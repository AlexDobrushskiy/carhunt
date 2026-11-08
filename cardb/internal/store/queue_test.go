package store

import (
	"fmt"
	"slices"
	"strings"
	"testing"
	"time"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
)

var rankNow = time.Date(2026, 11, 8, 12, 0, 0, 0, time.UTC)

// evRanker: the EV worked-example profile (internal/profile/testdata/ev.yaml).
func evRanker(t *testing.T) *ranker {
	t.Helper()
	p, err := profile.Load("../profile/testdata/ev.yaml")
	if err != nil {
		t.Fatal(err)
	}
	return newRanker(p)
}

func ip(n int) *int           { return &n }
func sp(s string) *string     { return &s }
func fp64(f float64) *float64 { return &f }

// cb describes a test car; zero values = unknown.
type cb struct {
	id                   int64
	make, model, variant string
	year, km, price      int
	reg                  string // reg_date; default "<year>-03"
	country, city        string
	kw, battery          float64
	drive, seller        string
	dist                 int
	status               string
	dead                 bool // no live listing
	opts                 map[string]string
	facts                map[string]string
	vin                  bool
	flags                []string
}

func (r *ranker) car(c cb) *rankCar {
	s := &api.CarSummary{ID: c.id, Make: sp(c.make), Model: sp(c.model), Variant: sp(c.variant), Status: "new", LiveListingCount: 1,
		SellerType: "dealer", Options: map[string]string{}}
	if fam, _, ok := r.fam.Family(c.make, c.model, c.variant); ok {
		s.ModelFamily = &fam
	}
	if c.year != 0 {
		s.Year = ip(c.year)
		reg := c.reg
		if reg == "" {
			reg = fmt.Sprintf("%d-03", c.year)
		}
		s.RegDate = &reg
	}
	if c.km != 0 {
		s.Km = ip(c.km)
	}
	if c.price != 0 {
		s.Price = ip(c.price)
	}
	if c.country != "" {
		s.Country = sp(c.country)
	}
	if c.city != "" {
		s.City = sp(c.city)
	}
	if c.kw != 0 {
		s.PowerKw = fp64(c.kw)
	}
	if c.battery != 0 {
		s.Powertrain = &api.Powertrain{BatteryNetKwh: fp64(c.battery)}
	}
	if c.drive != "" {
		s.Drive = sp(c.drive)
	}
	if c.seller != "" {
		s.SellerType = c.seller
	}
	if c.dist != 0 {
		s.DistanceKm = ip(c.dist)
	}
	if c.status != "" {
		s.Status = c.status
	}
	if c.dead {
		s.LiveListingCount = 0
	}
	if c.opts != nil {
		s.Options = c.opts
	}
	s.Market = MarketOf(s.Country, r.p.Owner.Home.Country)
	rc := &rankCar{c: s, facts: c.facts, hasVIN: c.vin, redFlags: c.flags}
	if rc.facts == nil {
		rc.facts = map[string]string{}
	}
	r.prepare([]*rankCar{rc}, rankNow)
	return rc
}

func TestTextHorsepower(t *testing.T) {
	for s, want := range map[string]int{
		"ID.4 286ch Pro 77 kWh Life Max": 286, "Pro 77 kWh 128kW (174 CV)": 174, "Limited Edition 58 kWh accu 190 PK": 190,
		"SKODA Enyaq 85 210 kW CV 82 kWh 77 kwh": 286, "Coupé 85 286PS Navi": 286, "77kWh 210kW (286CV) Endurance": 286,
		"Pro Business (1) 77 kWh accu, 210 kW / 286 pk": 286, "229hp": 229,
	} {
		if got := textHorsepower(s); got == nil || *got != want {
			t.Errorf("%q: got %v, want %d", s, got, want)
		}
	}
	for _, s := range []string{"77 kWh", "Pro Performance", "82KWh", "20\" wheels", "1500 kw", ""} {
		if got := textHorsepower(s); got != nil {
			t.Errorf("%q: got %d, want none", s, *got)
		}
	}
}

