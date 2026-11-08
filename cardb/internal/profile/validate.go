package profile

import (
	"errors"
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/geo"
)

// NumericFields are the car fields hard_filters[].field and penalties[].field may name. Powertrain fields may be
// written with or without the "powertrain." prefix.
var NumericFields = []string{"year", "km", "price", "power_kw", "power_hp", "wheels_in", "seats", "distance_km",
	"powertrain.battery_net_kwh", "powertrain.battery_gross_kwh", "powertrain.engine_cc", "powertrain.wltp_range_km",
	"powertrain.wltp_consumption", "powertrain.co2_g_km"}

// CanonicalField resolves a field name ("battery_net_kwh" → "powertrain.battery_net_kwh"); ok=false = unknown.
func CanonicalField(name string) (string, bool) {
	n := strings.ToLower(strings.TrimSpace(name))
	for _, f := range NumericFields {
		if n == f || "powertrain."+n == f {
			return f, true
		}
	}
	return "", false
}

// Fuels is the powertrain.fuel vocabulary.
var Fuels = []string{"bev", "phev", "hev", "mhev", "petrol", "diesel", "lpg", "cng", "hydrogen"}

// OptionKeys: built-in option vocabulary + search.option_keys.
func (p *Profile) OptionKeys() []string {
	out := slices.Clone(api.OptionKeys)
	for _, k := range p.Search.OptionKeys {
		if k = strings.TrimSpace(k); k != "" && !slices.Contains(out, k) {
			out = append(out, k)
		}
	}
	return out
}

