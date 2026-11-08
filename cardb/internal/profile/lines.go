package profile

import (
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/geo"
)

// View is GET /profile. families = the effective canonical family names (store builds them).
func (p *Profile) View(families []string) api.Profile {
	h := p.Owner.Home
	out := api.Profile{
		Owner:             api.ProfileOwner{Name: p.Owner.Name, TZ: p.Owner.TZ, Home: api.ProfileHome{City: h.City, Country: h.Country, Lat: h.Lat, Lon: h.Lon}},
		DefaultTier:       p.Search.DefaultTier,
		QueueDefaultTiers: p.Search.QueueDefaultTiers,
		OptionKeys:        p.OptionKeys(),
		OptionsWanted:     p.Search.OptionsWanted,
		MustHave:          p.Search.MustHave,
		HardFilters:       p.HardFilterLines(),
		Countries:         p.Search.Countries,
		Currency:          p.Search.Price.Currency,
		Weights:           p.Search.Weights,
		Families:          families,
		Ranking:           p.Search.Ranking,
		Warnings:          p.Warnings,
	}
	for _, u := range p.Users() {
		out.Users = append(out.Users, api.ProfileUser{Name: u.Name, Role: u.Role})
	}
	for _, t := range p.Tiers() {
		out.Tiers = append(out.Tiers, api.ProfileTier{Tier: t, Label: p.TierLabel(t), Rules: p.TierLines(t)})
	}
	if out.OptionsWanted == nil {
		out.OptionsWanted = map[string]float64{}
	}
	for _, s := range []*[]string{&out.MustHave, &out.Countries, &out.Warnings} {
		if *s == nil {
			*s = []string{}
		}
	}
	return out
}

// TierLabel: search.tier_labels[t], else the model labels/names of that tier, else "everything else" for the default.
func (p *Profile) TierLabel(t int) string {
	if l := p.Search.TierLabels[t]; l != "" {
		return l
	}
	if t == p.Search.DefaultTier {
		return "everything else"
	}
	var names []string
	for _, m := range p.Search.Models {
		if m.Tier == t {
			n := m.Label
			if n == "" {
				n = strings.TrimSpace(m.Make + " " + m.Model)
			}
			if !slices.Contains(names, n) {
				names = append(names, n)
			}
		}
	}
	return strings.Join(names, ", ")
}

// TierLines: one line per search.models rule of tier t, in match order.
func (p *Profile) TierLines(t int) []string {
	out := []string{}
	for _, m := range p.Search.Models {
		if m.Tier == t {
			out = append(out, m.Line())
		}
	}
	if t == p.Search.DefaultTier {
		out = append(out, "no search.models rule matches")
	}
	return out
}

// Line renders a model rule: "VW ID.4 · 280–290 hp (unknown: pro) · drive fwd/rwd · year ≥ 2023 · not gtx, pure".
func (m Model) Line() string {
	parts := []string{strings.TrimSpace(m.Make + " " + m.Model)}
	if m.Model == "" {
		parts[0] += " (any model)"
	}
	w := m.When
	if w == nil {
		return parts[0]
	}
	marker := ""
	if len(w.VariantAny) > 0 {
		marker = " (unknown: " + strings.Join(w.VariantAny, "/") + ")"
	}
	if w.PowerHP != nil {
		parts = append(parts, fmt.Sprintf("%s–%s hp%s", num(w.PowerHP[0]), num(w.PowerHP[1]), marker))
	}
	if w.BatteryNetKwh != nil {
		parts = append(parts, fmt.Sprintf("battery %s–%s kWh%s", num(w.BatteryNetKwh[0]), num(w.BatteryNetKwh[1]), marker))
	}
	if w.PowerHP == nil && w.BatteryNetKwh == nil && len(w.VariantAny) > 0 {
		parts = append(parts, "has "+strings.Join(w.VariantAny, "/"))
	}
	if len(w.Drive) > 0 {
		parts = append(parts, "drive "+strings.Join(w.Drive, "/"))
	}
	if len(w.Fuel) > 0 {
		parts = append(parts, "fuel "+strings.Join(w.Fuel, "/"))
	}
	if w.YearMin > 0 {
		parts = append(parts, fmt.Sprintf("year ≥ %d", w.YearMin))
	}
	if w.YearMax > 0 {
		parts = append(parts, fmt.Sprintf("year ≤ %d", w.YearMax))
	}
	if len(w.VariantNone) > 0 {
		parts = append(parts, "not "+strings.Join(w.VariantNone, ", "))
	}
	return strings.Join(parts, " · ")
}

