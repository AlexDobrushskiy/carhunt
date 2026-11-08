package server

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
)

func writeProfile(t *testing.T, y string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(y), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestProfileEndpoint(t *testing.T) {
	c := newServer(t)
	var p api.Profile
	body := string(c.call("GET", "/api/v1/profile", nil, 200, &p))
	if p.Owner.Name != "owner" || p.Owner.Home.Country != "PT" || len(p.Users) != 1 || p.Users[0].Role != "owner" {
		t.Fatalf("owner/users: %+v %+v", p.Owner, p.Users)
	}
	if len(p.Tiers) != 3 || p.Tiers[0].Label != "VAG 286 hp RWD" || len(p.Tiers[0].Rules) != 4 || p.DefaultTier != 3 ||
		!slices.Equal(p.QueueDefaultTiers, []int{1, 2}) {
		t.Fatalf("tiers: %+v", p.Tiers)
	}
	if !slices.Contains(p.HardFilters, "km ≤ 80 000") || !slices.Contains(p.HardFilters, "declared damage: not flagged damaged") ||
		!slices.Contains(p.OptionKeys, "pano") || !slices.Equal(p.MustHave, []string{"electric_seats", "power_tailgate"}) ||
		!slices.Contains(p.Families, "VW ID.4") || p.Currency != "EUR" || p.Weights["risk"] != 1 {
		t.Fatalf("profile: %+v", p)
	}
	for _, secretish := range []string{"token", "url", "data_dir", "127.0.0.1"} {
		if strings.Contains(body, secretish) {
			t.Errorf("profile JSON exposes %q", secretish)
		}
	}
	// Neutral server: one tier, no home, still a valid profile.
	n := newServerWith(t, "")
	n.call("GET", "/api/v1/profile", nil, 200, &p)
	if len(p.Tiers) != 1 || p.Tiers[0].Label != "everything else" || p.Owner.Home.Country != "" || p.MustHave == nil {
		t.Fatalf("neutral: %+v", p)
	}
	n.call("GET", "/api/v1/queue?spec=confirmed", nil, 400, nil) // no must_have
	n.call("GET", "/api/v1/queue?tier=2", nil, 400, nil)
}

// Two buyers, same cars: the queue (tiers, filters, scores, market) follows the profile.
func TestTwoProfilesReorderQueue(t *testing.T) {
	c := newServer(t)
	id4 := c.qcar("id4", nil) // T1 for the EV buyer
	ev6pt := c.qcar("ev6-pt", map[string]any{"make": "Kia", "model": "EV6", "power_kw": 168})
	ev6fr := c.qcar("ev6-fr", map[string]any{"make": "Kia", "model": "EV6", "power_kw": 168, "country": "FR", "city": "Lyon", "distance_km": 20})
	gtx := c.qcar("gtx", map[string]any{"model": "ID.4 GTX", "power_kw": 250, "drive": "awd"})
	old := c.qcar("old", map[string]any{"make": "Kia", "model": "EV6", "power_kw": 168, "reg_date": "2020-05"})

	evOrder := queueIDs(c.queue("tier=1,2,3"))
	if !slices.Equal(evOrder, []int64{id4, ev6pt, ev6fr, gtx}) {
		t.Fatalf("EV buyer order %v", evOrder)
	}

	// A buyer in France who wants an EV6 first, VW second, a heat pump, and takes older cars.
	fr, err := profile.Load(writeProfile(t, `
owner: {name: owner, home: {city: Lyon, country: FR, lat: 45.76, lon: 4.84}}
search:
  year_min: 2020
  models:
    - {make: Kia, model: EV6, tier: 1, base_fit: 0.8}
    - {make: VW, model: ID.4, tier: 2, base_fit: 0.6}
  options_wanted: {heat_pump: 5}
`))
	if err != nil {
		t.Fatal(err)
	}
	if err := c.st.SetProfile(fr); err != nil {
		t.Fatal(err)
	}
	q := c.queue("tier=1,2,3")
	frOrder := queueIDs(q)
	if !slices.Equal(frOrder[:3], []int64{ev6fr, ev6pt, old}[:3]) || len(frOrder) != 5 {
		t.Fatalf("FR buyer order %v", frOrder)
	}
	if it := queueItem(t, q, ev6fr); it.Tier != 1 || deref(it.Car.Market) != "home" || *it.Landed != 35000+50+65 {
		t.Fatalf("FR EV6 for the FR buyer: tier %d market %v landed %v", it.Tier, deref(it.Car.Market), *it.Landed)
	}
	if it := queueItem(t, q, id4); it.Tier != 2 || deref(it.Car.Market) != "abroad" {
		t.Fatalf("PT ID.4 for the FR buyer: tier %d market %v", it.Tier, deref(it.Car.Market))
	}
	if q.Counts["1"] != 3 || q.Counts["2"] != 2 || q.Counts["3"] != 0 {
		t.Fatalf("counts %v", q.Counts)
	}
	// Same data, back to the EV buyer.
	ev, _ := profile.Load("../profile/testdata/ev.yaml")
	if err := c.st.SetProfile(ev); err != nil {
		t.Fatal(err)
	}
	if got := queueIDs(c.queue("tier=1,2,3")); !slices.Equal(got, evOrder) {
		t.Fatalf("back to EV: %v", got)
	}
}

func TestDistanceEstimateAndMarket(t *testing.T) {
	c := newServer(t)
	near := c.qcar("near", map[string]any{"country": "ES", "city": "Badajoz", "lat": 38.88, "lon": -6.97}) // ~246 km road estimate
	stored := c.qcar("stored", map[string]any{"distance_km": 90, "lat": 38.72, "lon": -9.14})
	far := c.qcar("far", map[string]any{"country": "DE", "city": "Berlin", "lat": 52.52, "lon": 13.40})
	none := c.qcar("none", nil)

	cs := map[int64]api.CarSummary{}
	for _, s := range c.list("limit=100").Cars {
		cs[s.ID] = s
	}
	if s := cs[near]; s.DistanceKm == nil || *s.DistanceKm < 235 || *s.DistanceKm > 255 || deref(s.DistanceSource) != "estimate" || deref(s.Market) != "abroad" {
		t.Fatalf("near: %v %v %v", s.DistanceKm, deref(s.DistanceSource), deref(s.Market))
	}
	if s := cs[stored]; *s.DistanceKm != 90 || deref(s.DistanceSource) != "stored" || deref(s.Market) != "home" {
		t.Fatalf("stored: %v %v", *s.DistanceKm, deref(s.DistanceSource))
	}
	if s := cs[none]; s.DistanceKm != nil || s.DistanceSource != nil {
		t.Fatalf("none: %v", s.DistanceKm)
	}
	sameIDs(t, "distance_km_max=300", ids(c.list("distance_km_max=300")), near, stored)
	if got := ids(c.list("sort=distance_km")); !slices.Equal(got[:3], []int64{stored, near, far}) || got[3] != none {
		t.Fatalf("sort distance %v", got)
	}
	sameIDs(t, "market=abroad", ids(c.list("market=abroad")), near, far)
	sameIDs(t, "market=home", ids(c.list("market=home")), stored, none)
	d := c.car(near)
	if *d.Lat != 38.88 || *d.Lon != -6.97 || deref(d.DistanceSource) != "estimate" {
		t.Fatalf("detail: %+v", d.CarSpecs)
	}
	// The queue's landed cost uses the estimate (no distance-unknown risk).
	if it := queueItem(t, c.queue("tier=1,2,3"), near); slices.ContainsFunc(it.RiskReasons, func(s string) bool { return strings.HasPrefix(s, "distance unknown") }) {
		t.Fatalf("estimated distance counted as unknown: %q", it.RiskReasons)
	}
	// lat/lon validation.
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", none), map[string]any{"lat": 91}, 422, nil)
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", none), map[string]any{"lat": 40.0, "lon": -3.7}, 200, nil)
	if s := c.car(none); s.DistanceKm == nil || deref(s.DistanceSource) != "estimate" {
		t.Fatalf("patched location: %+v", s.CarSpecs)
	}
}

func TestQueueUserAndSortScore(t *testing.T) {
	c := newServer(t)
	a := c.qcar("a", nil)
	b := c.qcar("b", map[string]any{"seller": map[string]any{"type": "reseller", "name": "SYNTH Trade"}})
	n := c.qcar("n", map[string]any{"price": nil})
	c.queue("user=owner")
	c.queue("user=OWNER")
	c.call("GET", "/api/v1/queue?user=nobody", nil, 400, nil)
	if got := ids(c.list("sort=score")); !slices.Equal(got, []int64{a, b, n}) {
		t.Fatalf("sort=score (desc, missing last): %v", got)
	}
	if got := ids(c.list("sort=score&order=asc")); !slices.Equal(got, []int64{b, a, n}) {
		t.Fatalf("sort=score asc: %v", got)
	}
}
