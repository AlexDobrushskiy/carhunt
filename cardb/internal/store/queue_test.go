package store

import (
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

func TestIsIsland(t *testing.T) {
	for _, city := range []string{"Funchal (Madeira)", "Las Palmas De Gran Canaria", "Ponta Delgada", "Santa Cruz De Tenerife",
		"AÇORES", "Angra do Heroísmo, Azores", "Arrecife, Lanzarote", "Puerto del Rosario (Fuerteventura)", "Islas Canarias", "Canary Islands"} {
		if !isIsland(city) {
			t.Errorf("%q: want island", city)
		}
	}
	for _, city := range []string{"Porto", "Palmela", "Las Rozas de Madrid", "Madrid", "Tenerias", "Porto", "", "Funchalinho"} {
		if isIsland(city) {
			t.Errorf("%q: not an island", city)
		}
	}
}

func TestBalticHistory(t *testing.T) {
	for v, want := range map[string]string{
		"Imported from Poland (ad)":               "Poland",
		"importado da Polónia":                    "Poland",
		"aus Polen importiert":                    "Poland",
		"polnische Erstzulassung":                 "Poland",
		"Polish plates on photo 3":                "Poland",
		"importé de Pologne":                      "Poland",
		"importato dalla Polonia, targa polacca":  "Poland",
		"coche polaco":                            "Poland",
		"zarejestrowany w Polska":                 "Poland",
		"ex Lithuania":                            "Lithuania",
		"importado da Lituânia":                   "Lithuania",
		"aus Litauen":                             "Lithuania",
		"litauische Papiere":                      "Lithuania",
		"Lietuvos registracija":                   "Lithuania",
		"Carfax: registered in Latvija 2023":      "Latvia",
		"aus Lettland":                            "Latvia",
		"importado de Letonia":                    "Latvia",
		"importado da Letónia":                    "Latvia",
		"importée de Lettonie":                    "Latvia",
		"Estonian first registration":             "Estonia",
		"aus Estland":                             "Estonia",
		"importado de Estonia":                    "Estonia",
		"Eesti numbrimärk":                        "Estonia",
		"estnische Zulassung":                     "Estonia",
		"Imported from Germany; earlier in Polen": "Poland",
	} {
		if got := balticHistory(v); got != want {
			t.Errorf("%q: got %q, want %q", v, got, want)
		}
	}
	for _, v := range []string{"speaks DE/RU/EN/PL", "filtro de polen nuevo", "filtro de pólen trocado", "fresh polish, polished paint",
		"Imported from Germany (ad)", "importado", "yes (leboncoin is_import)", "Estoril", "lettering on tailgate", "establishment",
		"Polanco, Santander", "Estrela", "Latvianism"} {
		if got := balticHistory(v); got != "" {
			t.Errorf("%q: got %q, want none", v, got)
		}
	}
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

type tc struct {
	make, model, variant string
	year                 int // 0 = unknown
	kw                   float64
	drive                string
	battery              float64
}

func summary(c tc) *api.CarSummary {
	s := &api.CarSummary{Make: &c.make, Model: &c.model, Variant: &c.variant}
	if fam, _, ok := Family(c.make, c.model, c.variant); ok {
		s.ModelFamily = &fam
	}
	if c.year != 0 {
		s.Year = &c.year
	}
	if c.kw != 0 {
		s.PowerKw = &c.kw
	}
	if c.drive != "" {
		s.Drive = &c.drive
	}
	if c.battery != 0 {
		s.BatteryNetKwh = &c.battery
	}
	return s
}

func TestCarTier(t *testing.T) {
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
		if got := carTier(summary(c.car)); got != c.want {
			t.Errorf("%s: tier %d, want %d", c.name, got, c.want)
		}
	}
}

func TestTrimScore(t *testing.T) {
	c := &api.CarSummary{Options: map[string]string{"electric_seats": "yes", "power_tailgate": "no", "pano": "yes", "memory_seats": "unknown",
		"premium_audio": "yes", "heat_pump": "no", "hud": "yes"}}
	if s, src := trimScore(c, nil); s != 4-3+1.5+1-1 || src != "options" {
		t.Fatalf("options: %v %s", s, src)
	}
	w := 20
	c.WheelsIn = &w
	if s, _ := trimScore(c, nil); s != 2 {
		t.Fatalf("20\" penalty: %v", s)
	}
	for v, want := range map[string]float64{"7.5": 7.5, " 3,5 ": 3.5, "-2": -2} {
		if s, src := trimScore(c, &v); s != want || src != "fact" {
			t.Fatalf("fact %q: %v %s", v, s, src)
		}
	}
	bad := "high"
	if s, src := trimScore(c, &bad); s != 2 || src != "options" {
		t.Fatalf("non-numeric fact falls back: %v %s", s, src)
	}
	if s, src := trimScore(&api.CarSummary{}, nil); s != 0 || src != "options" {
		t.Fatalf("empty: %v %s", s, src)
	}
}

func ip(n int) *int { return &n }

func TestFairIndex(t *testing.T) {
	fam := func(s string) *string { return &s }
	car := func(f string, year, price, live int) *api.CarSummary {
		c := &api.CarSummary{ModelFamily: fam(f), Price: ip(price), LiveListingCount: live}
		if year != 0 {
			c.Year = ip(year)
		}
		return c
	}
	cars := []*api.CarSummary{
		car("VW ID.4", 2024, 30000, 1), car("VW ID.4", 2024, 34000, 2), car("VW ID.4", 2024, 31000, 1), car("VW ID.4", 2024, 1000, 0),
		car("VW ID.4", 2025, 40000, 1), car("Audi Q4", 2024, 40000, 1), car("Audi Q4", 2024, 41000, 1),
		{ModelFamily: fam("VW ID.4"), Year: ip(2024), LiveListingCount: 1}, // no price
	}
	fi := newFairIndex(cars)
	p, n, b := fi.fair(car("VW ID.4", 2024, 0, 1))
	if p == nil || *p != 31000 || n != 3 || *b != "VW ID.4 2024" {
		t.Fatalf("family+year: %v %d %v", p, n, b)
	}
	p, n, b = fi.fair(car("VW ID.4", 2025, 0, 1))
	if p == nil || *p != 32500 || n != 4 || *b != "VW ID.4 all years" {
		t.Fatalf("family fallback (even n): %v %d %v", p, n, b)
	}
	p, n, b = fi.fair(car("VW ID.4", 0, 0, 1))
	if p == nil || *p != 32500 || *b != "VW ID.4 all years" {
		t.Fatalf("year unknown: %v %d %v", p, n, b)
	}
	if p, n, b = fi.fair(car("Audi Q4", 2024, 0, 1)); p != nil || n != 0 || b != nil {
		t.Fatalf("n < 3: %v %d %v", p, n, b)
	}
	if p, _, _ = fi.fair(&api.CarSummary{}); p != nil {
		t.Fatal("unmapped family has a fair price")
	}
	if g := priceGapPct(ip(28000), ip(31000)); g == nil || *g != -9.7 {
		t.Fatalf("gap: %v", g)
	}
	if priceGapPct(nil, ip(31000)) != nil || priceGapPct(ip(1), nil) != nil {
		t.Fatal("gap without price/fair")
	}
}

func TestQueueWhy(t *testing.T) {
	fam, country := "VW ID.4", "PT"
	kw := 210.0
	c := &api.CarSummary{ModelFamily: &fam, Country: &country, PowerKw: &kw, Year: ip(2024), Km: ip(1), Price: ip(28000),
		Options: map[string]string{"electric_seats": "yes", "pano": "no", "premium_audio": "unknown"}, WheelsIn: ip(21)}
	gap, basis := -8.4, "VW ID.4 2024"
	if got, want := queueWhy(c, &gap, 40, &basis), `✓ e-seats · ✗ pano · ✗ 21" wheels · −8 % vs ID.4 2024 (n=40) · ? tailgate`; got != want {
		t.Fatalf("why:\n got %q\nwant %q", got, want)
	}
	g2, b2 := 0.3, "VW ID.4 all years"
	if got, want := queueWhy(&api.CarSummary{ModelFamily: &fam, Options: map[string]string{}}, &g2, 5, &b2),
		"±0 % vs ID.4 all years (n=5) · ? e-seats ? tailgate ? power ? year ? km ? price ? country"; got != want {
		t.Fatalf("unknowns:\n got %q\nwant %q", got, want)
	}
	note := "T1 cheapest with pano"
	c.GoodDeal, c.GoodDealNote = true, &note
	if got := queueWhy(c, &gap, 40, &basis); got != note {
		t.Fatalf("good deal: %q", got)
	}
	c.GoodDealNote = nil
	if got := queueWhy(c, &gap, 40, &basis); got != "good deal" {
		t.Fatalf("good deal without note: %q", got)
	}
	long := strings.Repeat("x", 300)
	c.GoodDealNote = &long
	if got := []rune(queueWhy(c, nil, 0, nil)); len(got) != maxWhy || got[maxWhy-1] != '…' {
		t.Fatalf("clipped: %d", len(got))
	}
}

func TestQueueExclusion(t *testing.T) {
	base := func() *api.CarSummary {
		return &api.CarSummary{Status: "new", LiveListingCount: 1, Year: ip(2024), Price: ip(35000), Km: ip(20000)}
	}
	if r := queueExclusion(base(), nil); r != "" {
		t.Fatalf("base excluded: %s", r)
	}
	if r := queueExclusion(&api.CarSummary{Status: "talking", LiveListingCount: 1}, nil); r != "" {
		t.Fatalf("all unknown should pass: %s", r)
	}
	s := func(v string) *string { return &v }
	for want, mod := range map[string]func(c *api.CarSummary){
		"rated":             func(c *api.CarSummary) { c.Verdict = &api.Verdict{Value: "maybe"} },
		"status bought":     func(c *api.CarSummary) { c.Status = "bought" },
		"no live listing":   func(c *api.CarSummary) { c.LiveListingCount = 0 },
		"year < 2023":       func(c *api.CarSummary) { c.Year = ip(2022) },
		"price > 42000":     func(c *api.CarSummary) { c.Price = ip(42001) },
		"km > 50000":        func(c *api.CarSummary) { c.Km = ip(50001) },
		"country CH":        func(c *api.CarSummary) { c.Country = s("CH") },
		"island":            func(c *api.CarSummary) { c.City = s("Funchal (Madeira)") },
		"deal_flag suspect": func(c *api.CarSummary) {},
	} {
		c := base()
		mod(c)
		qf := &queueFacts{}
		if want == "deal_flag suspect" {
			qf.dealFlag = "Suspect: price too low"
		}
		if got := queueExclusion(c, qf); got != want {
			t.Errorf("%s: got %q", want, got)
		}
	}
	if got := queueExclusion(base(), &queueFacts{history: []string{"Imported from Germany", "importado da Polónia"}}); got != "history Poland" {
		t.Fatalf("history: %q", got)
	}
	c := base()
	c.Price, c.Km, c.Country = ip(42000), ip(50000), s("lu")
	if r := queueExclusion(c, &queueFacts{dealFlag: "ok"}); r != "" {
		t.Fatalf("limits are inclusive: %s", r)
	}
}

func TestParseTiers(t *testing.T) {
	got, err := parseTiers([]string{"3,1", "T2", "1"}, defaultTiers)
	if err != nil || len(got) != 3 || got[0] != 1 || got[2] != 3 {
		t.Fatalf("%v %v", got, err)
	}
	if got, _ := parseTiers(nil, defaultTiers); len(got) != 2 {
		t.Fatalf("default: %v", got)
	}
	for _, bad := range []string{"4", "x", "0"} {
		if _, err := parseTiers([]string{bad}, nil); err == nil {
			t.Fatalf("%q accepted", bad)
		}
	}
}

func TestSpecMatch(t *testing.T) {
	car := func(seats, tailgate string) *api.CarSummary {
		o := map[string]string{}
		if seats != "" {
			o["electric_seats"] = seats
		}
		if tailgate != "" {
			o["power_tailgate"] = tailgate
		}
		return &api.CarSummary{Options: o}
	}
	for _, tc := range []struct {
		seats, tailgate    string
		confirmed, unknown bool
	}{
		{"yes", "yes", true, false},
		{"yes", "", false, true},
		{"", "unknown", false, true},
		{"", "", false, true},
		{"no", "yes", false, false},
		{"unknown", "no", false, false},
	} {
		c := car(tc.seats, tc.tailgate)
		if !specMatch(c, "") || specMatch(c, "confirmed") != tc.confirmed || specMatch(c, "unknown") != tc.unknown {
			t.Errorf("seats %q tailgate %q: confirmed %v unknown %v", tc.seats, tc.tailgate, specMatch(c, "confirmed"), specMatch(c, "unknown"))
		}
	}
}
