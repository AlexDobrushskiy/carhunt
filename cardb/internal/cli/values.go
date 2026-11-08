package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

// ---- car spec flags (shared by upsert and set) ----

type specField struct {
	flag    string
	key     string // JSON key; "powertrain.x" nests under powertrain
	kind    string // str | int | float
	help    string
	aliases []string
}

var specFields = []specField{
	{flag: "make", key: "make", kind: "str", help: "make, e.g. MINI"},
	{flag: "model", key: "model", kind: "str", help: "model, e.g. 'Countryman E'"},
	{flag: "variant", key: "variant", kind: "str", help: "trim/variant"},
	{flag: "body", key: "body", kind: "str", help: "body/seat note"},
	{flag: "reg", key: "reg_date", kind: "str", help: "first registration YYYY-MM[-DD] (MM/YYYY accepted)", aliases: []string{"reg-date"}},
	{flag: "km", key: "km", kind: "int", help: "odometer km"},
	{flag: "fuel", key: "powertrain.fuel", kind: "str", help: strings.Join(api.Fuels, "|")},
	{flag: "battery-net", key: "powertrain.battery_net_kwh", kind: "float", help: "net (usable) battery kWh"},
	{flag: "battery-gross", key: "powertrain.battery_gross_kwh", kind: "float", help: "gross battery kWh"},
	{flag: "engine-cc", key: "powertrain.engine_cc", kind: "int", help: "engine displacement, cc"},
	{flag: "gearbox", key: "powertrain.gearbox", kind: "str", help: strings.Join(api.Gearboxes, "|")},
	{flag: "wltp-range", key: "powertrain.wltp_range_km", kind: "int", help: "WLTP electric range, km"},
	{flag: "wltp-consumption", key: "powertrain.wltp_consumption", kind: "float", help: "WLTP consumption, kWh/100 km (BEV) or l/100 km"},
	{flag: "co2", key: "powertrain.co2_g_km", kind: "int", help: "CO2, g/km"},
	{flag: "power-kw", key: "power_kw", kind: "float", help: "power kW"},
	{flag: "drive", key: "drive", kind: "str", help: "fwd|rwd|awd|unknown"},
	{flag: "seats", key: "seats", kind: "int", help: "seats"},
	{flag: "colour", key: "colour", kind: "str", help: "exterior colour", aliases: []string{"color"}},
	{flag: "interior", key: "interior", kind: "str", help: "interior colour + material"},
	{flag: "interior-tone", key: "interior_tone", kind: "str", help: "dark|grey|brown|light|unknown"},
	{flag: "wheels", key: "wheels_in", kind: "int", help: "wheel size, inches"},
	{flag: "vin", key: "vin", kind: "str", help: "VIN"},
	{flag: "plate", key: "plate", kind: "str", help: "licence plate"},
	{flag: "country", key: "country", kind: "str", help: "ISO-2 country (PT, ES, DE…)"},
	{flag: "city", key: "city", kind: "str", help: "city"},
	{flag: "distance-km", key: "distance_km", kind: "int", help: "road distance from home, km"},
}

var (
	driveValues        = []string{"fwd", "rwd", "awd", "unknown"}
	interiorToneValues = []string{"dark", "grey", "brown", "light", "unknown"}
)

// specVals holds the raw string values of the spec flags.
type specVals map[string]*string

func addSpecFlags(f *flags) specVals {
	v := specVals{}
	for _, sf := range specFields {
		p := new(string)
		f.StringVar(p, sf.flag, "", sf.help)
		for _, a := range sf.aliases {
			f.StringVar(p, a, "", "alias of --"+sf.flag)
		}
		v[sf.flag] = p
	}
	return v
}

func (sf specField) isSet(f *flags) bool {
	if f.isSet(sf.flag) {
		return true
	}
	for _, a := range sf.aliases {
		if f.isSet(a) {
			return true
		}
	}
	return false
}

// collect returns the set spec flags as JSON key → typed value.
func (v specVals) collect(f *flags) (map[string]any, error) {
	out := map[string]any{}
	for _, sf := range specFields {
		if !sf.isSet(f) {
			continue
		}
		val, err := parseSpecValue(sf, *v[sf.flag])
		if err != nil {
			return nil, err
		}
		putPath(out, sf.key, val)
	}
	return out, nil
}

var (
	reRegFull  = regexp.MustCompile(`^\d{4}-\d{2}(-\d{2})?$`)
	reRegMY    = regexp.MustCompile(`^(\d{1,2})[/.-](\d{4})$`)
	reRegDMY   = regexp.MustCompile(`^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$`)
	reRegYear  = regexp.MustCompile(`^\d{4}$`)
	reCountry2 = regexp.MustCompile(`^[A-Z]{2}$`)
)

