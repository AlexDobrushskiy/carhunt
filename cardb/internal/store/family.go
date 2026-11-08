package store

import (
	_ "embed"
	"slices"
	"sort"
	"strings"
	"unicode"

	"go.yaml.in/yaml/v3"

	"carhunt/cardb/internal/geo"
	"carhunt/cardb/internal/profile"
)

// Model family: a canonical "<Make> <Family>" derived from the messy make/model/variant text at read time. The rule
// table is data: built-in families.yaml merged with the profile's search.families and search.models.

//go:embed families.yaml
var familiesYAML []byte

type familyRule struct {
	make     string     // canonical display make
	name     string     // family without the make
	match    [][]string // normalized token sequences, any one matches (consecutive tokens)
	with     []string   // tokens that must also appear somewhere in model + variant
	lead     bool       // the sequence must start the model (after a leading make)
	bare     bool       // distinctive enough to match when the make is empty or unknown
	body     []string   // a body token in model + variant selects bodyName
	bodyName string
}

type familyInfo struct{ name, make string }

// Families resolves model families for one profile. Read-only after newFamilies.
type Families struct {
	rules []familyRule
	makes map[string]string     // normalized make spelling → canonical make
	known map[string]familyInfo // normalized family name → canonical name + make
	base  map[string]string     // canonical family (incl. body names) → its rule's base family
}

var builtinFamilies = func() struct {
	Makes map[string][]string  `yaml:"makes"`
	Rules []profile.FamilyRule `yaml:"rules"`
} {
	var d struct {
		Makes map[string][]string  `yaml:"makes"`
		Rules []profile.FamilyRule `yaml:"rules"`
	}
	if err := yaml.Unmarshal(familiesYAML, &d); err != nil {
		panic("families.yaml: " + err.Error())
	}
	return d
}()

func compileFamilyRule(r profile.FamilyRule) familyRule {
	out := familyRule{make: strings.TrimSpace(r.Make), name: strings.TrimSpace(r.Name), lead: r.Lead, bare: r.Bare,
		bodyName: strings.TrimSpace(r.BodyName)}
	for _, m := range r.Match {
		if toks := strings.Fields(normFamilyText(m)); len(toks) > 0 {
			out.match = append(out.match, toks)
		}
	}
	for _, w := range r.With {
		out.with = append(out.with, strings.Fields(normFamilyText(w))...)
	}
	for _, b := range r.Body {
		out.body = append(out.body, strings.Fields(normFamilyText(b))...)
	}
	return out
}

// newFamilies merges the built-in table with the profile: search.families override a built-in rule with the same
// make + name in place, or are added ahead of the built-ins of their make; a search.models make/model that resolves
// to no family gets an automatic rule (its model words) at the end.
func newFamilies(p *profile.Profile) *Families {
	f := &Families{makes: map[string]string{}}
	addMake := func(canon string, aliases ...string) {
		for _, a := range append([]string{canon}, aliases...) {
			if n := normFamilyText(a); n != "" {
				if _, ok := f.makes[n]; !ok || a != canon {
					f.makes[n] = canon
				}
			}
		}
	}
	for canon, aliases := range builtinFamilies.Makes {
		addMake(canon, aliases...)
	}
	for _, r := range builtinFamilies.Rules {
		f.rules = append(f.rules, compileFamilyRule(r))
	}
	if p == nil {
		p = profile.Default()
	}
	for _, r := range p.Search.Families {
		mk := f.canonMake(r.Make)
		r.Make = mk
		addMake(mk, r.MakeAliases...)
		nr := compileFamilyRule(r)
		same := func(x familyRule) bool {
			return normFamilyText(x.make) == normFamilyText(mk) && normFamilyText(x.name) == normFamilyText(nr.name)
		}
		if i := slices.IndexFunc(f.rules, same); i >= 0 {
			f.rules[i] = nr
		} else if i := slices.IndexFunc(f.rules, func(x familyRule) bool { return x.make == mk }); i >= 0 {
			f.rules = slices.Insert(f.rules, i, nr)
		} else {
			f.rules = append(f.rules, nr)
		}
	}
	for _, m := range p.Search.Models {
		if strings.TrimSpace(m.Model) == "" {
			addMake(f.canonMake(m.Make))
			continue
		}
		if _, _, ok := f.Family(m.Make, m.Model, ""); ok {
			continue
		}
		mk := f.canonMake(m.Make)
		addMake(mk)
		f.rules = append(f.rules, compileFamilyRule(profile.FamilyRule{Make: mk, Name: strings.TrimSpace(m.Model), Match: []string{m.Model}}))
	}
	f.known, f.base = map[string]familyInfo{}, map[string]string{}
	for _, r := range f.rules {
		base := r.make + " " + r.name
		for _, n := range []string{r.name, r.bodyName} {
			if n != "" {
				full := r.make + " " + n
				f.known[normFamilyText(full)] = familyInfo{full, r.make}
				f.base[full] = base
			}
		}
	}
	return f
}

