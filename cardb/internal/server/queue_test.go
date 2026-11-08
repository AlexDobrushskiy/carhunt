package server

import (
	"fmt"
	"slices"
	"strings"
	"testing"
	"time"

	"carhunt/cardb/internal/api"
)

var queueT0 = time.Date(2026, 10, 1, 9, 0, 0, 0, time.UTC)

// qcar upserts an eligible T1 car (VW ID.4 Pro 286 hp RWD, 2024, PT) with fields overridden; nil deletes a field.
func (c *client) qcar(tag string, fields map[string]any) int64 {
	c.t.Helper()
	in := map[string]any{
		"url": "https://example.invalid/q/" + tag, "make": "VW", "model": "ID.4 Pro", "reg_date": "2024-03", "km": 20000,
		"price": 35000, "power_kw": 210, "drive": "rwd", "country": "PT", "city": "Porto",
	}
	for k, v := range fields {
		if v == nil {
			delete(in, k)
		} else {
			in[k] = v
		}
	}
	return c.upsert(in).CarID
}

func (c *client) queue(query string) api.Queue {
	c.t.Helper()
	var q api.Queue
	c.call("GET", "/api/v1/queue?"+query, nil, 200, &q)
	return q
}

func queueIDs(q api.Queue) []int64 {
	out := []int64{}
	for _, it := range q.Items {
		out = append(out, it.Car.ID)
	}
	return out
}

func queueItem(t *testing.T, q api.Queue, id int64) api.QueueItem {
	t.Helper()
	for _, it := range q.Items {
		if it.Car.ID == id {
			return it
		}
	}
	t.Fatalf("car %d not in queue %v", id, queueIDs(q))
	return api.QueueItem{}
}

func setFact(c *client, id int64, key, value string) {
	c.t.Helper()
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/facts/%s", id, key), map[string]any{"value": value}, 200, nil)
}