// Validate rejects a profile cardb cannot apply (key path in each message) and appends warnings for unknown option
// names.
func (p *Profile) Validate() error {
	var errs []string
	bad := func(path, format string, a ...any) { errs = append(errs, path+": "+fmt.Sprintf(format, a...)) }
	warn := func(path, format string, a ...any) {
		p.Warnings = append(p.Warnings, path+": "+fmt.Sprintf(format, a...))
	}
	iso2 := func(path, c string) {
		if len(c) != 2 || strings.ToUpper(c) != c || strings.ContainsFunc(c, func(r rune) bool { return r < 'A' || r > 'Z' }) {
			bad(path, "want an ISO-2 country code, got %q", c)
		}
	}
	rng := func(path string, xs []float64) {
		if len(xs) != 2 {
			bad(path, "want [min, max]")
		} else if xs[0] > xs[1] {
			bad(path, "min %v > max %v", xs[0], xs[1])
		}
	}

	seen := map[string]bool{strings.ToLower(p.Owner.Name): true}
	for _, u := range p.Cardb.Users {
		n := strings.ToLower(strings.TrimSpace(u.Name))
		switch {
		case n == "":
			bad("cardb.users", "empty name")
		case seen[n]:
			bad("cardb.users", "duplicate name %q", u.Name)
		case u.Role != "" && u.Role != "viewer":
			bad("cardb.users["+u.Name+"].role", "want viewer (the owner is owner.name)")
		}
		seen[n] = true
	}

	h := p.Owner.Home
	if h.Country != "" {
		iso2("owner.home.country", h.Country)
	}
	if (h.Lat == nil) != (h.Lon == nil) {
		bad("owner.home", "set both lat and lon or neither")
	}
	if h.Lat != nil && (*h.Lat < -90 || *h.Lat > 90) {
		bad("owner.home.lat", "out of range")
	}
	if h.Lon != nil && (*h.Lon < -180 || *h.Lon > 180) {
		bad("owner.home.lon", "out of range")
	}

	s := &p.Search
	for i, c := range s.Countries {
		iso2(fmt.Sprintf("search.countries[%d]", i), c)
	}
	for i, r := range s.ExcludeRegions {
		if _, ok := geo.Regions[r]; !ok {
			bad(fmt.Sprintf("search.exclude_regions[%d]", i), "unknown region %q (known: %s)", r, strings.Join(geo.RegionCodes(), " "))
		}
	}
	if s.Price.MaxEUR < 0 || s.Price.MinEUR < 0 || (s.Price.MaxEUR > 0 && s.Price.MinEUR > s.Price.MaxEUR) {
		bad("search.price", "want 0 ≤ min_eur ≤ max_eur")
	}
	if s.YearMin < 0 || s.KmMax < 0 {
		bad("search", "year_min and km_max must be ≥ 0")
	}
	for i, f := range s.Powertrain {
		if !slices.Contains(Fuels, f) {
			bad(fmt.Sprintf("search.powertrain[%d]", i), "unknown fuel %q (want %s)", f, strings.Join(Fuels, "|"))
		}
	}

	if s.DefaultTier < 1 {
		bad("search.default_tier", "must be ≥ 1")
	}
	if s.MaxDistanceKm < 0 {
		bad("search.max_distance_km", "must be ≥ 0 (0 = off)")
	}
	for i, m := range s.Models {
		path := fmt.Sprintf("search.models[%d]", i)
		if strings.TrimSpace(m.Make) == "" {
			bad(path+".make", "required")
		}
		if m.Tier < 1 {
			bad(path+".tier", "must be ≥ 1")
		} else if m.Tier > s.DefaultTier {
			bad(path+".tier", "%d > default_tier %d", m.Tier, s.DefaultTier)
		}
		if m.BaseFit != nil && (*m.BaseFit < 0 || *m.BaseFit > 2) {
			bad(path+".base_fit", "want 0…2")
		}
		if w := m.When; w != nil {
			if w.PowerHP != nil {
				rng(path+".when.power_hp", w.PowerHP)
			}
			if w.BatteryNetKwh != nil {
				rng(path+".when.battery_net_kwh", w.BatteryNetKwh)
			}
			for _, d := range w.Drive {
				if !slices.Contains([]string{"fwd", "rwd", "awd"}, d) {
					bad(path+".when.drive", "want fwd|rwd|awd, got %q", d)
				}
			}
			for _, f := range w.Fuel {
				if !slices.Contains(Fuels, f) {
					bad(path+".when.fuel", "unknown fuel %q", f)
				}
			}
			if w.YearMin > 0 && w.YearMax > 0 && w.YearMin > w.YearMax {
				bad(path+".when", "year_min > year_max")
			}
		}
	}
	for i, t := range s.QueueDefaultTiers {
		if t < 1 || t > s.DefaultTier {
			bad(fmt.Sprintf("search.queue_default_tiers[%d]", i), "tier %d outside 1…%d", t, s.DefaultTier)
		}
	}
	for t := range s.TierLabels {
		if t < 1 || t > s.DefaultTier {
			bad("search.tier_labels", "tier %d outside 1…%d", t, s.DefaultTier)
		}
	}

	for i, r := range s.Families {
		path := fmt.Sprintf("search.families[%d]", i)
		if strings.TrimSpace(r.Make) == "" || strings.TrimSpace(r.Name) == "" || len(r.Match) == 0 {
			bad(path, "make, name and match are required")
		}
		if (len(r.Body) > 0) != (r.BodyName != "") {
			bad(path, "body and body_name go together")
		}
	}

	for i, f := range s.HardFilters {
		path := fmt.Sprintf("search.hard_filters[%d]", i)
		kinds := 0
		for _, set := range []bool{f.Field != "", len(f.FactKeys()) > 0, f.Flag != ""} {
			if set {
				kinds++
			}
		}
		if kinds != 1 {
			bad(path, "set exactly one of field, fact/facts, flag")
			continue
		}
		if f.Min != nil && f.Max != nil && *f.Min > *f.Max {
			bad(path, "min > max")
		}
		switch {
		case f.Field != "":
			if _, ok := CanonicalField(f.Field); !ok {
				bad(path+".field", "unknown field %q (want %s)", f.Field, strings.Join(NumericFields, "|"))
			}
			if f.Min == nil && f.Max == nil {
				bad(path, "field needs min and/or max")
			}
			if len(f.Words) > 0 || len(f.MentionsCountry) > 0 {
				bad(path, "words/mentions_country go with fact/facts")
			}
		case f.Flag != "":
			if f.Min != nil || f.Max != nil || len(f.Words) > 0 || len(f.MentionsCountry) > 0 {
				bad(path, "flag takes no min/max/words/mentions_country")
			}
		default:
			n := 0
			for _, set := range []bool{f.Min != nil || f.Max != nil, len(f.Words) > 0, len(f.MentionsCountry) > 0} {
				if set {
					n++
				}
			}
			if n > 1 {
				bad(path, "use one of min/max, words, mentions_country")
			}
			for _, c := range f.MentionsCountry {
				if !slices.Contains(geo.MentionCountries(), c) {
					bad(path+".mentions_country", "no country names for %q (known: %s)", c, strings.Join(geo.MentionCountries(), " "))
				}
			}
		}
	}

	known := p.OptionKeys()
	for _, k := range sortedKeys(s.OptionsWanted) {
		if !slices.Contains(known, k) {
			warn("search.options_wanted."+k, "unknown option key (add it to search.option_keys)")
		}
		if w := s.OptionsWanted[k]; math.IsNaN(w) || math.IsInf(w, 0) {
			bad("search.options_wanted."+k, "not a number")
		}
	}
	for i, k := range s.MustHave {
		if !slices.Contains(known, k) {
			warn(fmt.Sprintf("search.must_have[%d]", i), "unknown option key %q", k)
		}
	}
	for i, pn := range s.Penalties {
		path := fmt.Sprintf("search.penalties[%d]", i)
		if _, ok := CanonicalField(pn.Field); !ok {
			bad(path+".field", "unknown field %q", pn.Field)
		}
		if pn.Min == nil && pn.Max == nil {
			bad(path, "needs min or max")
		}
	}
	for k, w := range s.Weights {
		if !slices.Contains([]string{"value", "fit", "risk"}, k) {
			bad("search.weights."+k, "unknown weight (want value, fit, risk)")
		} else if w < 0 {
			bad("search.weights."+k, "must be ≥ 0")
		}
	}
	if s.RoadFactor < 1 || s.RoadFactor > 3 {
		bad("search.road_factor", "want 1…3")
	}
	p.Search.Ranking.validate(bad)

	if len(errs) > 0 {
		return errors.New("profile: " + strings.Join(errs, "; "))
	}
	return nil
}

