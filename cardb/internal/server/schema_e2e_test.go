package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strconv"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/store"
)

// --- helpers ---------------------------------------------------------------------------

func newServerWithProfile(t *testing.T, p *profile.Profile) *client {
	t.Helper()
	dir := t.TempDir()
	st, err := store.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	st.SetProfile(p)
	t.Cleanup(func() { st.Close() })
	srv := httptest.NewServer(NewHandler(st, map[string]string{"agents": "tok-agents"}))
	t.Cleanup(srv.Close)
	return &client{t: t, base: srv.URL, token: "tok-agents", dir: dir}
}

// send is call with extra headers; returns status, body and headers.
func (c *client) send(method, path string, body any, hdr map[string]string) (int, []byte, http.Header) {
	c.t.Helper()
	j, err := json.Marshal(body)
	if err != nil {
		c.t.Fatal(err)
	}
	cp := *c
	cp.hdr = map[string]string{}
	for k, v := range c.hdr {
		cp.hdr[k] = v
	}
	for k, v := range hdr {
		cp.hdr[k] = v
	}
	return cp.raw(method, path, strings.NewReader(string(j)), "application/json")
}

type priceRejection struct {
	Error    string  `json:"error"`
	Reason   string  `json:"reason"`
	Price    int     `json:"price"`
	Expected *string `json:"expected"`
}

// rejectPrice upserts in, expects 422 with reason, and returns the body.
func (c *client) rejectPrice(in map[string]any, reason string) priceRejection {
	c.t.Helper()
	var rej priceRejection
	c.call("POST", "/api/v1/listings/upsert", in, 422, &rej)
	if rej.Reason != reason {
		c.t.Fatalf("upsert %v: reason %q, want %q (%s)", in, rej.Reason, reason, rej.Error)
	}
	return rej
}

func listingOf(d api.CarDetail, id int64) api.Listing {
	for _, l := range d.Listings {
		if l.ID == id {
			return l
		}
	}
	return api.Listing{}
}

func summaryOf(l api.CarList, id int64) *api.CarSummary {
	for i := range l.Cars {
		if l.Cars[i].ID == id {
			return &l.Cars[i]
		}
	}
	return nil
}

// --- powertrain ------------------------------------------------------------------------