func parseSpecValue(sf specField, raw string) (any, error) {
	raw = strings.TrimSpace(raw)
	switch sf.kind {
	case "int":
		n, err := parseIntLenient(raw)
		if err != nil {
			return nil, usageErrorf("--%s: %v", sf.flag, err)
		}
		return n, nil
	case "float":
		x, err := parseFloatLenient(raw)
		if err != nil {
			return nil, usageErrorf("--%s: %v", sf.flag, err)
		}
		return x, nil
	}
	switch sf.key {
	case "reg_date":
		return normalizeRegDate(raw)
	case "drive":
		d := strings.ToLower(raw)
		if !slices.Contains(driveValues, d) {
			return nil, usageErrorf("--drive: %q is not one of %s", raw, strings.Join(driveValues, "|"))
		}
		return d, nil
	case "interior_tone":
		t := strings.ToLower(raw)
		if t == "gray" {
			t = "grey"
		}
		if !slices.Contains(interiorToneValues, t) {
			return nil, usageErrorf("--interior-tone: %q is not one of %s", raw, strings.Join(interiorToneValues, "|"))
		}
		return t, nil
	case "country":
		c := strings.ToUpper(raw)
		if !reCountry2.MatchString(c) {
			return nil, usageErrorf("--country: want an ISO-2 code like PT or ES, got %q", raw)
		}
		return c, nil
	case "vin", "plate":
		return strings.ToUpper(raw), nil
	case "powertrain.fuel", "powertrain.gearbox":
		allowed := api.Fuels
		if sf.key == "powertrain.gearbox" {
			allowed = api.Gearboxes
		}
		v := strings.ToLower(raw)
		if !slices.Contains(allowed, v) {
			return nil, usageErrorf("--%s: %q is not one of %s", sf.flag, raw, strings.Join(allowed, "|"))
		}
		return v, nil
	}
	return raw, nil
}

func normalizeRegDate(raw string) (string, error) {
	switch {
	case reRegFull.MatchString(raw):
		return raw, nil
	case reRegMY.MatchString(raw):
		m := reRegMY.FindStringSubmatch(raw)
		mm, _ := strconv.Atoi(m[1])
		if mm < 1 || mm > 12 {
			break
		}
		return fmt.Sprintf("%s-%02d", m[2], mm), nil
	case reRegDMY.MatchString(raw):
		m := reRegDMY.FindStringSubmatch(raw)
		dd, _ := strconv.Atoi(m[1])
		mm, _ := strconv.Atoi(m[2])
		if mm < 1 || mm > 12 || dd < 1 || dd > 31 {
			break
		}
		return fmt.Sprintf("%s-%02d-%02d", m[3], mm, dd), nil
	case reRegYear.MatchString(raw):
		return "", usageErrorf("--reg: %q has no month; want YYYY-MM (use --fact reg_year=%s if only the year is known)", raw, raw)
	}
	return "", usageErrorf("--reg: want YYYY-MM or YYYY-MM-DD (or MM/YYYY), got %q", raw)
}

// parseIntLenient accepts "31 200", "31.200", "31,200 km", "34 600 €".
func parseIntLenient(raw string) (int, error) {
	s := strings.ToLower(strings.TrimSpace(raw))
	for _, suf := range []string{"km", "€", "eur", "euro", "euros"} {
		s = strings.TrimSpace(strings.TrimSuffix(s, suf))
	}
	s = strings.TrimPrefix(s, "€")
	s = strings.Map(func(r rune) rune {
		switch r {
		case ' ', '_', '.', ',', ' ', ' ', '\'':
			return -1
		}
		return r
	}, s)
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("not an integer: %q", raw)
	}
	return n, nil
}

func parseFloatLenient(raw string) (float64, error) {
	s := strings.ToLower(strings.TrimSpace(raw))
	for _, suf := range []string{"kwh", "kw"} {
		s = strings.TrimSpace(strings.TrimSuffix(s, suf))
	}
	s = strings.ReplaceAll(s, ",", ".")
	x, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, fmt.Errorf("not a number: %q", raw)
	}
	return x, nil
}

// ---- seller flags ----

type sellerVals struct {
	name, typ, company, city, note *string
	phones, whatsapps, emails      multi
	contacts                       multi
}

func addSellerFlags(f *flags) *sellerVals {
	s := &sellerVals{
		name:    f.String("seller-name", "", "seller name"),
		typ:     f.String("seller-type", "", "private|dealer|reseller|unknown"),
		company: f.String("seller-company", "", "dealer/company name"),
		city:    f.String("seller-city", "", "seller city"),
		note:    f.String("seller-note", "", "note about the seller"),
	}
	f.Var(&s.phones, "phone", "seller phone (repeatable)")
	f.Var(&s.whatsapps, "whatsapp", "seller WhatsApp number (repeatable)")
	f.Var(&s.emails, "email", "seller email (repeatable)")
	f.Var(&s.contacts, "contact", "seller contact KIND:VALUE, kind phone|whatsapp|email|site_chat|web (repeatable)")
	return s
}