// HardFilterLines: one human-readable line per queue exclusion, fixed rules first.
func (p *Profile) HardFilterLines() []string {
	s := p.Search
	out := []string{"not rated by the user", "status not closed/dropped/bought", "≥ 1 live listing"}
	if s.YearMin > 0 {
		out = append(out, fmt.Sprintf("year ≥ %d", s.YearMin))
	}
	if s.Price.MaxEUR > 0 {
		out = append(out, fmt.Sprintf("price ≤ %s %s", group(s.Price.MaxEUR), s.Price.Currency))
	}
	if s.KmMax > 0 {
		out = append(out, "km ≤ "+group(s.KmMax))
	}
	if len(s.Countries) > 0 {
		out = append(out, "country in "+strings.Join(s.Countries, " "))
	}
	if len(s.ExcludeRegions) > 0 {
		var rs []string
		for _, r := range s.ExcludeRegions {
			rs = append(rs, r+" ("+geo.Regions[r].Name+")")
		}
		out = append(out, "not in "+strings.Join(rs, ", "))
	}
	if len(s.ExcludePlaces) > 0 {
		out = append(out, "city not "+strings.Join(s.ExcludePlaces, ", "))
	}
	if len(s.Powertrain) > 0 {
		out = append(out, "fuel in "+strings.Join(s.Powertrain, " "))
	}
	for _, f := range s.HardFilters {
		out = append(out, f.Line())
	}
	return out
}

// Line renders a hard filter (its label first when set). A missing value always passes.
func (f HardFilter) Line() string {
	var what string
	rangeText := func(name string) string {
		switch {
		case f.Min != nil && f.Max != nil:
			return fmt.Sprintf("%s in %s…%s", name, num(*f.Min), num(*f.Max))
		case f.Min != nil:
			return fmt.Sprintf("%s ≥ %s", name, num(*f.Min))
		case f.Max != nil:
			return fmt.Sprintf("%s ≤ %s", name, num(*f.Max))
		}
		return name
	}
	switch {
	case f.Field != "":
		what = rangeText(f.Field)
	case f.Flag != "":
		what = "not flagged " + f.Flag
	default:
		facts := "fact " + strings.Join(f.FactKeys(), "/")
		switch {
		case len(f.Words) > 0:
			what = facts + " has none of: " + strings.Join(f.Words, ", ")
		case len(f.MentionsCountry) > 0:
			what = facts + " names none of " + strings.Join(f.MentionsCountry, " ")
		case f.Min != nil || f.Max != nil:
			what = rangeText(facts)
		default:
			what = facts + " not yes"
		}
	}
	if f.Label != "" {
		return f.Label + ": " + what
	}
	return what
}

func num(v float64) string { return strconv.FormatFloat(v, 'f', -1, 64) }

func group(n int) string {
	s := strconv.Itoa(n)
	var parts []string
	for len(s) > 3 {
		parts = append([]string{s[len(s)-3:]}, parts...)
		s = s[:len(s)-3]
	}
	return strings.Join(append([]string{s}, parts...), " ")
}

// TopOptions: options_wanted keys by weight desc (then key).
func (p *Profile) TopOptions() []string {
	keys := sortedKeys(p.Search.OptionsWanted)
	sort.SliceStable(keys, func(i, j int) bool { return p.Search.OptionsWanted[keys[i]] > p.Search.OptionsWanted[keys[j]] })
	return keys
}
