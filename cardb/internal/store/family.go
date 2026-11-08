package store

import (
	"slices"
	"sort"
	"strings"
	"unicode"
)

// Model family: a canonical "<Make> <Family>" derived from the messy make/model/variant text at read time.

type familyRule struct {
	make     string   // canonical display make
	name     string   // family without the make
	match    []string // normalized token sequences, any one matches (consecutive tokens)
	with     []string // tokens that must also appear somewhere in model + variant
	lead     bool     // the sequence must start the model (after a leading make)
	bare     bool     // distinctive enough to match when the make is empty or unknown
	body     []string // a body token in model + variant selects bodyName
	bodyName string
}

// familyRules: specific rules before general ones within a make.
var familyRules = []familyRule{
	{make: "Audi", name: "Q4", match: []string{"q4"}, bare: true, body: []string{"sportback", "spb"}, bodyName: "Q4 Sportback"},
	{make: "Audi", name: "Q6 e-tron", match: []string{"q6", "sq6"}},
	{make: "Audi", name: "Q8 e-tron", match: []string{"q8", "sq8"}, with: []string{"etron"}, bare: true},
	{make: "BMW", name: "iX1", match: []string{"ix1"}, bare: true},
	{make: "BMW", name: "iX2", match: []string{"ix2"}, bare: true},
	{make: "BMW", name: "iX3", match: []string{"ix3"}, bare: true},
	{make: "BMW", name: "iX", match: []string{"ix"}},
	{make: "BMW", name: "i4", match: []string{"i4"}},
	{make: "BYD", name: "Seal U", match: []string{"seal u"}},
	{make: "BYD", name: "Sealion 7", match: []string{"sealion 7", "sealion7"}, bare: true},
	{make: "BYD", name: "Seal", match: []string{"seal"}},
	{make: "BYD", name: "Atto 3", match: []string{"atto 3", "atto3"}, bare: true},
	{make: "Cupra", name: "Tavascan", match: []string{"tavascan"}, bare: true},
	{make: "Cupra", name: "Born", match: []string{"born"}},
	{make: "Ford", name: "Mustang Mach-E", match: []string{"mache", "mach e"}, bare: true},
	{make: "Hyundai", name: "Ioniq 5", match: []string{"ioniq 5", "ioniq5"}, bare: true},
	{make: "Hyundai", name: "Ioniq 6", match: []string{"ioniq 6", "ioniq6"}, bare: true},
	{make: "Hyundai", name: "Kona Electric", match: []string{"kona"}, bare: true},
	{make: "KGM", name: "Torres EVX", match: []string{"torres"}, with: []string{"evx"}, bare: true},
	{make: "Kia", name: "EV3", match: []string{"ev3"}, bare: true},
	{make: "Kia", name: "EV6", match: []string{"ev6"}, bare: true},
	{make: "Kia", name: "EV9", match: []string{"ev9"}, bare: true},
	{make: "Kia", name: "Niro EV", match: []string{"niro", "eniro"}, bare: true},
	{make: "MINI", name: "Countryman", match: []string{"countryman"}, bare: true},
	{make: "Mercedes", name: "EQA", match: []string{"eqa"}, bare: true},
	{make: "Mercedes", name: "EQB", match: []string{"eqb"}, bare: true},
	{make: "Mercedes", name: "EQC", match: []string{"eqc"}, bare: true},
	{make: "Mercedes", name: "EQE SUV", match: []string{"eqe"}, with: []string{"suv"}, bare: true},
	{make: "Nissan", name: "Ariya", match: []string{"ariya"}, bare: true},
	{make: "Peugeot", name: "e-308", match: []string{"e308", "e 308"}, bare: true},
	{make: "Polestar", name: "2", match: []string{"2"}, lead: true},
	{make: "Polestar", name: "4", match: []string{"4"}, lead: true},
	{make: "Renault", name: "Scenic E-Tech", match: []string{"scenic"}},
	{make: "Škoda", name: "Enyaq", match: []string{"enyaq"}, bare: true, body: []string{"coupe"}, bodyName: "Enyaq Coupé"},
	{make: "Škoda", name: "Elroq", match: []string{"elroq"}, bare: true},
	{make: "Smart", name: "#1", match: []string{"1"}, lead: true},
	{make: "Smart", name: "#3", match: []string{"3"}, lead: true},
	{make: "Tesla", name: "Model 3", match: []string{"model 3", "model3"}, bare: true},
	{make: "Tesla", name: "Model Y", match: []string{"model y", "modely"}, bare: true},
	{make: "Toyota", name: "bZ4X", match: []string{"bz4x"}, bare: true},
	{make: "Volvo", name: "EX30", match: []string{"ex30"}, bare: true},
	{make: "Volvo", name: "EX40", match: []string{"ex40"}, bare: true},
	{make: "Volvo", name: "XC40 Recharge", match: []string{"xc40"}, bare: true},
	{make: "VW", name: "ID.3", match: []string{"id3", "id 3"}, bare: true},
	{make: "VW", name: "ID.4", match: []string{"id4", "id 4"}, bare: true},
	{make: "VW", name: "ID.5", match: []string{"id5", "id 5"}, bare: true},
	{make: "VW", name: "ID.7", match: []string{"id7", "id 7"}, bare: true},
	{make: "VW", name: "ID. Buzz", match: []string{"idbuzz", "id buzz"}, bare: true},
	{make: "XPeng", name: "G6", match: []string{"g6"}},
}