// canonMake maps a make spelling to its canonical display form (unknown makes keep their trimmed spelling).
func (f *Families) canonMake(raw string) string {
	if mk, ok := f.makes[normFamilyText(raw)]; ok {
		return mk
	}
	return strings.TrimSpace(raw)
}

// normFamilyText lowercases, strips diacritics, drops '.' and '-', turns other non-alphanumerics into spaces.
func normFamilyText(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if f, ok := geo.Diacritics[r]; ok {
			b.WriteString(f)
			continue
		}
		switch {
		case r == '.' || r == '-':
		case unicode.IsLetter(r) || unicode.IsDigit(r):
			b.WriteRune(r)
		default:
			b.WriteByte(' ')
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

// leadingMake returns the canonical make spelled by the first one or two tokens, and how many tokens it used.
func (f *Families) leadingMake(toks []string) (string, int) {
	for n := min(2, len(toks)); n >= 1; n-- {
		if mk, ok := f.makes[strings.Join(toks[:n], " ")]; ok {
			return mk, n
		}
	}
	return "", 0
}

// seqAt reports whether seq occurs in toks (at the start only when lead).
func seqAt(toks, seq []string, lead bool) bool {
	for i := 0; i+len(seq) <= len(toks); i++ {
		if slices.Equal(toks[i:i+len(seq)], seq) {
			return true
		}
		if lead {
			return false
		}
	}
	return false
}

func (r *familyRule) matches(toks, all []string) bool {
	for _, w := range r.with {
		if !slices.Contains(all, w) {
			return false
		}
	}
	for _, m := range r.match {
		if seqAt(toks, m, r.lead) {
			return true
		}
	}
	return false
}

// Family maps raw make/model/variant to a canonical family ("VW ID.4") and its make. ok=false = unmapped.
// Family tokens come from the model (the variant is consulted only when the model alone matches nothing);
// body discriminators (Sportback, Coupé) are read from model + variant.
func (f *Families) Family(carMake, model, variant string) (family, familyMake string, ok bool) {
	mk := f.makes[normFamilyText(carMake)]
	mt := strings.Fields(normFamilyText(model))
	if lm, n := f.leadingMake(mt); n > 0 && (mk == "" || lm == mk) {
		mk, mt = lm, mt[n:]
	}
	all := append(append([]string{}, mt...), strings.Fields(normFamilyText(variant))...)
	find := func(toks []string) *familyRule {
		for i := range f.rules {
			r := &f.rules[i]
			if (mk != "" && r.make != mk) || (mk == "" && !r.bare) {
				continue
			}
			if r.matches(toks, all) {
				return r
			}
		}
		return nil
	}
	r := find(mt)
	if r == nil {
		r = find(all)
	}
	if r == nil {
		return "", "", false
	}
	name := r.name
	for _, b := range r.body {
		if slices.Contains(all, b) {
			name = r.bodyName
			break
		}
	}
	return r.make + " " + name, r.make, true
}

// Base returns the family a body variant belongs to ("Audi Q4 Sportback" → "Audi Q4"); unknown names map to themselves.
func (f *Families) Base(family string) string {
	if b, ok := f.base[family]; ok {
		return b
	}
	return family
}

// Names lists every canonical family, sorted by make then family.
func (f *Families) Names() []string {
	infos := make([]familyInfo, 0, len(f.known))
	for _, fi := range f.known {
		infos = append(infos, fi)
	}
	sortFamilies(infos)
	out := make([]string, len(infos))
	for i, fi := range infos {
		out[i] = fi.name
	}
	return out
}

func sortFamilies(infos []familyInfo) {
	sort.Slice(infos, func(i, j int) bool {
		mi, mj := normFamilyText(infos[i].make), normFamilyText(infos[j].make)
		if mi != mj {
			return mi < mj
		}
		return normFamilyText(infos[i].name) < normFamilyText(infos[j].name)
	})
}

// Canonical resolves a family name ignoring case, diacritics, '.' and '-'.
func (f *Families) Canonical(name string) (family, familyMake string, ok bool) {
	fi, ok := f.known[normFamilyText(name)]
	return fi.name, fi.make, ok
}