func (s *sellerVals) build(f *flags) (*api.SellerInput, error) {
	in := &api.SellerInput{}
	any := false
	str := func(flag string, p *string, dst **string) {
		if f.isSet(flag) {
			v := strings.TrimSpace(*p)
			*dst = &v
			any = true
		}
	}
	str("seller-name", s.name, &in.Name)
	str("seller-company", s.company, &in.Company)
	str("seller-city", s.city, &in.City)
	str("seller-note", s.note, &in.Note)
	if f.isSet("seller-type") {
		t := strings.ToLower(strings.TrimSpace(*s.typ))
		if !slices.Contains(api.SellerTypes, t) {
			return nil, usageErrorf("--seller-type: %q is not one of %s", *s.typ, strings.Join(api.SellerTypes, "|"))
		}
		in.Type = &t
		any = true
	}
	add := func(kind string, vals []string) {
		for _, v := range vals {
			if v = strings.TrimSpace(v); v != "" {
				in.Contacts = append(in.Contacts, api.Contact{Kind: kind, Value: v})
				any = true
			}
		}
	}
	add("phone", s.phones)
	add("whatsapp", s.whatsapps)
	add("email", s.emails)
	for _, c := range s.contacts {
		kind, val, ok := strings.Cut(c, ":")
		kind = strings.ToLower(strings.TrimSpace(kind))
		if !ok || !slices.Contains([]string{"phone", "whatsapp", "email", "site_chat", "web"}, kind) {
			return nil, usageErrorf("--contact: want KIND:VALUE with kind phone|whatsapp|email|site_chat|web, got %q", c)
		}
		add(kind, []string{val})
	}
	if !any {
		return nil, nil
	}
	return in, nil
}

// ---- evidence args: key=value[:source[:ref]] ----

type evidenceArg struct {
	Key, Value, Source, Ref string
}

// parseEvidence splits "key=value[:source[:ref]]". The source is recognised as the first
// ':'-separated segment (after the value) that is a known evidence source, so fact values may
// contain ':' themselves; everything after the source is the ref.
func parseEvidence(arg, defSource string) (evidenceArg, error) {
	key, rest, ok := strings.Cut(arg, "=")
	key = normalizeKey(key)
	if !ok || key == "" {
		return evidenceArg{}, usageErrorf("%q: want key=value[:source[:ref]]", arg)
	}
	ev := evidenceArg{Key: key, Value: rest, Source: defSource}
	parts := strings.Split(rest, ":")
	for i := 1; i < len(parts); i++ {
		if slices.Contains(api.EvidenceSources, parts[i]) {
			ev.Value = strings.Join(parts[:i], ":")
			ev.Source = parts[i]
			ev.Ref = strings.Join(parts[i+1:], ":")
			break
		}
	}
	ev.Value = strings.TrimSpace(ev.Value)
	if ev.Source != "" && !slices.Contains(api.EvidenceSources, ev.Source) {
		return evidenceArg{}, usageErrorf("source %q is not one of %s", ev.Source, strings.Join(api.EvidenceSources, " "))
	}
	return ev, nil
}

func normalizeKey(k string) string {
	return strings.ReplaceAll(strings.ToLower(strings.TrimSpace(k)), "-", "_")
}

func normalizeOptionValue(v string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "yes", "y", "true", "1", "✓", "✔", "+", "sim", "si", "ja", "oui":
		return "yes", nil
	case "no", "n", "false", "0", "✗", "✘", "-", "não", "nao":
		return "no", nil
	case "unknown", "?", "u", "":
		return "unknown", nil
	}
	return "", usageErrorf("option value %q: want yes|no|unknown", v)
}

// parseOptionArg parses one option argument, normalising value and warning on unknown keys.
func parseOptionArg(e *env, arg, defSource string) (evidenceArg, error) {
	ev, err := parseEvidence(arg, defSource)
	if err != nil {
		return ev, err
	}
	// An option value is never free text; if no known source matched, treat value:source as an error.
	if strings.Contains(ev.Value, ":") {
		v, src, _ := strings.Cut(ev.Value, ":")
		return ev, usageErrorf("%q: %q is not a known source (%s); value was %q", arg, src, strings.Join(api.EvidenceSources, " "), v)
	}
	if ev.Value, err = normalizeOptionValue(ev.Value); err != nil {
		return ev, err
	}
	if !slices.Contains(api.OptionKeys, ev.Key) {
		e.warnf("option key %q is not a known key (%s); stored anyway", ev.Key, strings.Join(api.OptionKeys, " "))
	}
	return ev, nil
}

