package profile

import (
	"slices"
	"strings"
	"testing"
)

func TestLoadEV(t *testing.T) {
	p, err := Load("testdata/ev.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Warnings) != 0 {
		t.Fatalf("warnings: %v", p.Warnings)
	}
	s := p.Search
	if s.DefaultTier != 3 || !slices.Equal(s.QueueDefaultTiers, []int{1, 2}) || len(s.Models) != 15 {
		t.Fatalf("tiers: %d %v %d", s.DefaultTier, s.QueueDefaultTiers, len(s.Models))
	}
	// YAML merge key: ID.5 inherits the ID.4 rule, overrides model and base_fit.
	if m := s.Models[1]; m.Model != "ID.5" || *m.BaseFit != 0.78 || m.When == nil || m.When.YearMin != 2023 || m.Tier != 1 {
		t.Fatalf("ID.5: %+v", m)
	}
	if !slices.Equal(s.Powertrain, []string{"bev"}) || *s.Ranking.VATReserve.Pct != 23 || s.Ranking.LandedCost.DefaultDistanceKm["DE"] != 2600 {
		t.Fatalf("defaults: %v %v", s.Powertrain, *s.Ranking.VATReserve.Pct)
	}
	// Untouched ranking keys keep the defaults; km_ref follows km_max.
	if s.Ranking.Peers.YearEUR != 2000 || s.Ranking.Risk.NoVIN != 0.8 || s.Ranking.Fit.KmRef != 50000 || p.Owner.Home.Lat == nil {
		t.Fatalf("ranking defaults: %+v", s.Ranking)
	}
	lines := p.HardFilterLines()
	for _, want := range []string{"year ≥ 2023", "price ≤ 42 000 EUR", "not in PT-20 (Azores), PT-30 (Madeira), ES-CN (Canary Islands)",
		"PL/Baltic history: fact origin/import/history_report/other names none of PL LT LV EE", "lease transfer: not flagged lease_transfer"} {
		if !slices.Contains(lines, want) {
			t.Errorf("hard filter lines lack %q: %q", want, lines)
		}
	}
	if got := p.TierLines(1)[0]; got != "VW ID.4 · 280–290 hp (unknown: pro) · drive fwd/rwd · year ≥ 2023 · not gtx, pure, pro performance, pro power" {
		t.Errorf("tier line: %q", got)
	}
	if p.TierLabel(1) != "VAG 286 hp RWD" || p.TierLabel(3) != "everything else" {
		t.Errorf("labels: %q %q", p.TierLabel(1), p.TierLabel(3))
	}
	v := p.View([]string{"VW ID.4"})
	if len(v.Tiers) != 3 || v.Users[0].Role != "owner" || v.Currency != "EUR" || len(v.MustHave) != 2 || v.Families[0] != "VW ID.4" {
		t.Fatalf("view: %+v", v)
	}
}

func TestDefaultProfile(t *testing.T) {
	p := Default()
	if p.Search.DefaultTier != 1 || !slices.Equal(p.Tiers(), []int{1}) || p.Search.Ranking.VATReserve.On() || p.Owner.Name != "owner" {
		t.Fatalf("default: %+v", p.Search)
	}
	if err := p.Validate(); err != nil {
		t.Fatal(err)
	}
	empty, err := Parse(nil)
	if err != nil || empty.Search.DefaultTier != 1 {
		t.Fatalf("empty file: %v", err)
	}
}

func TestWarnings(t *testing.T) {
	p, err := Parse([]byte(`
owner: {name: ana, home: {country: es}, shoe_size: 38}
search:
  options_wanted: {pano: 2, jetpack: 1}
  must_have: [heated_seats, laser]
  option_keys: [laser]
  hard_filters: [{flag: lease_transfer, exclude: true}]
  sites: [example]
notify: {backend: none}
`))
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(p.Warnings, "\n")
	for _, want := range []string{"field shoe_size not found", "field exclude not found", "field sites not found", "search.options_wanted.jetpack: unknown option key"} {
		if !strings.Contains(joined, want) {
			t.Errorf("warnings lack %q:\n%s", want, joined)
		}
	}
	if strings.Contains(joined, "laser") || strings.Contains(joined, "notify") {
		t.Errorf("unexpected warning:\n%s", joined)
	}
	if p.Owner.Home.Country != "ES" || *p.Search.Ranking.VATReserve.Pct != 21 {
		t.Errorf("home ES: %q VAT %v", p.Owner.Home.Country, *p.Search.Ranking.VATReserve.Pct)
	}
}