// The EV run's tier rules, now expressed as search.models data in the EV profile.
func TestEVTiers(t *testing.T) {
	r := evRanker(t)
	type tc struct {
		make, model, variant string
		year                 int
		kw                   float64
		drive                string
		battery              float64
	}
	cases := []struct {
		name string
		car  tc
		want int
	}{
		{"ID.4 Pro 210 rwd", tc{"VW", "ID.4 Pro", "Life Max", 2024, 210, "rwd", 77}, 1},
		{"ID.5 Pro power unknown", tc{"Volkswagen", "ID.5 Pro", "", 2024, 0, "", 0}, 1},
		{"ID.4 no marker but 210 kW", tc{"VW", "ID.4", "Style", 2025, 210, "rwd", 0}, 1},
		{"ID.5 power_kw wrong, text 286", tc{"VW", "ID.5 Pro", "Pro Business (1) 77 kWh accu, 210 kW / 286 pk", 2024, 77, "rwd", 0}, 1},
		{"ID.4 Pro year unknown", tc{"VW", "ID.4 Pro", "", 0, 210, "rwd", 0}, 1},
		{"ID.4 GTX awd", tc{"VW", "ID.4 GTX", "", 2024, 250, "awd", 0}, 3},
		{"ID.4 GTX no data", tc{"VW", "ID.4 GTX", "", 2024, 0, "", 0}, 3},
		{"ID.4 Pure", tc{"VW", "ID.4 Pure", "", 2024, 0, "", 0}, 3},
		{"ID.4 Pro 2022", tc{"VW", "ID.4 Pro", "", 2022, 210, "rwd", 0}, 3},
		{"ID.4 Pro 128 kW", tc{"VW", "ID.4 Pro", "Life Plus", 2023, 128, "rwd", 0}, 3},
		{"ID.4 Pro Performance power unknown", tc{"VW", "ID.4 Pro Performance", "", 2023, 0, "rwd", 0}, 3},
		{"ID.4 Pro text 150kW", tc{"VW", "ID.4 Pro", "VOLKSWAGEN ID.4 Pro 150kW", 2023, 0, "rwd", 0}, 3},
		{"ID.4 Pro 4MOTION", tc{"VW", "ID.4 Pro 4MOTION", "", 2024, 210, "", 0}, 3},
		{"Q4 45 rwd 2024", tc{"Audi", "Q4 e-tron 45", "S line", 2024, 210, "rwd", 77}, 1},
		{"Q4 Sportback 45 power unknown", tc{"Audi", "Q4 Sportback e-tron", "45 Black Edition", 2025, 0, "", 0}, 1},
		{"Q4 45 quattro awd", tc{"Audi", "Q4 e-tron 45 quattro", "", 2024, 210, "awd", 0}, 3},
		{"Q4 45 quattro drive unknown", tc{"Audi", "Q4 e-tron", "45 quattro Advanced", 2025, 0, "", 0}, 3},
		{"Q4 45 2023", tc{"Audi", "Q4 e-tron 45", "", 2023, 210, "rwd", 0}, 3},
		{"Q4 40", tc{"Audi", "Q4 e-tron 40", "", 2024, 150, "rwd", 0}, 3},
		{"Q4 no marker power unknown", tc{"Audi", "Q4 e-tron", "", 2024, 0, "", 0}, 3},
		{"Enyaq 85 drive unknown", tc{"Skoda", "Enyaq 85", "Loft", 2024, 210, "unknown", 0}, 1},
		{"Enyaq Coupé 85 power unknown", tc{"Škoda", "Enyaq", "Coupé 85 Sportline", 2025, 0, "", 0}, 1},
		{"Enyaq 85x", tc{"Skoda", "Enyaq 85x", "", 2024, 210, "awd", 0}, 3},
		{"Enyaq 85x no data", tc{"Skoda", "Enyaq", "85x Sportline", 2024, 0, "", 0}, 3},
		{"Enyaq RS", tc{"Skoda", "Enyaq RS", "", 2024, 0, "", 0}, 3},
		{"Enyaq 80", tc{"Skoda", "Enyaq 80", "", 2023, 150, "rwd", 0}, 3},
		{"Ioniq 5 77 kWh", tc{"Hyundai", "Ioniq 5", "Star", 2024, 168, "rwd", 77}, 2},
		{"Ioniq 5 84 marker", tc{"Hyundai", "IONIQ 5", "84KWH N Line RWD", 2025, 0, "", 0}, 2},
		{"Ioniq 5 77.4 marker", tc{"Hyundai", "Ioniq 5", "77.4 kWh Vision", 2023, 0, "", 0}, 2},
		{"Ioniq 5 58 kWh", tc{"Hyundai", "Ioniq 5", "58 kWh", 2023, 125, "rwd", 58}, 3},
		{"Ioniq 5 58 marker only", tc{"Hyundai", "Ioniq 5", "58 kWh Style", 2023, 0, "", 0}, 3},
		{"EV6 Air", tc{"Kia", "EV6", "Air 77.4 kWh", 2023, 168, "rwd", 77}, 2},
		{"EV6 GT-Line", tc{"Kia", "EV6", "GT-Line", 2023, 168, "rwd", 77}, 3},
		{"EV6 GTLine", tc{"Kia", "EV6 GTLine", "", 2023, 0, "", 0}, 3},
		{"EV6 GT", tc{"Kia", "EV6 GT", "", 2023, 430, "awd", 0}, 3},
		{"XPeng G6", tc{"XPeng", "G6", "Performance AWD", 2024, 350, "awd", 0}, 2},
		{"Tavascan Endurance", tc{"Cupra", "Tavascan", "Endurance", 2024, 210, "rwd", 77}, 2},
		{"Tavascan Endurance power unknown", tc{"Cupra", "Tavascan", "77kWh Endurance", 2025, 0, "", 0}, 2},
		{"Tavascan VZ AWD", tc{"Cupra", "Tavascan VZ", "", 2024, 250, "awd", 0}, 3},
		{"Tavascan VZ no data", tc{"Cupra", "Tavascan", "VZ", 2024, 0, "", 0}, 3},
		{"Tavascan no data", tc{"Cupra", "Tavascan", "", 2025, 0, "", 0}, 3},
		{"EQA", tc{"Mercedes", "EQA 250", "", 2024, 140, "fwd", 0}, 3},
		{"unmapped", tc{"Foo", "Bar", "", 2024, 210, "rwd", 0}, 3},
	}
	for _, c := range cases {
		rc := r.car(cb{make: c.car.make, model: c.car.model, variant: c.car.variant, year: c.car.year, kw: c.car.kw, drive: c.car.drive, battery: c.car.battery})
		if rc.c.Tier != c.want {
			t.Errorf("%s: tier %d, want %d", c.name, rc.c.Tier, c.want)
		}
	}
	// meta entry: a non-matching ID.4 keeps the family's base_fit and model risk; EQA risk depends on the year rule.
	gtx := r.car(cb{make: "VW", model: "ID.4 GTX", year: 2024})
	if gtx.meta == nil || *gtx.meta.m.BaseFit != 0.80 || gtx.meta.m.Risk != 1.5 {
		t.Fatalf("GTX meta: %+v", gtx.meta)
	}
	if eqa := r.car(cb{make: "Mercedes", model: "EQA", year: 2024}); eqa.meta.m.Risk != 7 {
		t.Fatalf("EQA 2024 risk %v", eqa.meta.m.Risk)
	}
	if eqa := r.car(cb{make: "Mercedes", model: "EQA", year: 2025}); eqa.meta.m.Risk != 2 {
		t.Fatalf("EQA 2025 risk %v", eqa.meta.m.Risk)
	}
}