// ---- status / verdict ----

func statusList() []string { return api.Statuses }

func normalizeStatus(s string) (string, error) {
	st := strings.ReplaceAll(strings.ToLower(strings.TrimSpace(s)), "-", "_")
	if !slices.Contains(api.Statuses, st) {
		return "", usageErrorf("status %q is not one of %s", s, strings.Join(api.Statuses, " "))
	}
	return st, nil
}

func normalizeVerdict(v string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "up", "👍", "like", "yes", "good", "+", "+1":
		return "up", nil
	case "maybe", "🤔", "meh", "?", "unsure":
		return "maybe", nil
	case "down", "👎", "dislike", "no", "bad", "-", "-1":
		return "down", nil
	case "clear", "none", "reset":
		return "", nil
	}
	return "", usageErrorf("verdict %q: want up|maybe|down (👍 🤔 👎, like/dislike) or clear", v)
}

func normalizeOnOff(v string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "on", "yes", "y", "true", "1", "✓", "★", "good":
		return true, nil
	case "off", "no", "n", "false", "0", "✗", "clear", "none":
		return false, nil
	}
	return false, usageErrorf("%q: want on|off (yes/no, true/false, ✓/✗)", v)
}

// ---- times ----

var localLayouts = []string{"2006-01-02T15:04:05", "2006-01-02T15:04", "2006-01-02 15:04:05", "2006-01-02 15:04", "2006-01-02"}

// parseTime accepts RFC 3339, local "YYYY-MM-DD[ HH:MM[:SS]]", "now", or unix seconds.
func parseTime(flag, raw string) (time.Time, error) {
	s := strings.TrimSpace(raw)
	if s == "now" {
		return time.Now().UTC(), nil
	}
	if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return t.UTC(), nil
	}
	for _, l := range localLayouts {
		if t, err := time.ParseInLocation(l, s, time.Local); err == nil {
			return t.UTC(), nil
		}
	}
	if n, err := strconv.ParseInt(s, 10, 64); err == nil && n > 1e9 {
		return time.Unix(n, 0).UTC(), nil
	}
	return time.Time{}, usageErrorf("--%s: want RFC 3339 (2026-11-01T14:05:00Z) or 'YYYY-MM-DD HH:MM' local, got %q", flag, raw)
}

// parseSince also accepts a duration back from now: 30m, 24h, 7d.
func parseSince(raw string) (time.Time, error) {
	s := strings.TrimSpace(raw)
	if strings.HasSuffix(s, "d") {
		if n, err := strconv.Atoi(strings.TrimSuffix(s, "d")); err == nil {
			return time.Now().Add(-time.Duration(n) * 24 * time.Hour).UTC(), nil
		}
	}
	if d, err := time.ParseDuration(s); err == nil {
		return time.Now().Add(-d).UTC(), nil
	}
	return parseTime("since", s)
}

// ---- inputs ----

// readInput reads a file, or stdin for "-".
func (e *env) readInput(path string) ([]byte, error) {
	if path == "-" {
		return io.ReadAll(e.stdin)
	}
	return os.ReadFile(path)
}

// textArg resolves TEXT from a positional (or "-" for stdin) or --text-file.
func (e *env) textArg(pos []string, textFile string) (string, error) {
	if textFile != "" {
		if len(pos) > 0 {
			return "", usageErrorf("give TEXT or --text-file, not both")
		}
		b, err := e.readInput(textFile)
		return strings.TrimRight(string(b), "\n"), err
	}
	if len(pos) == 0 {
		return "", nil
	}
	if len(pos) > 1 {
		return "", usageErrorf("got %d text arguments; quote the text as one argument", len(pos))
	}
	if pos[0] == "-" {
		b, err := io.ReadAll(e.stdin)
		return strings.TrimRight(string(b), "\n"), err
	}
	return pos[0], nil
}

func parseJSONArg(flag, raw string) (json.RawMessage, error) {
	if !json.Valid([]byte(raw)) {
		return nil, usageErrorf("--%s: not valid JSON: %s", flag, raw)
	}
	return json.RawMessage(raw), nil
}

func parseID(what, s string) (int64, error) {
	n, err := strconv.ParseInt(strings.TrimPrefix(strings.TrimSpace(s), "#"), 10, 64)
	if err != nil || n <= 0 {
		return 0, usageErrorf("%s: want a numeric id, got %q", what, s)
	}
	return n, nil
}

func isURL(s string) bool {
	return strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://")
}