func TestQueueEligibility(t *testing.T) {
	c := newServer(t)
	in := map[string]int64{}
	out := map[string]int64{}
	in["base"] = c.qcar("base", nil)

	// Verdict: rated leaves, cleared comes back.
	out["verdict"] = c.qcar("verdict", nil)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", out["verdict"]), map[string]any{"value": "maybe"}, 200, nil)
	in["verdict cleared"] = c.qcar("verdict-cleared", nil)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", in["verdict cleared"]), map[string]any{"value": "down"}, 200, nil)
	c.call("DELETE", fmt.Sprintf("/api/v1/cars/%d/verdict", in["verdict cleared"]), nil, 204, nil)

	// Status.
	for _, st := range []string{"closed", "dropped", "bought"} {
		out["status "+st] = c.qcar("st-"+st, nil)
		c.call("POST", fmt.Sprintf("/api/v1/cars/%d/status", out["status "+st]), map[string]any{"status": st}, 200, nil)
	}
	in["status talking"] = c.qcar("st-talking", nil)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/status", in["status talking"]), map[string]any{"status": "talking"}, 200, nil)

	// Listings: removed-only and sold-only leave; removed + live stays.
	out["removed only"] = c.qcar("removed", map[string]any{"listing_status": "removed"})
	out["sold only"] = c.qcar("sold", map[string]any{"listing_status": "sold"})
	in["removed + live"] = c.qcar("removed-live", map[string]any{"listing_status": "removed"})
	c.upsert(map[string]any{"url": "https://example.invalid/q/removed-live-2", "car": fmt.Sprint(in["removed + live"]), "price": 34000})

	// Hard filters; limits inclusive; unknown passes.
	out["year 2022"] = c.qcar("y22", map[string]any{"reg_date": "2022-12"})
	in["year 2023"] = c.qcar("y23", map[string]any{"reg_date": "2023-01"})
	in["year unknown"] = c.qcar("y-unknown", map[string]any{"reg_date": nil})
	out["price 42001"] = c.qcar("p-over", map[string]any{"price": 42001})
	in["price 42000"] = c.qcar("p-max", map[string]any{"price": 42000})
	in["price unknown"] = c.qcar("p-unknown", map[string]any{"price": nil})
	out["km 50001"] = c.qcar("km-over", map[string]any{"km": 50001})
	in["km 50000"] = c.qcar("km-max", map[string]any{"km": 50000})
	in["km unknown"] = c.qcar("km-unknown", map[string]any{"km": nil})
	for _, cc := range []string{"ES", "DE", "FR", "BE", "NL", "LU", "IT"} {
		in["country "+cc] = c.qcar("c-"+cc, map[string]any{"country": cc, "city": nil})
	}
	out["country PL"] = c.qcar("c-PL", map[string]any{"country": "PL", "city": nil})
	out["country CH"] = c.qcar("c-CH", map[string]any{"country": "CH", "city": nil})
	in["country unknown"] = c.qcar("c-unknown", map[string]any{"country": nil, "city": nil})
	// exclude_regions PT-20 PT-30 ES-CN: matched on the city; a known country must be the region's.
	for i, cc := range [][2]string{{"Funchal (Madeira)", "PT"}, {"Las Palmas De Gran Canaria", "ES"}, {"Ponta Delgada", "PT"},
		{"Santa Cruz De Tenerife", "ES"}, {"Açores", ""}} {
		out["island "+cc[0]] = c.qcar(fmt.Sprintf("isl-%d", i), map[string]any{"city": cc[0], "country": cc[1]})
	}
	in["city Palmela"] = c.qcar("palmela", map[string]any{"city": "Palmela"})
	in["Mallorca (ES-IB not excluded)"] = c.qcar("mallorca", map[string]any{"city": "Palma de Mallorca", "country": "ES"})

	// Lease transfer / declared damage flags.
	out["lease transfer"] = c.qcar("lease", nil)
	setFact(c, out["lease transfer"], "lease_transfer", "yes (Leasingübernahme)")
	in["lease transfer no"] = c.qcar("lease-no", nil)
	setFact(c, in["lease transfer no"], "lease_transfer", "no")

	// History facts (origin/import/history_report/other) naming PL/LT/LV/EE.
	for key, val := range map[string]string{"origin": "Imported from Poland (ad)", "import": "importado da Lituânia",
		"history_report": "Carfax: registered in Latvija 2023", "other": "ex Estland, 2 owners"} {
		id := c.qcar("hist-"+key, nil)
		setFact(c, id, key, val)
		out["history "+key] = id
	}
	for key, val := range map[string]string{"origin": "Imported from Germany (ad)", "import": "yes (leboncoin is_import)",
		"other": "dealer speaks DE/RU/EN/PL; filtro de polen nuevo", "photos_seen": "Polish plates"} {
		id := c.qcar("hist-ok-"+key, nil)
		setFact(c, id, key, val)
		in["history ok "+key] = id
	}

	// Suspect deal flag.
	out["suspect"] = c.qcar("suspect", nil)
	setFact(c, out["suspect"], "deal_flag", "suspect")
	in["deal_flag other"] = c.qcar("flag-ok", nil)
	setFact(c, in["deal_flag other"], "deal_flag", "cheap")

	q := c.queue("tier=1,2,3&limit=1000")
	got := queueIDs(q)
	for name, id := range in {
		if !slices.Contains(got, id) {
			t.Errorf("%s (car %d) missing from the queue", name, id)
		}
	}
	for name, id := range out {
		if slices.Contains(got, id) {
			t.Errorf("%s (car %d) is in the queue", name, id)
		}
	}
	if q.Total != len(in) || len(q.Items) != len(in) {
		t.Fatalf("total %d / items %d, want %d", q.Total, len(q.Items), len(in))
	}

	// removed_listing_count on summaries (queue + list).
	if it := queueItem(t, q, in["removed + live"]); it.Car.RemovedListingCount != 1 || it.Car.LiveListingCount != 1 || it.Car.ListingCount != 2 {
		t.Fatalf("removed + live counts: %+v", it.Car)
	}
	for _, cs := range c.list("limit=1000").Cars {
		want := 0
		if cs.ID == out["removed only"] || cs.ID == in["removed + live"] {
			want = 1
		}
		if cs.RemovedListingCount != want {
			t.Fatalf("car %d removed_listing_count %d, want %d", cs.ID, cs.RemovedListingCount, want)
		}
	}

	// Unknowns show in the why line.
	for name, label := range map[string]string{"year unknown": "? year", "km unknown": "? km", "price unknown": "? price", "country unknown": "? country"} {
		if why := queueItem(t, q, in[name]).Why; !strings.Contains(why, label) {
			t.Errorf("%s: why %q lacks %q", name, why, label)
		}
	}
	if why := queueItem(t, q, in["base"]).Why; strings.Contains(why, "? year") || strings.Contains(why, "? power") {
		t.Errorf("base why lists known fields as unknown: %q", why)
	}
}