// makeAliases maps normalized make spellings to the canonical display make.
var makeAliases = map[string]string{
	"audi": "Audi", "bmw": "BMW", "byd": "BYD", "cupra": "Cupra", "ford": "Ford", "hyundai": "Hyundai",
	"kgm": "KGM", "kg mobility": "KGM", "kgmobility": "KGM", "ssangyong": "KGM", "ssang yong": "KGM",
	"kia": "Kia", "mini": "MINI", "bmw mini": "MINI",
	"mercedes": "Mercedes", "mercedesbenz": "Mercedes", "mercedes benz": "Mercedes", "mb": "Mercedes",
	"nissan": "Nissan", "peugeot": "Peugeot", "polestar": "Polestar", "renault": "Renault", "skoda": "Škoda",
	"smart": "Smart", "tesla": "Tesla", "toyota": "Toyota", "volvo": "Volvo", "vw": "VW", "volkswagen": "VW",
	"xpeng": "XPeng",
}

var foldDiacritics = func() map[rune]string {
	m := map[rune]string{'æ': "ae", 'œ': "oe", 'ß': "ss"}
	for base, rs := range map[string]string{
		"a": "àáâãäåāăą", "c": "çćč", "d": "ďđ", "e": "èéêëēėęě", "g": "ğ", "i": "ìíîïīįı", "l": "łľĺ",
		"n": "ñńň", "o": "òóôõöøōő", "r": "ŕř", "s": "śšşș", "t": "ťţț", "u": "ùúûüūůűų", "y": "ýÿ", "z": "źżž",
	} {
		for _, r := range rs {
			m[r] = base
		}
	}
	return m
}()

// normFamilyText lowercases, strips diacritics, drops '.' and '-', turns other non-alphanumerics into spaces.
func normFamilyText(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if f, ok := foldDiacritics[r]; ok {
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
func leadingMake(toks []string) (string, int) {
	for n := min(2, len(toks)); n >= 1; n-- {
		if mk, ok := makeAliases[strings.Join(toks[:n], " ")]; ok {
			return mk, n
		}
	}
	return "", 0
}

// seqAt reports whether seq occurs in toks (at the start only when lead).
func seqAt(toks, seq []string, lead bool) bool {
	for i := 0; i+len(seq) <= len(toks); i++ {
		match := true
		for j := range seq {
			if toks[i+j] != seq[j] {
				match = false
				break
			}
		}
		if match {
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
		if seqAt(toks, strings.Fields(m), r.lead) {
			return true
		}
	}
	return false
}

// Family maps raw make/model/variant to a canonical family ("VW ID.4") and its make. ok=false = unmapped.
// Family tokens come from the model (the variant is consulted only when the model alone matches nothing);
// body discriminators (Sportback, Coupé) are read from model + variant.
func Family(carMake, model, variant string) (family, familyMake string, ok bool) {
	mk := makeAliases[normFamilyText(carMake)]
	mt := strings.Fields(normFamilyText(model))
	if lm, n := leadingMake(mt); n > 0 && (mk == "" || lm == mk) {
		mk, mt = lm, mt[n:]
	}
	all := append(append([]string{}, mt...), strings.Fields(normFamilyText(variant))...)
	find := func(toks []string) *familyRule {
		for i := range familyRules {
			r := &familyRules[i]
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

type familyInfo struct{ name, make string }

// knownFamilies: normalized name → canonical name + make.
var knownFamilies = func() map[string]familyInfo {
	m := map[string]familyInfo{}
	for _, r := range familyRules {
		for _, n := range []string{r.name, r.bodyName} {
			if n != "" {
				full := r.make + " " + n
				m[normFamilyText(full)] = familyInfo{full, r.make}
			}
		}
	}
	return m
}()

// FamilyNames lists every canonical family, sorted by make then family.
func FamilyNames() []string {
	infos := make([]familyInfo, 0, len(knownFamilies))
	for _, fi := range knownFamilies {
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

// CanonicalFamily resolves a family name ignoring case, diacritics, '.' and '-'.
func CanonicalFamily(name string) (family, familyMake string, ok bool) {
	fi, ok := knownFamilies[normFamilyText(name)]
	return fi.name, fi.make, ok
}
