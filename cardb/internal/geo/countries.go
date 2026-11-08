package geo

import (
	"sort"
	"strings"
	"unicode"
)

// countryWords names a country in free text (EN/DE/FR/ES/PT/IT/native; nouns and adjectives).
type countryWords struct {
	words    []string            // folded whole words
	prefixes []string            // folded word starts (German adjective endings: polnische, polnischen…)
	cased    []string            // matched only with this capitalisation (English "Polish" vs "polish" = car polish)
	notAfter map[string][]string // word → preceding words that cancel it ("de polen" = pollen in ES/PT)
}

// mentionNames: countries whose mention in a fact (origin, import, history) can be a hard filter. Add a country here
// with its words before using it in search.hard_filters[].mentions_country.
var mentionNames = map[string]countryWords{
	"PL": {
		words: []string{"poland", "polen", "polska", "polski", "polskie", "pologne", "polonia", "polaco", "polaca", "polacos", "polacas",
			"polacco", "polacca", "polacchi", "polacche", "polones", "polonesa", "poloneses", "polonesas", "polonais", "polonaise", "polonaises"},
		prefixes: []string{"polnisch"},
		cased:    []string{"Polish"},
		notAfter: map[string][]string{"polen": {"de"}},
	},
	"LT": {
		words: []string{"lithuania", "lithuanian", "litauen", "lituanie", "lituanien", "lituanienne", "lituania", "lituano", "lituana",
			"lituanos", "lituanas", "lietuva", "lietuvos"},
		prefixes: []string{"litauisch"},
	},
	"LV": {
		words: []string{"latvia", "latvian", "lettland", "lettonie", "letton", "lettone", "lettonne", "lettonia", "letonia", "leton", "letona",
			"letones", "letonas", "letao", "latvija", "latvijas"},
		prefixes: []string{"lettisch"},
	},
	"EE": {
		words: []string{"estonia", "estonian", "estland", "estonie", "estonien", "estonienne", "estonio", "estonios", "estonias", "estone",
			"estoni", "eesti"},
		prefixes: []string{"estnisch"},
	},
}

// MentionCountries lists the ISO-2 codes MentionedCountry knows, sorted.
func MentionCountries() []string {
	out := make([]string, 0, len(mentionNames))
	for c := range mentionNames {
		out = append(out, c)
	}
	sort.Strings(out)
	return out
}

// MentionedCountry returns the first of codes (ISO-2) that free text names, or "".
func MentionedCountry(text string, codes []string) string {
	toks := strings.Fields(FoldWords(text))
	var raw []string // original-case words, for cased matches
	for _, code := range codes {
		cw, ok := mentionNames[strings.ToUpper(code)]
		if !ok {
			continue
		}
		for i, t := range toks {
			if cancel := cw.notAfter[t]; i > 0 && contains(cancel, toks[i-1]) {
				continue
			}
			if contains(cw.words, t) {
				return strings.ToUpper(code)
			}
			for _, p := range cw.prefixes {
				if strings.HasPrefix(t, p) {
					return strings.ToUpper(code)
				}
			}
		}
		if len(cw.cased) > 0 {
			if raw == nil {
				raw = strings.FieldsFunc(text, func(r rune) bool { return !unicode.IsLetter(r) })
			}
			for _, w := range raw {
				if contains(cw.cased, w) {
					return strings.ToUpper(code)
				}
			}
		}
	}
	return ""
}

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}