func TestQueueTiers(t *testing.T) {
	c := newServer(t)
	cases := []struct {
		name   string
		fields map[string]any
		want   int
	}{
		{"ID.4 Pro 210 rwd", nil, 1},
		{"ID.5 Pro power unknown", map[string]any{"model": "ID.5 Pro", "power_kw": nil, "drive": nil}, 1},
		{"ID.4 no marker, 210 kW", map[string]any{"model": "ID.4", "variant": "Style"}, 1},
		{"ID.5 power_kw wrong, text 286", map[string]any{"model": "ID.5 Pro", "variant": "Pro Business (1) 77 kWh accu, 210 kW / 286 pk", "power_kw": 77}, 1},
		{"ID.4 GTX", map[string]any{"model": "ID.4 GTX", "power_kw": 250, "drive": "awd"}, 3},
		{"ID.4 GTX no data", map[string]any{"model": "ID.4 GTX", "power_kw": nil, "drive": nil}, 3},
		{"ID.4 Pure", map[string]any{"model": "ID.4 Pure", "power_kw": nil}, 3},
		{"ID.4 Pro 128 kW", map[string]any{"power_kw": 128}, 3},
		{"ID.4 Pro Performance power unknown", map[string]any{"model": "ID.4 Pro Performance", "power_kw": nil}, 3},
		{"Q4 45", map[string]any{"make": "Audi", "model": "Q4 e-tron 45", "variant": "S line"}, 1},
		{"Q4 Sportback 45 power unknown", map[string]any{"make": "Audi", "model": "Q4 Sportback e-tron", "variant": "45 Black Edition", "power_kw": nil, "drive": nil}, 1},
		{"Q4 45 quattro", map[string]any{"make": "Audi", "model": "Q4 e-tron 45 quattro", "drive": "awd"}, 3},
		{"Q4 45 quattro drive unknown", map[string]any{"make": "Audi", "model": "Q4 e-tron", "variant": "45 quattro", "power_kw": nil, "drive": nil}, 3},
		{"Q4 45 2023", map[string]any{"make": "Audi", "model": "Q4 e-tron 45", "reg_date": "2023-10"}, 3},
		{"Q4 40", map[string]any{"make": "Audi", "model": "Q4 e-tron 40", "power_kw": 150}, 3},
		{"Enyaq 85", map[string]any{"make": "Skoda", "model": "Enyaq 85", "drive": "unknown"}, 1},
		{"Enyaq Coupé 85 power unknown", map[string]any{"make": "Škoda", "model": "Enyaq", "variant": "Coupé 85", "power_kw": nil}, 1},
		{"Enyaq 85x", map[string]any{"make": "Skoda", "model": "Enyaq 85x", "drive": "awd"}, 3},
		{"Enyaq 85x drive unknown", map[string]any{"make": "Skoda", "model": "Enyaq", "variant": "85x Sportline", "power_kw": nil, "drive": nil}, 3},
		{"Enyaq RS", map[string]any{"make": "Skoda", "model": "Enyaq RS", "power_kw": nil}, 3},
		{"Ioniq 5 77 kWh", map[string]any{"make": "Hyundai", "model": "Ioniq 5", "power_kw": 168, "powertrain": map[string]any{"battery_net_kwh": 77}}, 2},
		{"Ioniq 5 84 marker", map[string]any{"make": "Hyundai", "model": "IONIQ 5", "variant": "84KWH N Line", "power_kw": nil}, 2},
		{"Ioniq 5 58 kWh", map[string]any{"make": "Hyundai", "model": "Ioniq 5", "variant": "58 kWh", "power_kw": 125, "powertrain": map[string]any{"battery_net_kwh": 58}}, 3},
		{"EV6 Air", map[string]any{"make": "Kia", "model": "EV6", "variant": "Air", "power_kw": 168}, 2},
		{"EV6 GT-Line", map[string]any{"make": "Kia", "model": "EV6", "variant": "GT-Line", "power_kw": 168}, 3},
		{"EV6 GT", map[string]any{"make": "Kia", "model": "EV6 GT", "power_kw": 430, "drive": "awd"}, 3},
		{"XPeng G6", map[string]any{"make": "XPeng", "model": "G6", "variant": "Performance AWD", "power_kw": 350, "drive": "awd"}, 2},
		{"Tavascan Endurance", map[string]any{"make": "Cupra", "model": "Tavascan", "variant": "Endurance"}, 2},
		{"Tavascan Endurance power unknown", map[string]any{"make": "Cupra", "model": "Tavascan", "variant": "77kWh Endurance", "power_kw": nil}, 2},
		{"Tavascan VZ AWD", map[string]any{"make": "Cupra", "model": "Tavascan VZ", "power_kw": 250, "drive": "awd"}, 3},
		{"Tavascan VZ power unknown", map[string]any{"make": "Cupra", "model": "Tavascan", "variant": "VZ", "power_kw": nil, "drive": nil}, 3},
		{"EQA", map[string]any{"make": "Mercedes", "model": "EQA 250", "power_kw": 140, "drive": "fwd"}, 3},
	}
	tierOf := map[int64]int{}
	names := map[int64]string{}
	want := map[int][]int64{}
	for i, tc := range cases {
		id := c.qcar(fmt.Sprintf("tier-%d", i), tc.fields)
		tierOf[id], names[id] = tc.want, tc.name
		want[tc.want] = append(want[tc.want], id)
	}
	for _, cs := range c.list("limit=1000").Cars {
		if cs.Tier != tierOf[cs.ID] {
			t.Errorf("%s: summary tier %d, want %d", names[cs.ID], cs.Tier, tierOf[cs.ID])
		}
	}
	for tier := 1; tier <= 3; tier++ {
		var l api.CarList
		c.call("GET", fmt.Sprintf("/api/v1/cars?tier=%d", tier), nil, 200, &l)
		sameIDs(t, fmt.Sprintf("GET /cars?tier=%d", tier), ids(l), want[tier]...)
	}
	var l api.CarList
	c.call("GET", "/api/v1/cars?tier=1,2", nil, 200, &l)
	sameIDs(t, "GET /cars?tier=1,2", ids(l), append(slices.Clone(want[1]), want[2]...)...)
	c.call("GET", "/api/v1/cars?tier=5", nil, 400, nil)

	// tier param + counts (counts ignore the param).
	wantCounts := map[string]int{"1": len(want[1]), "2": len(want[2]), "3": len(want[3])}
	for query, tiers := range map[string][]int{"": {1, 2}, "tier=1,2": {1, 2}, "tier=3": {3}, "tier=1&tier=3": {1, 3}, "tier=T2": {2}, "tier=1,2,3": {1, 2, 3}} {
		q := c.queue(query + "&limit=1000")
		var exp []int64
		for _, tr := range tiers {
			exp = append(exp, want[tr]...)
		}
		sameIDs(t, "queue "+query, queueIDs(q), exp...)
		if q.Total != len(exp) {
			t.Errorf("queue %s: total %d, want %d", query, q.Total, len(exp))
		}
		for k, n := range wantCounts {
			if q.Counts[k] != n {
				t.Errorf("queue %s: counts %v, want %v", query, q.Counts, wantCounts)
			}
		}
		for _, it := range q.Items {
			if it.Tier != tierOf[it.Car.ID] || it.Car.Tier != it.Tier {
				t.Errorf("queue %s: %s tier %d/%d", query, names[it.Car.ID], it.Tier, it.Car.Tier)
			}
		}
	}
	for _, bad := range []string{"tier=4", "tier=x", "tier=0", "limit=-1", "offset=x"} {
		c.call("GET", "/api/v1/queue?"+bad, nil, 400, nil)
	}

	// Power-unknown marker path: T1 by marker, the why line says "? power".
	q := c.queue("tier=1&limit=1000")
	for _, it := range q.Items {
		if strings.Contains(names[it.Car.ID], "power unknown") != strings.Contains(it.Why, "? power") {
			t.Errorf("%s: why %q", names[it.Car.ID], it.Why)
		}
	}
}