// Neutral profile: one tier, nothing excluded beyond the fixed rules.
func TestNeutralProfile(t *testing.T) {
	r := newRanker(profile.Default())
	rc := r.car(cb{make: "VW", model: "ID.4 Pro", year: 2015, km: 300000, price: 99000, country: "CH", city: "Funchal"})
	if rc.c.Tier != 1 || r.exclusion(rc, "owner") != "" {
		t.Fatalf("neutral: tier %d, excluded %q", rc.c.Tier, r.exclusion(rc, "owner"))
	}
	if rc.landed == nil || rc.landed.total != 99000 || rc.c.Market != nil {
		t.Fatalf("neutral landed/market: %+v %v", rc.landed, rc.c.Market)
	}
}

func TestScopeExclusion(t *testing.T) {
	r := evRanker(t)
	base := cb{make: "VW", model: "ID.4 Pro", year: 2024, price: 35000, km: 20000, country: "PT", city: "Porto"}
	if got := r.exclusion(r.car(base), "owner"); got != "" {
		t.Fatalf("base excluded: %s", got)
	}
	if got := r.exclusion(r.car(cb{make: "VW", model: "ID.4", status: "talking"}), "owner"); got != "" {
		t.Fatalf("all unknown should pass: %s", got)
	}
	for want, mod := range map[string]func(c *cb){
		"status bought":        func(c *cb) { c.status = "bought" },
		"no live listing":      func(c *cb) { c.dead = true },
		"year < 2021":          func(c *cb) { c.year = 2020 },
		"price > 40000":        func(c *cb) { c.price = 40001 },
		"km > 80000":           func(c *cb) { c.km = 80001 },
		"country CH":           func(c *cb) { c.country = "CH" },
		"region PT-30":         func(c *cb) { c.city = "Funchal (Madeira)" },
		"region ES-CN":         func(c *cb) { c.country, c.city = "ES", "Las Palmas De Gran Canaria" },
		"suspect ad":           func(c *cb) { c.facts = map[string]string{"deal_flag": "Suspect: price too low"} },
		"PL/Baltic history":    func(c *cb) { c.facts = map[string]string{"import": "importado da Polónia"} },
		"lease transfer":       func(c *cb) { c.facts = map[string]string{"lease_transfer": "yes (Leasingübernahme)"} },
		"declared damage":      func(c *cb) { c.facts = map[string]string{"damaged": "front impact"} },
		"region PT-20 (no cc)": func(c *cb) { c.country, c.city = "", "Ponta Delgada" },
		"fuel phev":            func(c *cb) {},
	} {
		c := base
		mod(&c)
		rc := r.car(c)
		if want == "fuel phev" {
			rc.c.Powertrain = &api.Powertrain{Fuel: sp("phev")}
		}
		if got := r.exclusion(rc, "owner"); got != strings.TrimSuffix(want, " (no cc)") {
			t.Errorf("%s: got %q", want, got)
		}
	}
	for name, mod := range map[string]func(c *cb){
		"limits inclusive": func(c *cb) { c.price, c.km = 40000, 80000 },
		"Palmela":          func(c *cb) { c.city = "Palmela" },
		"deal_flag cheap":  func(c *cb) { c.facts = map[string]string{"deal_flag": "cheap"} },
		"history Germany": func(c *cb) {
			c.facts = map[string]string{"origin": "Imported from Germany", "other": "filtro de polen nuevo"}
		},
		"lease transfer no":   func(c *cb) { c.facts = map[string]string{"lease_transfer": "no"} },
		"Las Palmas in PT":    func(c *cb) { c.city = "Las Palmas" }, // region country must match a known car country
		"Polish plates other": func(c *cb) { c.facts = map[string]string{"photos_seen": "Polish plates"} },
	} {
		c := base
		mod(&c)
		if got := r.exclusion(r.car(c), "owner"); got != "" {
			t.Errorf("%s: excluded %q", name, got)
		}
	}
	rc := r.car(base)
	rc.c.Verdict = &api.Verdict{Value: "maybe"}
	if got := r.exclusion(rc, "owner"); got != "rated" {
		t.Fatalf("rated: %q", got)
	}
	// A price flag of the price listing counts as a flag.
	p := mustProfile(t, "search:\n  hard_filters: [{flag: price_lease}]\n")
	r2 := newRanker(p)
	rc = r2.car(base)
	rc.priceFlags = []string{"price_lease"}
	if got := r2.exclusion(rc, "owner"); got != "not flagged price_lease" {
		t.Fatalf("price flag: %q", got)
	}
}