func TestPowertrainRoundTripAndPatchMerge(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://example.invalid/pt/1", "make": "SYNTH", "model": "Volt One", "price": 30000,
		"powertrain": map[string]any{"fuel": "BEV", "battery_net_kwh": 77, "gearbox": "Automatic", "wltp_range_km": 520, "wltp_consumption": 16.5}})
	pt := c.car(r.CarID).Powertrain
	if pt == nil || *pt.Fuel != "bev" || *pt.BatteryNetKwh != 77 || *pt.Gearbox != "automatic" || *pt.WltpRangeKm != 520 ||
		*pt.WltpConsumption != 16.5 || pt.EngineCc != nil || pt.Co2GKm != nil {
		t.Fatalf("created powertrain: %s", mustJSONT(t, pt))
	}

	// Upsert fills empty powertrain fields only; filled fields keep their value and write no event.
	c.upsert(map[string]any{"url": "https://example.invalid/pt/1", "powertrain": map[string]any{"fuel": "phev", "co2_g_km": 0, "engine_cc": 1}})
	d := c.car(r.CarID)
	if *d.Powertrain.Fuel != "bev" || d.Powertrain.Co2GKm == nil || *d.Powertrain.Co2GKm != 0 || *d.Powertrain.EngineCc != 1 {
		t.Fatalf("fill-if-empty: %s", mustJSONT(t, d.Powertrain))
	}
	if n := len(eventsOfType(c.events(r.CarID), "spec_change")); n != 0 {
		t.Fatalf("filling empty fields wrote %d spec_change events", n)
	}
	// overwrite replaces and writes a spec_change event.
	c.upsert(map[string]any{"url": "https://example.invalid/pt/1", "overwrite": true, "powertrain": map[string]any{"fuel": "phev"}})
	sc := eventsOfType(c.events(r.CarID), "spec_change")
	if len(sc) != 1 || !strings.Contains(sc[0].Summary, "fuel bev → phev") {
		t.Fatalf("overwrite spec_change: %+v", sc)
	}

	// PATCH merges field by field: null clears one field, the rest stays.
	var p api.CarDetail
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", r.CarID), `{"powertrain": {"engine_cc": null, "co2_g_km": 32, "gearbox": "MANUAL"}}`, 200, &p)
	if pt := p.Powertrain; pt.EngineCc != nil || *pt.Co2GKm != 32 || *pt.Gearbox != "manual" || *pt.Fuel != "phev" || *pt.BatteryNetKwh != 77 || *pt.WltpRangeKm != 520 {
		t.Fatalf("patch merge: %s", mustJSONT(t, pt))
	}
	if sc := eventsOfType(c.events(r.CarID), "spec_change"); !strings.Contains(sc[0].Summary, "engine_cc 1 → —") {
		t.Fatalf("patch spec_change: %+v", sc[0])
	}
	// Pre-v2 clients may still send the battery flat.
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", r.CarID), `{"battery_net_kwh": 74.5}`, 200, &p)
	if *p.Powertrain.BatteryNetKwh != 74.5 {
		t.Fatalf("flat battery patch: %s", mustJSONT(t, p.Powertrain))
	}
	for _, bad := range []string{`{"powertrain": {"fuel": "steam"}}`, `{"powertrain": {"gearbox": "cvt"}}`, `{"powertrain": {"turbo": true}}`,
		`{"powertrain": {"engine_cc": -1}}`, `{"powertrain": "bev"}`, `{"fuel": "bev"}`} {
		c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", r.CarID), bad, 422, nil)
	}
	c.call("POST", "/api/v1/listings/upsert", map[string]any{"url": "https://example.invalid/pt/bad", "powertrain": map[string]any{"fuel": "steam"}}, 422, nil)

	// fuel filter: missing fuel = unknown; repeatable and comma lists; bad value 400.
	diesel := c.upsert(map[string]any{"url": "https://example.invalid/pt/2", "make": "SYNTH", "model": "Oil Two", "price": 20000,
		"powertrain": map[string]any{"fuel": "diesel", "engine_cc": 1968}}).CarID
	unknown := c.upsert(map[string]any{"url": "https://example.invalid/pt/3", "make": "SYNTH", "model": "Mystery", "price": 20000}).CarID
	sameIDs(t, "fuel=phev", ids(c.list("fuel=phev")), r.CarID)
	sameIDs(t, "fuel=unknown", ids(c.list("fuel=unknown")), unknown)
	sameIDs(t, "fuel=phev,diesel", ids(c.list("fuel=phev,diesel")), r.CarID, diesel)
	sameIDs(t, "fuel=diesel&fuel=UNKNOWN", ids(c.list("fuel=diesel&fuel=UNKNOWN")), diesel, unknown)
	c.call("GET", "/api/v1/cars?fuel=steam", nil, 400, nil)
	if s := summaryOf(c.list(""), diesel); s.Powertrain == nil || *s.Powertrain.EngineCc != 1968 {
		t.Fatalf("summary powertrain: %+v", s)
	}

	// "powertrain": null clears every field.
	var cleared api.CarDetail
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", diesel), `{"powertrain": null}`, 200, &cleared)
	if cleared.Powertrain != nil {
		t.Fatalf("powertrain null: %s", mustJSONT(t, cleared.Powertrain))
	}
}