func TestQueueOrder(t *testing.T) {
	at := func(h int) string { return queueT0.Add(time.Duration(h) * time.Hour).Format(time.RFC3339) }
	order := func(c *client) []int64 { return queueIDs(c.queue("tier=1,2,3&limit=1000")) }
	expect := func(t *testing.T, label string, got []int64, want ...int64) {
		t.Helper()
		if !slices.Equal(got, want) {
			t.Fatalf("%s: order %v, want %v", label, got, want)
		}
	}

	t.Run("tier", func(t *testing.T) {
		c := newServer(t)
		t2 := c.qcar("t2", map[string]any{"make": "Kia", "model": "EV6", "power_kw": 168, "seen_at": at(3)})
		c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/good-deal", t2), map[string]any{"good_deal": true}, 200, nil)
		t3 := c.qcar("t3", map[string]any{"make": "Mercedes", "model": "EQA", "power_kw": 140, "seen_at": at(2)})
		t1 := c.qcar("t1", map[string]any{"seen_at": at(1)})
		expect(t, "tier", order(c), t1, t2, t3)
	})

	t.Run("good deal then deal rank", func(t *testing.T) {
		c := newServer(t)
		rank := func(tag, r string, h int) int64 {
			id := c.qcar(tag, map[string]any{"seen_at": at(h)})
			if r != "" {
				setFact(c, id, "deal_rank", r)
			}
			return id
		}
		missing := rank("missing", "", 9) // newest: would be first on created_at
		odd := rank("odd", "watch", 8)
		r10 := rank("r10", "T1-10", 7)
		r2 := rank("r2", "T1-2", 6)
		r21 := rank("r21", "T2-1", 5)
		gdNoRank := rank("gd", "", 1)
		gdRank := rank("gd-rank", "T1-5", 0)
		for _, id := range []int64{gdNoRank, gdRank} {
			c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/good-deal", id), map[string]any{"good_deal": true, "note": "cheap"}, 200, nil)
		}
		expect(t, "deal", order(c), gdRank, gdNoRank, r2, r10, r21, odd, missing)
	})

	t.Run("score", func(t *testing.T) {
		c := newServer(t)
		plain := c.qcar("plain", map[string]any{"seen_at": at(9)})
		reseller := c.qcar("reseller", map[string]any{"seen_at": at(8), "seller": map[string]any{"type": "reseller", "name": "SYNTH Trade"}})
		vetted := c.qcar("vetted", map[string]any{"seen_at": at(1), "vin": "SYN4ZZZE2ZRP00001", "options": map[string]any{
			"electric_seats": map[string]any{"value": "yes"}, "power_tailgate": map[string]any{"value": "yes"}}})
		for k, v := range map[string]string{"owners": "1", "service_history": "yes", "accidents": "none", "battery_soh": "95 %"} {
			setFact(c, vetted, k, v)
		}
		expect(t, "score", order(c), vetted, plain, reseller)
		q := c.queue("")
		for _, it := range q.Items {
			if it.Score == nil || it.Value == nil || *it.Value != 50 || it.Landed == nil || it.FairPrice != nil || it.Risk <= 0 || len(it.RiskReasons) == 0 {
				t.Fatalf("item %d: %+v", it.Car.ID, it)
			}
		}
		if it := queueItem(t, q, reseller); !slices.Contains(it.RiskReasons, "reseller +4") {
			t.Fatalf("reseller reasons %q", it.RiskReasons)
		}
		if it := queueItem(t, q, vetted); it.Fit <= queueItem(t, q, plain).Fit || it.Risk >= queueItem(t, q, plain).Risk {
			t.Fatalf("vetted fit/risk: %v %v", it.Fit, it.Risk)
		}
	})

	t.Run("landed breaks score ties", func(t *testing.T) {
		c := newServer(t)
		// No peers (n < 3): value 50 for both, equal score; the cheaper landed cost wins over the newer car.
		cheap := c.qcar("cheap", map[string]any{"price": 30000, "seen_at": at(1)})
		dear := c.qcar("dear", map[string]any{"price": 35000, "seen_at": at(2)})
		noPrice := c.qcar("noprice", map[string]any{"price": nil, "seen_at": at(9)})
		expect(t, "landed", order(c), cheap, dear, noPrice)
		q := c.queue("")
		if it := queueItem(t, q, cheap); *it.Landed != 30165 || *it.Score != *queueItem(t, q, dear).Score {
			t.Fatalf("cheap: landed %v score %v", *it.Landed, *it.Score)
		}
		if it := queueItem(t, q, noPrice); it.Score != nil || it.Value != nil || it.Landed != nil {
			t.Fatalf("no price: %+v", it)
		}
	})

	t.Run("created then id", func(t *testing.T) {
		c := newServer(t)
		old := c.qcar("old", map[string]any{"seen_at": at(1)})
		newer := c.qcar("new", map[string]any{"seen_at": at(5)})
		sameA := c.qcar("same-a", map[string]any{"seen_at": at(3)})
		sameB := c.qcar("same-b", map[string]any{"seen_at": at(3)})
		expect(t, "created", order(c), newer, sameB, sameA, old)
		q := c.queue("limit=2&offset=1")
		if len(q.Items) != 2 || q.Total != 4 || q.Items[0].Position != 2 || q.Items[0].Car.ID != sameB || q.Items[1].Position != 3 {
			t.Fatalf("paging: total %d %+v", q.Total, queueIDs(q))
		}
	})
}