// Field + numeric-fact hard filters: out of range excludes, missing passes.
func TestHardFilterFields(t *testing.T) {
	r := newRanker(mustProfile(t, `
search:
  hard_filters:
    - {field: powertrain.battery_net_kwh, min: 70}
    - {field: wheels_in, max: 19}
    - {fact: battery_soh, min: 90}
`))
	ok := r.car(cb{make: "VW", model: "ID.4", battery: 77})
	if got := r.exclusion(ok, "owner"); got != "" {
		t.Fatalf("77 kWh: %q", got)
	}
	if got := r.exclusion(r.car(cb{make: "VW", model: "ID.4", battery: 52}), "owner"); got != "powertrain.battery_net_kwh ≥ 70" {
		t.Fatalf("52 kWh: %q", got)
	}
	big := r.car(cb{make: "VW", model: "ID.4"})
	big.c.WheelsIn = ip(21)
	if got := r.exclusion(big, "owner"); got != "wheels_in ≤ 19" {
		t.Fatalf("wheels: %q", got)
	}
	soh := r.car(cb{make: "VW", model: "ID.4", facts: map[string]string{"battery_soh": "86 % (dealer test)"}})
	if got := r.exclusion(soh, "owner"); got != "fact battery_soh ≥ 90" {
		t.Fatalf("soh: %q", got)
	}
	soh.facts["battery_soh"] = "unknown"
	if got := r.exclusion(soh, "owner"); got != "" {
		t.Fatalf("soh unparseable passes: %q", got)
	}
}

func TestParseTiers(t *testing.T) {
	all := []int{1, 2, 3}
	got, err := parseTiers([]string{"3,1", "T2", "1"}, []int{1, 2}, all)
	if err != nil || !slices.Equal(got, []int{1, 2, 3}) {
		t.Fatalf("%v %v", got, err)
	}
	if got, _ := parseTiers(nil, []int{1, 2}, all); !slices.Equal(got, []int{1, 2}) {
		t.Fatalf("default: %v", got)
	}
	for _, bad := range []string{"4", "x", "0"} {
		if _, err := parseTiers([]string{bad}, nil, all); err == nil {
			t.Fatalf("%q accepted", bad)
		}
	}
	if got, err := parseTiers([]string{"5"}, nil, []int{1, 2, 3, 4, 5}); err != nil || got[0] != 5 {
		t.Fatalf("tier 5 in a 5-tier profile: %v %v", got, err)
	}
}