func (r *Ranking) validate(bad func(path, format string, a ...any)) {
	const base = "search.ranking."
	pe := r.Peers
	if pe.PowerBandHP <= 0 {
		bad(base+"peers.power_band_hp", "must be > 0")
	}
	if !sort.IntsAreSorted(pe.KmBands) {
		bad(base+"peers.km_bands", "must ascend")
	}
	if len(pe.MinN) != 4 {
		bad(base+"peers.min_n", "want 4 values (trim+year+km, trim+year, trim, family)")
	}
	if pe.OutlierLow <= 0 || pe.OutlierHigh <= pe.OutlierLow {
		bad(base+"peers", "want 0 < outlier_low < outlier_high")
	}
	steps := func(path string, ss [][]float64) {
		for i, s := range ss {
			if len(s) != 2 || s[0] < 0 {
				bad(fmt.Sprintf("%s[%d]", path, i), "want [max_km, cost] with max_km ≥ 0")
			}
		}
	}
	lc := r.LandedCost
	steps(base+"landed_cost.home_trip", lc.HomeTrip)
	steps(base+"landed_cost.abroad_trip.travel", lc.Abroad.Travel)
	steps(base+"landed_cost.abroad_trip.food", lc.Abroad.Food)
	if lc.Abroad.KmPerNight <= 0 {
		bad(base+"landed_cost.abroad_trip.km_per_night", "must be > 0")
	}
	for c, d := range lc.DefaultDistanceKm {
		if d < 0 || (c != "other" && len(c) != 2) {
			bad(base+"landed_cost.default_distance_km."+c, "want ISO-2 (or other) → km ≥ 0")
		}
	}
	if v := r.VATReserve.Pct; v != nil && (*v < 0 || *v > 50) {
		bad(base+"vat_reserve.pct", "want 0…50")
	}
	if r.Risk.ThinPeersN < 0 || r.Risk.UnknownOptionTop < 0 || r.Risk.ReasonsMax < 0 {
		bad(base+"risk", "counts must be ≥ 0")
	}
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