func TestQueueFairPrice(t *testing.T) {
	c := newServer(t)
	// VW ID.4 Pro 2024, 20 000 km: PT asks (one rated, one over the price cap — both still peers), a removed-only and an
	// unpriced car (both ignored), and one ES ask 950 km away.
	a := c.qcar("a", map[string]any{"price": 30000})
	rated := c.qcar("rated", map[string]any{"price": 32000})
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", rated), map[string]any{"value": "down"}, 200, nil)
	c.qcar("dear", map[string]any{"price": 45000})
	c.qcar("other", map[string]any{"price": 33000})
	c.qcar("gone", map[string]any{"price": 10000, "listing_status": "removed"})
	c.qcar("unpriced", map[string]any{"price": nil})
	es := c.qcar("es", map[string]any{"price": 30000, "country": "ES", "city": "Vigo", "distance_km": 950})
	// Audi Q4: two cars → no fair price. Unmapped family.
	q4 := c.qcar("q4", map[string]any{"make": "Audi", "model": "Q4 e-tron 45", "price": 40000})
	c.qcar("q4b", map[string]any{"make": "Audi", "model": "Q4 e-tron 45", "price": 41000})
	odd := c.qcar("odd", map[string]any{"make": "Foo", "model": "Bar", "price": 30000})

	q := c.queue("tier=1,2,3")
	// a: peers rated/dear/other (PT) + es → median of country medians: PT 33000, ES 30000 → 31500. Landed: PT
	// 32165/33165/45165 → 33165 (+100 trip +65 registration, default distance 250), ES 30888 → 32026.5 → 32050.
	it := queueItem(t, q, a)
	if *it.FairPrice != 31500 || *it.FairLanded != 32050 || it.FairN != 4 || deref(it.FairBasis) != "VW ID.4 · ~275 hp 2wd" ||
		*it.Landed != 30165 || *it.PriceGapPct != 5.9 || *it.Value != 61.8 {
		t.Fatalf("a: fair %v/%v n %d basis %v landed %v gap %v value %v", *it.FairPrice, *it.FairLanded, it.FairN, deref(it.FairBasis),
			*it.Landed, *it.PriceGapPct, *it.Value)
	}
	if !strings.Contains(it.Why, "−6 % vs ID.4 · ~275 hp 2wd (n=4)") {
		t.Fatalf("a why: %q", it.Why)
	}
	// es: landed 30000 + 100 + 250 + 0.135·950 + 1 night 100 + food 60 + import 250 = 30888; peers all PT.
	it = queueItem(t, q, es)
	if *it.Landed != 30888 || *it.FairPrice != 32500 || *it.FairLanded != 32650 || *it.PriceGapPct != 5.4 || deref(it.Car.Market) != "abroad" {
		t.Fatalf("es: landed %v fair %v/%v gap %v", *it.Landed, *it.FairPrice, *it.FairLanded, *it.PriceGapPct)
	}
	for _, id := range []int64{q4, odd} {
		if it := queueItem(t, q, id); it.FairPrice != nil || it.FairN != 0 || it.FairBasis != nil || it.PriceGapPct != nil || *it.Value != 50 || strings.Contains(it.Why, " vs ") {
			t.Fatalf("car %d: want no fair price, got %+v", id, it)
		}
	}
	// Raw JSON shape: nulls present, counts keyed by every profile tier.
	body := string(c.call("GET", "/api/v1/queue?tier=3", nil, 200, nil))
	for _, s := range []string{`"total":`, `"counts":{"1":`, `"3":`, `"items":[`, `"fair_price":null`, `"fair_landed":null`, `"fair_basis":null`,
		`"price_gap_pct":null`, `"fair_n":0`, `"score":`, `"value":50`, `"fit":`, `"risk":`, `"risk_reasons":[`, `"landed":`, `"trim_score":0`,
		`"trim_score_source":"options"`, `"position":1`, `"removed_listing_count":0`, `"tier":3`} {
		if !strings.Contains(body, s) {
			t.Fatalf("queue JSON lacks %s: %s", s, body)
		}
	}
}