func TestSpecMatch(t *testing.T) {
	must := []string{"electric_seats", "power_tailgate"}
	for _, tc := range []struct {
		seats, tailgate    string
		confirmed, unknown bool
	}{
		{"yes", "yes", true, false}, {"yes", "", false, true}, {"", "unknown", false, true}, {"", "", false, true},
		{"no", "yes", false, false}, {"unknown", "no", false, false},
	} {
		o := map[string]string{}
		if tc.seats != "" {
			o["electric_seats"] = tc.seats
		}
		if tc.tailgate != "" {
			o["power_tailgate"] = tc.tailgate
		}
		c := &api.CarSummary{Options: o}
		if !specMatch(c, must, "") || specMatch(c, must, "confirmed") != tc.confirmed || specMatch(c, must, "unknown") != tc.unknown {
			t.Errorf("seats %q tailgate %q", tc.seats, tc.tailgate)
		}
	}
}

func TestLandedCost(t *testing.T) {
	r := evRanker(t)
	cases := []struct {
		name  string
		car   cb
		want  int
		guess bool
		vat   bool
	}{
		// 30000 + home trip 50 (≤ 100 km) + registration 65
		{"home near", cb{country: "PT", dist: 30, km: 20000}, 30115, false, false},
		// + 200 (> 500 km)
		{"home far", cb{country: "PT", dist: 600, km: 20000}, 30265, false, false},
		// unknown distance at home: default PT 250 → 100
		{"home default", cb{country: "PT", km: 20000}, 30165, true, false},
		// unknown country = home market
		{"country unknown", cb{km: 20000}, 30165, true, false},
		// 30000 + travel 100 + fixed 250 + 0.135·950 + 1 night 100 + food 60 + import 250
		{"abroad ES", cb{country: "ES", dist: 950, km: 20000}, 30888, false, false},
		// + 0.135·2600 + 2 nights + VAT 23 % (km ≤ 6000)
		{"abroad DE new", cb{country: "DE", km: 5000}, 38111, true, true},
		// registered within 6 months of 2026-11-08 → VAT reserve
		{"abroad recent reg", cb{country: "FR", dist: 1700, km: 9000, year: 2026, reg: "2026-06"}, 30000 + 100 + 250 + 230 + 200 + 60 + 250 + 6900, false, true},
		{"abroad older reg", cb{country: "FR", dist: 1700, km: 9000, year: 2026, reg: "2026-04"}, 30000 + 100 + 250 + 230 + 200 + 60 + 250, false, false},
		// near abroad: ≤ 700 km, no night
		{"abroad near", cb{country: "ES", dist: 300, km: 20000}, 30000 + 50 + 250 + 41 + 30 + 250, false, false},
	}
	for _, c := range cases {
		c.car.make, c.car.model, c.car.price = "VW", "ID.4", 30000
		l := r.car(c.car).landed
		if l == nil || l.total != c.want || l.distGuess != c.guess || l.vat != c.vat {
			t.Errorf("%s: %+v, want %d guess %v vat %v", c.name, l, c.want, c.guess, c.vat)
		}
	}
	if r.car(cb{make: "VW", model: "ID.4"}).landed != nil {
		t.Fatal("landed without price")
	}
	// Without default_distance_km, an abroad distance comes from the country centroid.
	r2 := newRanker(mustProfile(t, "owner: {home: {country: PT, lat: 38.72, lon: -9.14}}\n"))
	if l := r2.car(cb{make: "VW", model: "ID.4", price: 30000, country: "DE"}).landed; l.distKm < 1800 || l.distKm > 2600 || !l.distGuess {
		t.Fatalf("centroid guess: %+v", l)
	}
}