func TestValidationErrors(t *testing.T) {
	for yaml, want := range map[string]string{
		"search: {models: [{make: VW, model: ID.4, tier: 0}]}":                  "search.models[0].tier: must be ≥ 1",
		"search: {default_tier: 2, models: [{make: VW, model: ID.4, tier: 3}]}": "search.models[0].tier: 3 > default_tier 2",
		"search: {models: [{model: ID.4, tier: 1}]}":                            "search.models[0].make: required",
		"search: {models: [{make: VW, tier: 1, when: {power_hp: [300, 200]}}]}": "search.models[0].when.power_hp: min 300 > max 200",
		"search: {models: [{make: VW, tier: 1, when: {power_hp: [300]}}]}":      "search.models[0].when.power_hp: want [min, max]",
		"search: {models: [{make: VW, tier: 1, when: {drive: [4x4]}}]}":         `search.models[0].when.drive: want fwd|rwd|awd, got "4x4"`,
		"search: {queue_default_tiers: [2]}":                                    "search.queue_default_tiers[0]: tier 2 outside 1…1",
		"search: {exclude_regions: [PT-99]}":                                    `search.exclude_regions[0]: unknown region "PT-99"`,
		"search: {countries: [Portugal]}":                                       "search.countries[0]: want an ISO-2 country code",
		"search: {powertrain: [steam]}":                                         `search.powertrain[0]: unknown fuel "steam"`,
		"search: {hard_filters: [{field: colour, min: 1}]}":                     `search.hard_filters[0].field: unknown field "colour"`,
		"search: {hard_filters: [{field: km}]}":                                 "search.hard_filters[0]: field needs min and/or max",
		"search: {hard_filters: [{fact: origin, flag: x}]}":                     "search.hard_filters[0]: set exactly one of field, fact/facts, flag",
		"search: {hard_filters: [{fact: origin, mentions_country: [XX]}]}":      `search.hard_filters[0].mentions_country: no country names for "XX"`,
		"search: {hard_filters: [{fact: origin, words: [a], min: 1}]}":          "search.hard_filters[0]: use one of min/max, words, mentions_country",
		"search: {weights: {speed: 1}}":                                         "search.weights.speed: unknown weight",
		"search: {price: {max_eur: 10, min_eur: 20}}":                           "search.price: want 0 ≤ min_eur ≤ max_eur",
		"search: {families: [{make: VW, name: ID.9}]}":                          "search.families[0]: make, name and match are required",
		"search: {penalties: [{field: wheels_in, weight: 1}]}":                  "search.penalties[0]: needs min or max",
		"search: {ranking: {peers: {min_n: [8, 6]}}}":                           "search.ranking.peers.min_n: want 4 values",
		"search: {ranking: {landed_cost: {home_trip: [[100]]}}}":                "search.ranking.landed_cost.home_trip[0]: want [max_km, cost]",
		"search: {ranking: {vat_reserve: {pct: 80}}}":                           "search.ranking.vat_reserve.pct: want 0…50",
		"owner: {home: {country: PT, lat: 41}}":                                 "owner.home: set both lat and lon or neither",
		"search: {year_min: twenty}":                                            "cannot unmarshal",
		"cardb: {users: [{name: owner}]}":                                       `cardb.users: duplicate name "owner"`,
	} {
		_, err := Parse([]byte(yaml))
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s:\n got %v\nwant …%s…", yaml, err, want)
		}
	}
}

func TestStep(t *testing.T) {
	steps := [][]float64{{100, 50}, {500, 100}, {0, 200}}
	for km, want := range map[float64]float64{0: 50, 100: 50, 101: 100, 500: 100, 501: 200, 9999: 200} {
		if got := Step(steps, km); got != want {
			t.Errorf("Step(%v) = %v, want %v", km, got, want)
		}
	}
}