func TestQueueWhyGoodDeal(t *testing.T) {
	c := newServer(t)
	id := c.qcar("gd", map[string]any{"options": map[string]any{"electric_seats": map[string]any{"value": "yes"}}})
	plain := c.qcar("plain", map[string]any{"power_kw": nil, "options": map[string]any{"electric_seats": map[string]any{"value": "yes"},
		"power_tailgate": map[string]any{"value": "yes"}, "pano": map[string]any{"value": "no"}}})
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/good-deal", id), map[string]any{"good_deal": true, "note": "T1 cheapest with e-seats"}, 200, nil)
	q := c.queue("")
	if why := queueItem(t, q, id).Why; why != "T1 cheapest with e-seats" {
		t.Fatalf("good deal why: %q", why)
	}
	if why := queueItem(t, q, plain).Why; why != "✓ e-seats · ✓ tailgate · ✗ pano · ? power" {
		t.Fatalf("plain why: %q", why)
	}
	if q.Items[0].Car.ID != id {
		t.Fatalf("good deal not first: %v", queueIDs(q))
	}
}

func TestQueueSpecFilter(t *testing.T) {
	c := newServer(t)
	opt := func(seats, tailgate string) map[string]any {
		o := map[string]any{}
		if seats != "" {
			o["electric_seats"] = map[string]any{"value": seats, "source": "ad_text"}
		}
		if tailgate != "" {
			o["power_tailgate"] = map[string]any{"value": tailgate, "source": "photo"}
		}
		return map[string]any{"options": o}
	}
	both := c.qcar("spec-both", opt("yes", "yes"))
	half := c.qcar("spec-half", opt("yes", ""))
	none := c.qcar("spec-none", nil)
	noSeats := c.qcar("spec-no", opt("no", "yes"))

	ids := func(q api.Queue) map[int64]bool {
		m := map[int64]bool{}
		for _, id := range queueIDs(q) {
			m[id] = true
		}
		return m
	}
	if q := ids(c.queue("")); !q[both] || !q[half] || !q[none] || !q[noSeats] {
		t.Fatalf("unfiltered queue misses a car: %v", q)
	}
	conf := c.queue("spec=confirmed")
	if got := queueIDs(conf); len(got) != 1 || got[0] != both || conf.Total != 1 {
		t.Fatalf("spec=confirmed = %v total %d", got, conf.Total)
	}
	if src := conf.Items[0].Car.OptionSources; src["electric_seats"] != "ad_text" || src["power_tailgate"] != "photo" {
		t.Fatalf("option_sources = %v", src)
	}
	unk := ids(c.queue("spec=unknown"))
	if len(unk) != 2 || !unk[half] || !unk[none] {
		t.Fatalf("spec=unknown = %v", unk)
	}
	c.call("GET", "/api/v1/queue?spec=maybe", nil, 400, nil)
}