func TestLocate(t *testing.T) {
	r := evRanker(t)
	s := api.CarSpecs{Country: sp("ES"), Lat: fp64(38.88), Lon: fp64(-6.97)} // ~190 km great-circle × 1.3
	r.locate(&s)
	if s.DistanceKm == nil || *s.DistanceKm < 235 || *s.DistanceKm > 255 || deref(s.DistanceSource) != "estimate" || deref(s.Market) != "abroad" {
		t.Fatalf("estimate: %v %v %v", *s.DistanceKm, deref(s.DistanceSource), deref(s.Market))
	}
	s = api.CarSpecs{Country: sp("PT"), Lat: fp64(42.24), Lon: fp64(-8.72), DistanceKm: ip(150)}
	r.locate(&s)
	if *s.DistanceKm != 150 || deref(s.DistanceSource) != "stored" || deref(s.Market) != "home" {
		t.Fatalf("stored: %v %v %v", *s.DistanceKm, s.DistanceSource, s.Market)
	}
	s = api.CarSpecs{Country: sp("PT")}
	r.locate(&s)
	if s.DistanceKm != nil || s.DistanceSource != nil {
		t.Fatal("no location, no distance")
	}
	n := newRanker(profile.Default())
	s = api.CarSpecs{Country: sp("PT"), Lat: fp64(42.24), Lon: fp64(-8.72)}
	n.locate(&s)
	if s.Market != nil || s.DistanceKm != nil {
		t.Fatal("no home: no market/estimate")
	}
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func TestMedianOfCountryMedians(t *testing.T) {
	got := medianOfCountryMedians(map[string][]float64{"PT": {30000, 31000, 32000}, "ES": {28000}, "DE": {35000, 36000}})
	if got != 31000 {
		t.Fatalf("got %v", got)
	}
	if round50(32115) != 32100 || round50(32125) != 32150 {
		t.Fatal("round50")
	}
	for g, want := range map[float64]float64{0: 50, 10: 70, 20: 90, 40: 90, -15: 20, -30: 20, 6.2: 62.4} {
		if v := valueOfGap(g); v != want {
			t.Errorf("value(%v) = %v, want %v", g, v, want)
		}
	}
}

// peerCars: VW ID.4 Pro 210 kW peers at home, 30 km away.
func peerCars(r *ranker, n int, year, km, price int, idBase int64) []*rankCar {
	var out []*rankCar
	for i := range n {
		out = append(out, r.car(cb{id: idBase + int64(i), make: "VW", model: "ID.4 Pro", kw: 210, drive: "rwd", year: year, km: km, price: price + 100*i, country: "PT", dist: 30}))
	}
	return out
}

func TestPeerLadder(t *testing.T) {
	r := evRanker(t)
	target := r.car(cb{id: 1, make: "VW", model: "ID.4 Pro", kw: 210, drive: "rwd", year: 2024, km: 20000, price: 30000, country: "PT", dist: 30})

	// Step 1: 8 peers with the same trim, year and km band; no adjustment.
	cars := append([]*rankCar{target}, peerCars(r, 8, 2024, 25000, 31000, 100)...)
	ps := r.peersOf(target, r.pool(cars))
	if len(ps.peers) != 8 || ps.adjust || ps.basis != "VW ID.4 · ~275 hp 2wd · 2024 · 15–30k km" {
		t.Fatalf("step 1: n=%d adjust=%v %q", len(ps.peers), ps.adjust, ps.basis)
	}
	// Step 2: 7 of them in the km band + 1 at 40k = same year, 8 ≥ 6.
	cars = append([]*rankCar{target}, peerCars(r, 7, 2024, 25000, 31000, 100)...)
	cars = append(cars, peerCars(r, 1, 2024, 40000, 31000, 200)...)
	if ps = r.peersOf(target, r.pool(cars)); len(ps.peers) != 8 || !ps.adjust || ps.basis != "VW ID.4 · ~275 hp 2wd · 2024" {
		t.Fatalf("step 2: n=%d %q", len(ps.peers), ps.basis)
	}
	// Step 3 with year/km adjustment: three peers of other years.
	cars = []*rankCar{target,
		r.car(cb{id: 11, make: "VW", model: "ID.4 Pro", kw: 210, year: 2023, km: 10000, price: 30000, country: "PT", dist: 30}), // +2000 −600
		r.car(cb{id: 12, make: "VW", model: "ID.4 Pro", kw: 210, year: 2025, km: 30000, price: 34000, country: "PT", dist: 30}), // −2000 +600
		r.car(cb{id: 13, make: "VW", model: "ID.4 Pro", kw: 210, year: 2023, km: 30000, price: 33000, country: "PT", dist: 30}), // +2000 +600
		r.car(cb{id: 14, make: "VW", model: "ID.4 GTX", kw: 250, drive: "awd", year: 2024, km: 20000, price: 20000, country: "PT"}),
	}
	ps = r.peersOf(target, r.pool(cars))
	fp := r.fairOf(target, ps)
	if ps.basis != "VW ID.4 · ~275 hp 2wd" || fp.n != 3 || fp.fair != 32600 || fp.fairLanded != 32700 {
		t.Fatalf("step 3: %q %+v", ps.basis, fp)
	}
	res := r.rank(target, r.pool(cars), rankNow)
	if res.gap == nil || *res.gap != 7.9 || *res.value != 65.8 {
		t.Fatalf("gap/value: %v %v", res.gap, res.value)
	}
	// Step 4: the GTX is another trim, but with the family step it joins (≥ 3 in the family).
	gtx := cars[4]
	if ps := r.peersOf(gtx, r.pool(cars)); ps.basis != "VW ID.4 · all trims" || len(ps.peers) != 4 {
		t.Fatalf("step 4: %q n=%d", ps.basis, len(ps.peers))
	}
	// No peers: value 50, thin-peer risk.
	lone := r.car(cb{id: 50, make: "Kia", model: "EV6", year: 2024, price: 30000, country: "PT"})
	res = r.rank(lone, r.pool([]*rankCar{lone}), rankNow)
	if res.fair != nil || *res.value != 50 || !slices.ContainsFunc(res.reasons, func(s string) bool { return strings.HasPrefix(s, "thin peers (n=0)") }) {
		t.Fatalf("lone: %+v", res)
	}
}

// Fair = median of per-country medians: three PT asks don't outvote one ES ask.
func TestFairCountryVotes(t *testing.T) {
	r := evRanker(t)
	mk := func(id int64, country string, price, dist int) *rankCar {
		return r.car(cb{id: id, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: price, country: country, dist: dist})
	}
	target := mk(1, "PT", 30000, 30)
	cars := []*rankCar{target, mk(2, "PT", 30000, 30), mk(3, "PT", 31000, 30), mk(4, "PT", 31500, 30), mk(5, "ES", 40000, 950)}
	fp := r.fairOf(target, r.peersOf(target, r.pool(cars)))
	// PT median 31000, ES 40000 → 35500.
	if fp == nil || fp.fair != 35500 || fp.n != 4 {
		t.Fatalf("fair: %+v", fp)
	}
}

func TestPoolExclusions(t *testing.T) {
	r := evRanker(t)
	cars := peerCars(r, 9, 2024, 20000, 30000, 100)
	cars = append(cars,
		r.car(cb{id: 1, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 15000, country: "PT"}),             // outlier < 0.67×
		r.car(cb{id: 2, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 3000, price: 30000, country: "DE"}),              // VAT reserve
		r.car(cb{id: 3, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 30000, country: "PT", dead: true}), // no live listing
		r.car(cb{id: 4, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 30000, status: "dropped"}),
		r.car(cb{id: 5, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 45000, country: "PT"}), // over the cap: still a peer
		r.car(cb{id: 6, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 30000, country: "CH"}), // out of scope
	)
	forced := r.car(cb{id: 7, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 30000, country: "PT"})
	forced.priceFlags = []string{"price_net"} // forced past price sanity
	cars = append(cars, forced)
	var ids []int64
	for _, rc := range r.pool(cars) {
		ids = append(ids, rc.c.ID)
	}
	for _, id := range []int64{1, 2, 3, 4, 6, 7} {
		if slices.Contains(ids, id) {
			t.Errorf("car %d in the pool", id)
		}
	}
	if !slices.Contains(ids, 5) || len(ids) != 10 {
		t.Errorf("pool %v", ids)
	}
}

func TestFitAndRisk(t *testing.T) {
	r := evRanker(t)
	// Abroad reseller, nearly new, no evidence at all, one red flag.
	bad := r.car(cb{id: 1, make: "VW", model: "ID.4 Pro", kw: 210, year: 2026, km: 5000, price: 30000, country: "DE", seller: "reseller",
		flags: []string{"photos from another car"}})
	res := r.rank(bad, r.pool([]*rankCar{bad}), rankNow)
	// 4 unknown options 3.2 + VIN .8 + service .8 + owners .5 + accidents .8 + battery 1 + distance .5 + reseller 4 + VAT 4
	// + thin 3 + model 1.5 + red flag 3
	if res.risk != 23.1 {
		t.Fatalf("risk %v %v", res.risk, res.reasons)
	}
	want := []string{"reseller +4", "VAT reserve +4", "? e-seats, tailgate, pano, memory +3.2", "thin peers (n=0) +3", "red flag: photos from another car +3"}
	if !slices.Equal(res.reasons, want) {
		t.Fatalf("reasons %q", res.reasons)
	}
	// fit = 0.80 + (reseller −0.12 + age .005·8 + km .03·(1 − 5000/80000))
	if res.fit != round(0.80-0.12+0.04+0.028125, 3) {
		t.Fatalf("fit %v", res.fit)
	}
	if *res.score != round(50*res.fit-res.risk, 2) {
		t.Fatalf("score %v", *res.score)
	}

	// Home private seller with full evidence and options.
	good := r.car(cb{id: 2, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 20000, price: 30000, country: "PT", dist: 50, seller: "private", vin: true,
		opts:  map[string]string{"electric_seats": "yes", "power_tailgate": "yes", "pano": "no", "memory_seats": "yes"},
		facts: map[string]string{"owners": "1", "service_history": "yes, main dealer", "accidents": "none", "battery_soh": "96%"}})
	res = r.rank(good, r.pool([]*rankCar{good}), rankNow)
	if res.risk != 4.5 || !slices.Equal(res.reasons, []string{"thin peers (n=0) +3", "model risk +1.5"}) {
		t.Fatalf("good risk %v %q", res.risk, res.reasons)
	}
	// options (5+5−1.67+1.33)·.03 + private .06 + home .04 + age .005·6 + km .03·.75 + 3 history .045
	wantFit := round(0.80+(9.66*0.03)+0.06+0.04+0.03+0.0225+0.045, 3)
	if res.fit != wantFit {
		t.Fatalf("good fit %v, want %v", res.fit, wantFit)
	}
	if ts, src := r.trimScoreOf(good); ts != 9.7 || src != "options" {
		t.Fatalf("trim score %v %s", ts, src)
	}
	good.facts["trim_score"] = "2,5"
	if ts, src := r.trimScoreOf(good); ts != 2.5 || src != "fact" {
		t.Fatalf("trim fact %v %s", ts, src)
	}
	// weights.fit scales the terms around base_fit; weights.risk scales risk in the score.
	r2 := newRanker(mustProfile(t, `
owner: {home: {country: PT}}
search:
  models: [{make: VW, model: ID.4, tier: 1, base_fit: 0.8}]
  weights: {fit: 0, risk: 2}
`))
	g2 := r2.car(cb{id: 2, make: "VW", model: "ID.4", year: 2024, km: 20000, price: 30000, country: "PT", seller: "private"})
	res = r2.rank(g2, nil, rankNow)
	if res.fit != 0.8 || *res.score != round(50*0.8-2*res.risk, 2) {
		t.Fatalf("weights: fit %v score %v risk %v", res.fit, *res.score, res.risk)
	}
	// No price: no value, no score.
	np := r.car(cb{id: 3, make: "VW", model: "ID.4 Pro", year: 2024})
	if res := r.rank(np, nil, rankNow); res.value != nil || res.score != nil {
		t.Fatal("no price ranked")
	}
}

func TestWhy(t *testing.T) {
	r := evRanker(t)
	c := r.car(cb{id: 1, make: "VW", model: "ID.4 Pro", kw: 210, year: 2024, km: 1, price: 28000, country: "PT",
		opts: map[string]string{"electric_seats": "yes", "pano": "no", "premium_audio": "unknown"}})
	c.c.WheelsIn = ip(21)
	res := &rankResult{gap: fp64(8.4), fair: &fairPrice{basis: "VW ID.4 · ~275 hp 2wd · 2024", n: 40}}
	if got, want := r.why(c, res), `✓ e-seats · ✗ pano · ✗ 21" wheels · −8 % vs ID.4 · ~275 hp 2wd · 2024 (n=40) · ? tailgate`; got != want {
		t.Fatalf("why:\n got %q\nwant %q", got, want)
	}
	bare := r.car(cb{id: 2, make: "VW", model: "ID.4"})
	if got, want := r.why(bare, &rankResult{}), "? e-seats ? tailgate ? power ? year ? km ? price ? country"; got != want {
		t.Fatalf("unknowns: %q", got)
	}
	c.c.GoodDeal, c.c.GoodDealNote = true, sp("T1 cheapest with pano")
	if got := r.why(c, res); got != "T1 cheapest with pano" {
		t.Fatalf("good deal: %q", got)
	}
	c.c.GoodDealNote = sp(strings.Repeat("x", 300))
	if got := []rune(r.why(c, res)); len(got) != maxWhy || got[maxWhy-1] != '…' {
		t.Fatalf("clipped: %d", len(got))
	}
	// option_labels override.
	r2 := newRanker(mustProfile(t, "search:\n  options_wanted: {towbar: 1}\n  option_labels: {towbar: hitch}\n"))
	if got := r2.why(r2.car(cb{make: "VW", model: "ID.4", opts: map[string]string{"towbar": "yes"}}), &rankResult{}); !strings.HasPrefix(got, "✓ hitch") {
		t.Fatalf("label: %q", got)
	}
}
