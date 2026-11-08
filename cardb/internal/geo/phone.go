package geo

import "strings"

// Dialing is a country's telephone numbering plan: calling code, national significant number length and the trunk
// prefix(es) dialled before national numbers (dropped in international form).
type Dialing struct {
	Code     string
	Min, Max int // national significant number length
	Trunk    []string
}

func (d Dialing) fits(n int) bool { return n >= d.Min && n <= d.Max }

// Dialings: EU + EEA + CH + UK, keyed by ISO-2.
var Dialings = map[string]Dialing{
	"AT": {"43", 4, 13, []string{"0"}}, "BE": {"32", 8, 9, []string{"0"}}, "BG": {"359", 8, 9, []string{"0"}},
	"HR": {"385", 8, 9, []string{"0"}}, "CY": {"357", 8, 8, nil}, "CZ": {"420", 9, 9, nil}, "DK": {"45", 8, 8, nil},
	"EE": {"372", 7, 8, nil}, "FI": {"358", 5, 12, []string{"0"}}, "FR": {"33", 9, 9, []string{"0"}},
	"DE": {"49", 6, 11, []string{"0"}}, "GR": {"30", 10, 10, nil}, "HU": {"36", 8, 9, []string{"06"}},
	"IE": {"353", 7, 9, []string{"0"}}, "IT": {"39", 6, 11, nil}, "LV": {"371", 8, 8, nil},
	"LT": {"370", 8, 8, []string{"8", "0"}}, "LU": {"352", 4, 11, nil}, "MT": {"356", 8, 8, nil},
	"NL": {"31", 9, 9, []string{"0"}}, "PL": {"48", 9, 9, nil}, "PT": {"351", 9, 9, nil}, "RO": {"40", 9, 9, []string{"0"}},
	"SK": {"421", 9, 9, []string{"0"}}, "SI": {"386", 8, 8, []string{"0"}}, "ES": {"34", 9, 9, nil},
	"SE": {"46", 7, 9, []string{"0"}}, "CH": {"41", 9, 9, []string{"0"}}, "NO": {"47", 8, 8, nil},
	"IS": {"354", 7, 7, nil}, "LI": {"423", 7, 7, nil}, "GB": {"44", 10, 10, []string{"0"}},
}

var byCode = func() map[string]Dialing {
	m := map[string]Dialing{}
	for _, d := range Dialings {
		m[d.Code] = d
	}
	return m
}()

// international reports whether digits already start with a known calling code followed by a number of that
// country's length (the stored form: "351555010203").
func international(digits string) bool {
	for n := 1; n <= 3 && n < len(digits); n++ {
		if d, ok := byCode[digits[:n]]; ok && d.fits(len(digits)-n) {
			return true
		}
	}
	return false
}

// NormalizePhone returns digits with the country code and no '+' ("351555010203"). "+…" and "00…" are international;
// other numbers already in international form stay; a national-format number ("555 010 203", "0151 2345678") gets
// home's calling code after dropping one trunk prefix. home = ISO-2 of the owner's country ("" = no national rule).
// Ambiguous digits are read as international so normalizing a stored value never changes it.
func NormalizePhone(s, home string) string {
	var b strings.Builder
	plus := false
	for _, r := range s {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		} else if r == '+' && b.Len() == 0 {
			plus = true
		}
	}
	d := b.String()
	if strings.HasPrefix(d, "00") {
		return d[2:]
	}
	if plus || d == "" {
		return d
	}
	dial, ok := Dialings[strings.ToUpper(home)]
	if !ok {
		return d
	}
	for _, t := range dial.Trunk {
		if strings.HasPrefix(d, t) && dial.fits(len(d)-len(t)) {
			return dial.Code + d[len(t):]
		}
	}
	if international(d) {
		return d
	}
	if dial.fits(len(d)) {
		return dial.Code + d
	}
	return d
}
