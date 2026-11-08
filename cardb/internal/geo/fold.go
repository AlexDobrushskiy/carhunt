// Package geo holds generic geographic and language data: text folding, ISO 3166-2 region place names, country
// names in EU languages, telephone dialing plans, country centroids and VAT rates. Nothing buyer-specific.
package geo

import (
	"strings"
	"unicode"
)

// Diacritics maps accented lower-case letters to their ASCII base ("ł" → "l", "ß" → "ss").
var Diacritics = func() map[rune]string {
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

// FoldWords lowercases, strips diacritics and turns every non-alphanumeric rune (including '.' and '-') into a space.
func FoldWords(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if f, ok := Diacritics[r]; ok {
			b.WriteString(f)
			continue
		}
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
		} else {
			b.WriteByte(' ')
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

// HasPhrase reports whether the folded phrase occurs as whole words in folded text.
func HasPhrase(folded, phrase string) bool {
	return phrase != "" && strings.Contains(" "+folded+" ", " "+phrase+" ")
}