func mustJSONT(t *testing.T, v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// --- versions ------------------------------------------------------------------------------

func TestIfMatchConflict(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://example.invalid/v/1", "make": "SYNTH", "model": "Shared", "price": 25000})
	path := fmt.Sprintf("/api/v1/cars/%d", r.CarID)

	status, body, hdr := c.send("GET", path, nil, nil)
	var d api.CarDetail
	if status != 200 || json.Unmarshal(body, &d) != nil {
		t.Fatalf("get: %d %s", status, body)
	}
	v0 := d.Version
	if v0 < 1 || hdr.Get("ETag") != strconv.Quote(strconv.FormatInt(v0, 10)) {
		t.Fatalf("ETag %q, version %d", hdr.Get("ETag"), v0)
	}
	etag := hdr.Get("ETag")

	// Two writers read the same version; the first wins, the second gets 412 with the current car.
	alice, bob := c.as("agent-a"), c.as("agent-b")
	status, body, hdr = alice.send("PATCH", path, map[string]any{"summary": "from A"}, map[string]string{"If-Match": etag})
	if status != 200 {
		t.Fatalf("writer A: %d %s", status, body)
	}
	var afterA api.CarDetail
	_ = json.Unmarshal(body, &afterA)
	if afterA.Version <= v0 || hdr.Get("ETag") != strconv.Quote(strconv.FormatInt(afterA.Version, 10)) {
		t.Fatalf("writer A: version %d (was %d), ETag %q", afterA.Version, v0, hdr.Get("ETag"))
	}
	status, body, _ = bob.send("PATCH", path, map[string]any{"summary": "from B"}, map[string]string{"If-Match": etag})
	var conflict struct {
		Error   string        `json:"error"`
		Version int64         `json:"version"`
		Car     api.CarDetail `json:"car"`
	}
	if status != 412 || json.Unmarshal(body, &conflict) != nil {
		t.Fatalf("writer B stale: %d %s", status, body)
	}
	if conflict.Error == "" || conflict.Version != afterA.Version || conflict.Car.ID != r.CarID || *conflict.Car.Summary != "from A" {
		t.Fatalf("412 body: %s", body)
	}
	if got := c.car(r.CarID); *got.Summary != "from A" || got.Version != afterA.Version {
		t.Fatalf("stale write changed the car: %+v", got.Summary)
	}
	// B re-reads and retries with the fresh version (bare number accepted too).
	status, body, _ = bob.send("PATCH", path, map[string]any{"summary": "from B"}, map[string]string{"If-Match": strconv.FormatInt(conflict.Version, 10)})
	if status != 200 || *c.car(r.CarID).Summary != "from B" {
		t.Fatalf("writer B retry: %d %s", status, body)
	}

	// Body `version` works like If-Match, on PATCH and on POST status.
	cur := c.car(r.CarID).Version
	c.call("PATCH", path, map[string]any{"km": 1000, "version": cur - 1}, 412, nil)
	c.call("POST", path+"/status", map[string]any{"status": "contacted", "version": cur - 1}, 412, nil)
	status, body, _ = c.send("POST", path+"/status", map[string]any{"status": "contacted"}, map[string]string{"If-Match": `"` + strconv.FormatInt(cur-1, 10) + `"`})
	if status != 412 {
		t.Fatalf("status with stale If-Match: %d %s", status, body)
	}
	var st api.CarDetail
	c.call("POST", path+"/status", map[string]any{"status": "contacted", "version": cur}, 200, &st)
	if st.Status != "contacted" || st.Version <= cur {
		t.Fatalf("status with fresh version: %s v%d", st.Status, st.Version)
	}
	// No precondition = last writer wins, as before; If-Match * = any version; garbage = 400.
	c.call("PATCH", path, map[string]any{"km": 1100}, 200, nil)
	if s, b, _ := c.send("PATCH", path, map[string]any{"km": 1200}, map[string]string{"If-Match": "*"}); s != 200 {
		t.Fatalf("If-Match *: %d %s", s, b)
	}
	if s, _, _ := c.send("PATCH", path, map[string]any{"km": 1300}, map[string]string{"If-Match": "abc"}); s != 400 {
		t.Fatalf("If-Match abc: %d", s)
	}

	// Anything shown on the car moves the version: a message, a note, an option, a listing price.
	bump := func(label string, write func()) {
		t.Helper()
		before := c.car(r.CarID).Version
		write()
		if after := c.car(r.CarID).Version; after <= before {
			t.Fatalf("%s: version %d → %d, want an increase", label, before, after)
		}
	}
	bump("message", func() {
		c.call("POST", "/api/v1/messages", map[string]any{"car": fmt.Sprint(r.CarID), "channel": "email", "direction": "in", "text": "still available"}, 201, nil)
	})
	bump("note", func() { c.call("POST", path+"/notes", map[string]any{"text": "call tomorrow"}, 201, nil) })
	bump("option", func() {
		c.call("PUT", path+"/options/heat_pump", map[string]any{"value": "yes", "source": "ad_text"}, 200, nil)
	})
	bump("price", func() { c.upsert(map[string]any{"url": "https://example.invalid/v/1", "price": 24000}) })
	if s := summaryOf(c.list(""), r.CarID); s.Version != c.car(r.CarID).Version {
		t.Fatalf("summary version %d != detail %d", s.Version, c.car(r.CarID).Version)
	}

	// A plain re-sighting (same data, later seen_at) and an idempotent add are not changes.
	same := func(label string, write func()) {
		t.Helper()
		before := c.car(r.CarID).Version
		write()
		if after := c.car(r.CarID).Version; after != before {
			t.Fatalf("%s: version %d → %d, want unchanged", label, before, after)
		}
	}
	same("re-sighting", func() { c.upsert(map[string]any{"url": "https://example.invalid/v/1", "price": 24000}) })
	c.call("PATCH", path, map[string]any{"red_flags_add": []string{"x"}}, 200, nil)
	same("idempotent add", func() { c.call("PATCH", path, map[string]any{"red_flags_add": []string{" x "}}, 200, nil) })
	same("rejected price", func() {
		c.call("POST", "/api/v1/listings/upsert", map[string]any{"url": "https://example.invalid/v/1", "price": 240}, 422, nil)
	})
}

// --- red_flags / open_questions ops ------------------------------------------------------

func TestListOpsConcurrentAgents(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://example.invalid/l/1", "make": "SYNTH", "model": "Listy", "price": 25000})
	path := fmt.Sprintf("/api/v1/cars/%d", r.CarID)
	c.call("PATCH", path, map[string]any{"red_flags": []string{"imported"}, "open_questions": []string{"service book?"}}, 200, nil)

	// Two agents add different items, each without knowing the other's; both survive.
	c.as("agent-a").call("PATCH", path, map[string]any{"red_flags_add": []string{"accident 2023"}}, 200, nil)
	c.as("agent-b").call("PATCH", path, map[string]any{"red_flags_add": []string{"no service book"}, "open_questions_add": []string{"second key?"}}, 200, nil)
	d := c.car(r.CarID)
	if !slices.Equal(d.RedFlags, []string{"imported", "accident 2023", "no service book"}) ||
		!slices.Equal(d.OpenQuestions, []string{"service book?", "second key?"}) {
		t.Fatalf("after adds: %q / %q", d.RedFlags, d.OpenQuestions)
	}

	// Add is idempotent (exact text after trim); remove of a missing item is a no-op; remove + add in one request.
	var p api.CarDetail
	c.call("PATCH", path, map[string]any{"red_flags_add": []string{"  accident 2023 "}, "red_flags_remove": []string{"not there"}}, 200, &p)
	if !slices.Equal(p.RedFlags, d.RedFlags) {
		t.Fatalf("idempotent add / missing remove changed the list: %q", p.RedFlags)
	}
	c.call("PATCH", path, map[string]any{"red_flags_remove": []string{"imported"}, "open_questions_remove": []string{"service book?"},
		"open_questions_add": []string{"tyres?"}}, 200, &p)
	if !slices.Equal(p.RedFlags, []string{"accident 2023", "no service book"}) || !slices.Equal(p.OpenQuestions, []string{"second key?", "tyres?"}) {
		t.Fatalf("after removes: %q / %q", p.RedFlags, p.OpenQuestions)
	}

	// A full replace and an op on the same list in one request is ambiguous → 422 (other lists may mix).
	c.call("PATCH", path, map[string]any{"red_flags": []string{"a"}, "red_flags_add": []string{"b"}}, 422, nil)
	c.call("PATCH", path, map[string]any{"red_flags": []string{"a"}, "open_questions_remove": []string{"tyres?"}}, 200, &p)
	if !slices.Equal(p.RedFlags, []string{"a"}) || !slices.Equal(p.OpenQuestions, []string{"second key?"}) {
		t.Fatalf("replace + other-list op: %q / %q", p.RedFlags, p.OpenQuestions)
	}
	c.call("PATCH", path, map[string]any{"red_flags_add": []string{""}}, 422, nil)
	c.call("PATCH", path, map[string]any{"red_flags_add": "x"}, 422, nil)
}

// --- price sanity ----------------------------------------------------------------------------

func TestPriceSanityRejectsX100(t *testing.T) {
	c := newServer(t)
	ad := func(n int, extra map[string]any) map[string]any {
		in := map[string]any{"url": fmt.Sprintf("https://example.invalid/p/%d", n), "make": "SYNTH", "model": fmt.Sprintf("Lone %d", n), "price": 31500}
		for k, v := range extra {
			in[k] = v
		}
		return in
	}

	// A normal price passes and leaves no flags.
	ok := c.upsert(ad(1, nil))
	d := c.car(ok.CarID)
	if l := listingOf(d, ok.ListingID); l.PriceVat != "unknown" || len(l.PriceFlags) != 0 {
		t.Fatalf("normal price: vat %q flags %v", l.PriceVat, l.PriceFlags)
	}

	// Absolute cap: ×100 when price/100 is plausible, else out of range; ≤ 0 is out of range.
	rej := c.rejectPrice(ad(2, map[string]any{"price": 3150000}), "price_x100")
	if rej.Price != 3150000 || rej.Expected == nil || !strings.Contains(*rej.Expected, "31 500") || !strings.Contains(rej.Error, "force") {
		t.Fatalf("x100 body: %+v", rej)
	}
	c.rejectPrice(ad(2, map[string]any{"price": 900000000}), "price_range")
	c.rejectPrice(ad(2, map[string]any{"price": 0}), "price_range")
	// Nothing of the rejected upserts was written.
	var found []api.Listing
	c.call("GET", "/api/v1/listings?url=https://example.invalid/p/2", nil, 200, &found)
	if len(found) != 0 {
		t.Fatalf("rejected upsert stored a listing: %+v", found)
	}

	// Family median (n ≥ 3 live cars): > 8× the median is ×100 even under the cap.
	for i, p := range []int{30000, 32000, 34000} {
		c.qcar(fmt.Sprintf("fam%d", i), map[string]any{"price": p})
	}
	rej = c.rejectPrice(map[string]any{"url": "https://example.invalid/q/x100", "make": "VW", "model": "ID.4 Pro", "price": 290000}, "price_x100")
	if rej.Expected == nil || !strings.Contains(*rej.Expected, "fair 32 000") || !strings.Contains(*rej.Expected, "n=3") {
		t.Fatalf("family x100 expected: %+v", rej.Expected)
	}
	c.qcar("dear", map[string]any{"price": 120000}) // 3.75× the median: expensive, not ×100

	// Lease: under search.price.min_eur (default 1 500), or monthly/lease wording with a price that is low.
	c.rejectPrice(ad(3, map[string]any{"price": 399}), "price_lease")
	c.rejectPrice(ad(3, map[string]any{"price": 9000, "price_note": "Renting 450 €/mês"}), "price_lease")
	c.rejectPrice(map[string]any{"url": "https://example.invalid/q/lease", "make": "VW", "model": "ID.4 Pro", "price": 7900, "title": "VW ID.4 Leasing"}, "price_lease")
	c.upsert(map[string]any{"url": "https://example.invalid/q/lease-ok", "make": "VW", "model": "ID.4 Pro", "price": 31000, "title": "VW ID.4 — Leasing möglich"})

	// Net: price_vat net, or net wording unless price_vat says gross/margin or gross wording is present.
	c.rejectPrice(ad(4, map[string]any{"price_vat": "net"}), "price_net")
	c.rejectPrice(ad(4, map[string]any{"title": "SYNTH Lone 4 — 31 500 € + IVA"}), "price_net")
	c.rejectPrice(ad(4, map[string]any{"price_note": "zzgl. MwSt."}), "price_net")
	c.upsert(ad(5, map[string]any{"price_note": "excl. VAT", "price_vat": "gross"}))
	c.upsert(ad(6, map[string]any{"price_note": "Brutto 31.500 / netto 26.470"}))
	c.upsert(ad(7, map[string]any{"price_vat": "MARGIN"}))
	c.call("POST", "/api/v1/listings/upsert", ad(8, map[string]any{"price_vat": "incl"}), 422, nil)
	// Re-upserting a stored price with a new price_vat re-checks it.
	c.rejectPrice(ad(1, map[string]any{"price_vat": "net"}), "price_net")
	c.upsert(ad(1, map[string]any{"price_vat": "gross"}))
	if l := listingOf(c.car(ok.CarID), ok.ListingID); l.PriceVat != "gross" {
		t.Fatalf("price_vat after upsert: %q", l.PriceVat)
	}

	// force: stored, flagged on the listing and the summary, override event; a replay of the same price is not
	// re-checked; a sane price clears the flags.
	forced := c.upsert(ad(9, map[string]any{"price": 3150000, "force": true}))
	d = c.car(forced.CarID)
	if l := listingOf(d, forced.ListingID); !slices.Equal(l.PriceFlags, []string{"price_x100"}) || *l.Price != 3150000 {
		t.Fatalf("forced listing: price %v flags %v", l.Price, l.PriceFlags)
	}
	if s := summaryOf(c.list(""), forced.CarID); !slices.Equal(s.PriceFlags, []string{"price_x100"}) {
		t.Fatalf("summary price_flags: %v", s.PriceFlags)
	}
	ov := eventsOfType(c.events(forced.CarID), "price_sanity_override")
	var data struct {
		Reason string `json:"reason"`
		Price  int    `json:"price"`
	}
	if len(ov) != 1 || json.Unmarshal(ov[0].Data, &data) != nil || data.Reason != "price_x100" || data.Price != 3150000 {
		t.Fatalf("override event: %+v", ov)
	}
	c.upsert(ad(9, map[string]any{"price": 3150000})) // replay without force: unchanged price, accepted
	if n := len(eventsOfType(c.events(forced.CarID), "price_sanity_override")); n != 1 {
		t.Fatalf("replay wrote another override event (%d)", n)
	}
	c.upsert(ad(9, map[string]any{"price": 31500}))
	if l := listingOf(c.car(forced.CarID), forced.ListingID); len(l.PriceFlags) != 0 || *l.Price != 31500 {
		t.Fatalf("after a sane price: %v %v", l.Price, l.PriceFlags)
	}
	if s := summaryOf(c.list(""), forced.CarID); len(s.PriceFlags) != 0 {
		t.Fatalf("summary flags after a sane price: %v", s.PriceFlags)
	}

	// PATCH /listings/{id}: same check, same force path, price_vat.
	lpath := fmt.Sprintf("/api/v1/listings/%d", ok.ListingID)
	c.call("PATCH", lpath, map[string]any{"price": 315000000}, 422, nil)
	var rj priceRejection
	c.call("PATCH", lpath, map[string]any{"price": 3150000}, 422, &rj)
	if rj.Reason != "price_x100" {
		t.Fatalf("patch listing reason %q", rj.Reason)
	}
	c.call("PATCH", lpath, map[string]any{"price_vat": "net"}, 422, nil) // re-checks the stored price as net
	var l api.Listing
	c.call("PATCH", lpath, map[string]any{"price": 3150000, "force": true}, 200, &l)
	if !slices.Equal(l.PriceFlags, []string{"price_x100"}) {
		t.Fatalf("patch listing forced flags %v", l.PriceFlags)
	}
	c.call("PATCH", lpath, map[string]any{"price": 31400, "price_vat": "gross"}, 200, &l)
	if len(l.PriceFlags) != 0 || l.PriceVat != "gross" || *l.Price != 31400 {
		t.Fatalf("patch listing sane: %+v", l)
	}
}

func TestPriceSanityProfileBounds(t *testing.T) {
	p := profile.Default()
	p.Search.Price.MinEUR = 5000
	p.Search.Price.CapEUR = 150000
	p.Search.Price.MaxEUR = 10000
	c := newServerWithProfile(t, p)
	ad := func(n, price int) map[string]any {
		return map[string]any{"url": fmt.Sprintf("https://example.invalid/b/%d", n), "make": "SYNTH", "model": "Bound", "price": price}
	}
	c.rejectPrice(ad(1, 4000), "price_lease")      // under min_eur
	c.rejectPrice(ad(1, 1600000), "price_x100")    // over cap_eur, ÷100 = 16 000 plausible
	c.rejectPrice(ad(1, 900000000), "price_range") // over cap, ÷100 still over
	c.rejectPrice(ad(1, 85000), "price_x100")      // no family data: > 8× max_eur
	c.upsert(ad(1, 60000))                         // over budget is not insane
	c.upsert(ad(2, 5000))                          // at min
	c.call("POST", "/api/v1/listings/upsert", ad(3, -1), 422, nil)
}

// GET /cars rows (CarSummary) and queue items carry `version`, equal to the detail's and rising on writes.
func TestCarListRowsCarryVersion(t *testing.T) {
	c := newServer(t)
	id := c.qcar("ver", nil)
	rowVersion := func(path string, pick func(map[string]any) []any) float64 {
		t.Helper()
		var raw map[string]any
		c.call("GET", path, nil, 200, &raw)
		for _, r := range pick(raw) {
			row := r.(map[string]any)
			if car, ok := row["car"].(map[string]any); ok {
				row = car
			}
			if row["id"] == float64(id) {
				v, ok := row["version"].(float64)
				if !ok {
					t.Fatalf("%s: row without a numeric version: %v", path, row)
				}
				return v
			}
		}
		t.Fatalf("%s: car %d not listed", path, id)
		return 0
	}
	cars := func(m map[string]any) []any { return m["cars"].([]any) }
	items := func(m map[string]any) []any { return m["items"].([]any) }

	v1 := rowVersion("/api/v1/cars", cars)
	if v1 < 1 || int64(v1) != c.car(id).Version || rowVersion("/api/v1/queue?tier=1,2,3", items) != v1 {
		t.Fatalf("list version %v, detail %d", v1, c.car(id).Version)
	}
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", id), map[string]any{"summary": "x"}, 200, nil)
	if v2 := rowVersion("/api/v1/cars", cars); v2 <= v1 || int64(v2) != c.car(id).Version {
		t.Fatalf("list version after write %v (was %v), detail %d", v2, v1, c.car(id).Version)
	}
}

// Pre-v2 clients send the battery flat; upsert and POST /cars fold it into powertrain (fill-if-empty like any
// spec) instead of dropping it, and a flat value that contradicts a nested one is 422.
func TestUpsertLegacyFlatBattery(t *testing.T) {
	c := newServer(t)
	u := "https://example.invalid/legacy/1"
	r := c.upsert(map[string]any{"url": u, "make": "SYNTH", "model": "Old Client", "price": 30000, "battery_net_kwh": 77, "battery_gross_kwh": 82})
	pt := c.car(r.CarID).Powertrain
	if pt == nil || *pt.BatteryNetKwh != 77 || *pt.BatteryGrossKwh != 82 || pt.Fuel != nil {
		t.Fatalf("flat battery on create: %s", mustJSONT(t, pt))
	}
	// Fill-if-empty: an existing value stays, overwrite replaces it.
	c.upsert(map[string]any{"url": u, "battery_net_kwh": 70})
	if v := *c.car(r.CarID).Powertrain.BatteryNetKwh; v != 77 {
		t.Fatalf("flat battery overwrote without overwrite: %v", v)
	}
	c.upsert(map[string]any{"url": u, "battery_net_kwh": 74, "overwrite": true})
	if v := *c.car(r.CarID).Powertrain.BatteryNetKwh; v != 74 {
		t.Fatalf("flat battery with overwrite: %v", v)
	}
	// Flat + nested: same value is fine and merges with other nested fields; different values are 422.
	r2 := c.upsert(map[string]any{"url": "https://example.invalid/legacy/2", "make": "SYNTH", "model": "Mixed", "price": 30000,
		"battery_net_kwh": 60, "powertrain": map[string]any{"battery_net_kwh": 60, "fuel": "bev"}})
	if pt := c.car(r2.CarID).Powertrain; *pt.BatteryNetKwh != 60 || *pt.Fuel != "bev" {
		t.Fatalf("flat + nested agreeing: %s", mustJSONT(t, pt))
	}
	var e api.Error
	c.call("POST", "/api/v1/listings/upsert", map[string]any{"url": "https://example.invalid/legacy/3", "price": 30000,
		"battery_gross_kwh": 64, "powertrain": map[string]any{"battery_gross_kwh": 66}}, 422, &e)
	if !strings.Contains(e.Error, "battery_gross_kwh") {
		t.Fatalf("conflict error: %q", e.Error)
	}
	var found []api.Listing
	c.call("GET", "/api/v1/listings?url=https://example.invalid/legacy/3", nil, 200, &found)
	if len(found) != 0 {
		t.Fatal("conflicting upsert stored a listing")
	}
	// POST /cars takes the same path.
	var d api.CarDetail
	c.call("POST", "/api/v1/cars", map[string]any{"make": "SYNTH", "model": "Direct", "battery_net_kwh": 58}, 201, &d)
	if d.Powertrain == nil || *d.Powertrain.BatteryNetKwh != 58 {
		t.Fatalf("POST /cars flat battery: %s", mustJSONT(t, d.Powertrain))
	}
	// Reads only ever nest.
	_, body, _ := c.send("GET", fmt.Sprintf("/api/v1/cars/%d", d.ID), nil, nil)
	if strings.Count(string(body), `"battery_net_kwh"`) != 1 || !strings.Contains(string(body), `"powertrain":{"battery_net_kwh":58`) {
		t.Fatalf("read shape: flat battery key leaked: %s", body)
	}
}
