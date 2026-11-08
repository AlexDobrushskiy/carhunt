package store

import (
	"carhunt/cardb/internal/geo"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"unicode"
)

// NormURL is a parsed listing URL.
type NormURL struct {
	URL     string // display form: lowercased scheme/host, no fragment/tracking params/trailing slash
	Key     string // match key: like URL but without scheme and www./m. host prefix
	Site    string // StandVirtual, OLX, … or the bare host
	SiteRef string // site ad id, "" if unknown
	Country string // default country implied by the site, "" if unknown
}

var trackingParams = map[string]bool{
	"fbclid": true, "gclid": true, "dclid": true, "msclkid": true, "yclid": true, "igshid": true,
	"ref": true, "ref_src": true, "src": true, "source": true, "mc_cid": true, "mc_eid": true,
	"_ga": true, "_gl": true, "si": true, "spm": true,
}

var (
	reIDCode    = regexp.MustCompile(`(ID[0-9A-Za-z]+)`)
	reSVRef     = regexp.MustCompile(`(ID[0-9A-Za-z]+)\.html`)
	reTrailNum  = regexp.MustCompile(`(\d+)(?:\.html?)?$`)
	reUUIDTail  = regexp.MustCompile(`([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$`)
	reLaCentral = regexp.MustCompile(`/auto-occasion-annonce-(\d+)`)
	reNumSeg    = regexp.MustCompile(`/(\d+)(?:\.html?)?(?:/|$)`)
	reMobileNum = regexp.MustCompile(`(\d{6,})\.html`)
)

// NormalizeURL parses and normalizes a listing URL.
func NormalizeURL(raw string) (NormURL, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return NormURL{}, invalidf("url is required")
	}
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return NormURL{}, invalidf("invalid url %q", raw)
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" {
		return NormURL{}, invalidf("invalid url scheme %q", u.Scheme)
	}
	host := strings.ToLower(u.Host)
	host = strings.TrimSuffix(host, ":443")
	host = strings.TrimSuffix(host, ":80")
	matchHost := host
	for _, p := range []string{"www.", "m."} {
		matchHost = strings.TrimPrefix(matchHost, p)
	}

	q := u.Query()
	keys := make([]string, 0, len(q))
	for k := range q {
		lk := strings.ToLower(k)
		if strings.HasPrefix(lk, "utm_") || trackingParams[lk] {
			continue
		}
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var qs []string
	for _, k := range keys {
		vals := append([]string(nil), q[k]...)
		sort.Strings(vals)
		for _, v := range vals {
			qs = append(qs, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	path := strings.TrimRight(u.EscapedPath(), "/")
	query := ""
	if len(qs) > 0 {
		query = "?" + strings.Join(qs, "&")
	}

	n := NormURL{
		URL: scheme + "://" + host + path + query,
		Key: matchHost + path + query,
	}
	n.Site, n.SiteRef, n.Country = siteOf(matchHost, u.Path, q)
	return n, nil
}

func siteOf(host, path string, q url.Values) (site, ref, country string) {
	path = strings.TrimRight(path, "/")
	last := func(re *regexp.Regexp, s string) string {
		m := re.FindAllStringSubmatch(s, -1)
		if len(m) == 0 {
			return ""
		}
		return m[len(m)-1][1]
	}
	switch {
	case hostIs(host, "standvirtual.com"):
		ref = last(reSVRef, path)
		if ref == "" {
			ref = last(reIDCode, path)
		}
		return "StandVirtual", ref, "PT"
	case hostIs(host, "olx.pt"):
		return "OLX", last(reIDCode, path), "PT"
	case hostIs(host, "custojusto.pt"):
		return "CustoJusto", last(reTrailNum, path), "PT"
	case hostIs(host, "mobile.de"):
		ref = q.Get("id")
		if ref == "" {
			ref = last(reMobileNum, path)
		}
		return "mobile.de", ref, "DE"
	case strings.HasPrefix(host, "autoscout24.") || strings.Contains(host, ".autoscout24."):
		tld := host[strings.LastIndex(host, ".")+1:]
		c := strings.ToUpper(tld)
		if len(c) != 2 {
			c = ""
		}
		return "AutoScout24", last(reUUIDTail, path), c
	case hostIs(host, "lacentrale.fr"):
		return "La Centrale", last(reLaCentral, path), "FR"
	case hostIs(host, "leboncoin.fr"):
		return "leboncoin", last(reNumSeg, path+"/"), "FR"
	case hostIs(host, "coches.net"):
		return "coches.net", last(reTrailNum, path), "ES"
	}
	return host, "", ""
}

func hostIs(host, domain string) bool {
	return host == domain || strings.HasSuffix(host, "."+domain)
}

// NormalizePhone: digits with the country code, no + ("351555010203"); a national-format number gets the calling
// code of home (ISO-2, the owner's country). See geo.NormalizePhone.
func NormalizePhone(s, home string) string { return geo.NormalizePhone(s, home) }

// looksLikePhone: only phone punctuation and at least 7 digits.
func looksLikePhone(s string) bool {
	digits := 0
	for _, r := range s {
		switch {
		case r >= '0' && r <= '9':
			digits++
		case strings.ContainsRune("+-() ./", r):
		default:
			return false
		}
	}
	return digits >= 7
}

// NormalizeContact normalizes a contact value by kind (home: see NormalizePhone).
func NormalizeContact(kind, value, home string) string {
	value = strings.TrimSpace(value)
	switch kind {
	case "phone", "whatsapp":
		return NormalizePhone(value, home)
	case "email":
		return strings.ToLower(value)
	}
	return value
}

// NormalizeCounterpart turns a phone/email/handle into the form stored on messages and contacts (home: see NormalizePhone).
func NormalizeCounterpart(s, home string) string {
	s = strings.TrimSpace(s)
	switch {
	case s == "":
		return ""
	case looksLikePhone(s):
		return NormalizePhone(s, home)
	case strings.Contains(s, "@") && !strings.Contains(s, "/"):
		return strings.ToLower(s)
	}
	return s
}

// NormalizeVIN uppercases and strips separators; returns "" unless 17 chars.
func NormalizeVIN(s string) string {
	v := alnumUpper(s)
	if len(v) != 17 {
		return ""
	}
	return v
}

// NormalizePlate keeps alphanumerics uppercased.
func NormalizePlate(s string) string {
	v := alnumUpper(s)
	if len(v) < 4 {
		return ""
	}
	return v
}

func alnumUpper(s string) string {
	var b strings.Builder
	for _, r := range s {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(unicode.ToUpper(r))
		}
	}
	return b.String()
}

func lowerTrim(s *string) string {
	if s == nil {
		return ""
	}
	return strings.ToLower(strings.TrimSpace(*s))
}
