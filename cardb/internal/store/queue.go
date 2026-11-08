package store

import (
	"cmp"
	"context"
	"database/sql"
	"fmt"
	"math"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode"

	"carhunt/cardb/internal/api"
)

// "To rate" queue: unrated cars that pass the owner's standing hard filters, in tier / deal / trim / price order.
// DESIGN.md "To rate queue" documents every rule here; keep both in sync.

// Hard filters. A missing value passes (and shows as unknown in the why line).
const (
	queueYearMin  = 2023
	queuePriceMax = 42000
	queueKmMax    = 50000
)

var (
	queueCountries = []string{"PT", "ES", "DE", "FR", "BE", "NL", "LU", "IT"}
	// queueClosedStatuses leave the queue.
	queueClosedStatuses = []string{"closed", "dropped", "bought"}
	// islandMarkers are matched as whole words against the folded city.
	islandMarkers = []string{"madeira", "funchal", "acores", "azores", "ponta delgada", "canarias", "canary", "las palmas",
		"tenerife", "gran canaria", "lanzarote", "fuerteventura"}
	// historyFactKeys are scanned for a Polish / Baltic history.
	historyFactKeys = []string{"origin", "import", "history_report", "other"}
	queueFactKeys   = append([]string{"trim_score", "deal_flag"}, historyFactKeys...)
	defaultTiers    = []int{1, 2}
)

// balticNames: folded whole words naming Poland / Lithuania / Latvia / Estonia (EN/DE/FR/ES/PT/IT/native, nouns and
// adjectives). balticPrefixes match the start of a word (German adjective endings). English "Polish" is matched only
// capitalised ("polish" = car polish); "polen" after "de" is the Spanish/Portuguese word for pollen ("filtro de polen").
var (
	balticNames = map[string]string{}
	balticWords = map[string][]string{
		"Poland": {"poland", "polen", "polska", "polski", "polskie", "pologne", "polonia", "polaco", "polaca", "polacos", "polacas",
			"polacco", "polacca", "polacchi", "polacche", "polones", "polonesa", "poloneses", "polonesas", "polonais", "polonaise", "polonaises"},
		"Lithuania": {"lithuania", "lithuanian", "litauen", "lituanie", "lituanien", "lituanienne", "lituania", "lituano", "lituana",
			"lituanos", "lituanas", "lietuva", "lietuvos"},
		"Latvia": {"latvia", "latvian", "lettland", "lettonie", "letton", "lettone", "lettonne", "lettonia", "letonia", "leton", "letona",
			"letones", "letonas", "letao", "latvija", "latvijas"},
		"Estonia": {"estonia", "estonian", "estland", "estonie", "estonien", "estonienne", "estonio", "estonios", "estonias", "estone",
			"estoni", "eesti"},
	}
	balticPrefixes = map[string]string{"polnisch": "Poland", "litauisch": "Lithuania", "lettisch": "Latvia", "estnisch": "Estonia"}
)

func init() {
	for country, ws := range balticWords {
		for _, w := range ws {
			balticNames[w] = country
		}
	}
}

// foldWords lowercases, strips diacritics and turns every non-alphanumeric rune (including '.' and '-') into a space.
func foldWords(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if f, ok := foldDiacritics[r]; ok {
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

func hasPhrase(folded, phrase string) bool {
	return strings.Contains(" "+folded+" ", " "+phrase+" ")
}

// isIsland reports whether a city is on Madeira, the Azores or the Canary Islands.
func isIsland(city string) bool {
	f := foldWords(city)
	for _, m := range islandMarkers {
		if hasPhrase(f, m) {
			return true
		}
	}
	return false
}

// balticHistory returns the country (Poland/Lithuania/Latvia/Estonia) a free-text fact value names, or "".
func balticHistory(value string) string {
	toks := strings.Fields(foldWords(value))
	for i, t := range toks {
		if t == "polen" && i > 0 && toks[i-1] == "de" {
			continue
		}
		if c, ok := balticNames[t]; ok {
			return c
		}
		for p, c := range balticPrefixes {
			if strings.HasPrefix(t, p) {
				return c
			}
		}
	}
	for _, w := range strings.FieldsFunc(value, func(r rune) bool { return !unicode.IsLetter(r) }) {
		if w == "Polish" {
			return "Poland"
		}
	}
	return ""
}

// queueFacts are the facts the queue reads (loaded only for GET /queue).
type queueFacts struct {
	trimScore *string
	dealFlag  string
	history   []string
}

func loadQueueFacts(tx *sql.Tx) (map[int64]*queueFacts, error) {
	out := map[int64]*queueFacts{}
	q := "SELECT car_id, key, value FROM facts WHERE key IN (?" + strings.Repeat(", ?", len(queueFactKeys)-1) + ")"
	args := make([]any, len(queueFactKeys))
	for i, k := range queueFactKeys {
		args[i] = k
	}
	err := eachRow(tx, q, args, func(sc scanner) error {
		var id int64
		var k, v string
		if err := sc.Scan(&id, &k, &v); err != nil {
			return err
		}
		qf := out[id]
		if qf == nil {
			qf = &queueFacts{}
			out[id] = qf
		}
		switch k {
		case "trim_score":
			qf.trimScore = &v
		case "deal_flag":
			qf.dealFlag = v
		default:
			qf.history = append(qf.history, v)
		}
		return nil
	})
	return out, err
}

// queueExclusion returns why a car is not in the queue, or "" when it is eligible.
func queueExclusion(c *api.CarSummary, qf *queueFacts) string {
	if qf == nil {
		qf = &queueFacts{}
	}
	switch {
	case c.Verdict != nil:
		return "rated"
	case slices.Contains(queueClosedStatuses, c.Status):
		return "status " + c.Status
	case c.LiveListingCount == 0:
		return "no live listing"
	case c.Year != nil && *c.Year < queueYearMin:
		return fmt.Sprintf("year < %d", queueYearMin)
	case c.Price != nil && *c.Price > queuePriceMax:
		return fmt.Sprintf("price > %d", queuePriceMax)
	case c.Km != nil && *c.Km > queueKmMax:
		return fmt.Sprintf("km > %d", queueKmMax)
	case c.Country != nil && *c.Country != "" && !slices.Contains(queueCountries, strings.ToUpper(*c.Country)):
		return "country " + *c.Country
	case c.City != nil && isIsland(*c.City):
		return "island"
	}
	if f := strings.Fields(foldWords(qf.dealFlag)); len(f) > 0 && f[0] == "suspect" {
		return "deal_flag suspect"
	}
	for _, v := range qf.history {
		if country := balticHistory(v); country != "" {
			return "history " + country
		}
	}
	return ""
}

// --- tier ---------------------------------------------------------------------------

var reTextPower = regexp.MustCompile(`(?i)(?:^|[^0-9.,])(\d{2,3})(?:[.,]\d)?\s*(kw|cv|ps|ch|hp|bhp|pk)\b`)

// textHorsepower reads a power figure from ad text ("210kW", "286 CV", "285ch", "190 PK"); nil when there is none.
func textHorsepower(s string) *int {
	m := reTextPower.FindStringSubmatch(s)
	if m == nil {
		return nil
	}
	n, _ := strconv.Atoi(m[1])
	hp := n
	if strings.EqualFold(m[2], "kw") {
		if n < 40 || n > 400 {
			return nil
		}
		hp = api.Horsepower(float64(n))
	}
	if hp < 60 || hp > 600 {
		return nil
	}
	return &hp
}

func near286(hp int) bool { return hp >= 280 && hp <= 290 }

var reIoniqLongRange = regexp.MustCompile(`(?i)(?:^|[^0-9.,])(77|84)(?:[.,]\d)?\s*(?:kwh)?(?:$|[^0-9])`)

// carTier: 1 = VAG 286 hp RWD (ID.4/ID.5 Pro, Q4 45, Enyaq 85), 2 = Ioniq 5 long range, EV6 (not GT/GT-Line), XPeng G6,
// Tavascan 286 hp RWD, 3 = everything else. Power = power_kw and/or a figure in model/variant ("210 kW", "286 CV").
// Power known: one of them must be ≈286 hp (280–290) and then qualifies without the trim marker; unknown: the marker decides.
func carTier(c *api.CarSummary) int {
	fam := optStr(c.ModelFamily)
	if fam == "" {
		return 3
	}
	text := optStr(c.Model) + " " + optStr(c.Variant)
	toks := strings.Fields(foldWords(text))
	has := func(ws ...string) bool {
		for _, w := range ws {
			if slices.Contains(toks, w) {
				return true
			}
		}
		return false
	}
	// Power is known when power_kw or the text gives a figure; either one ≈286 is enough (power_kw is sometimes a
	// mis-entered battery size while the text says "210 kW / 286 pk").
	var powers []int
	if c.PowerKw != nil {
		powers = append(powers, api.Horsepower(*c.PowerKw))
	}
	if hp := textHorsepower(text); hp != nil {
		powers = append(powers, *hp)
	}
	awd := strings.EqualFold(optStr(c.Drive), "awd") || has("quattro", "4motion", "4x4", "awd", "4wd", "allrad")
	yearOK := func(min int) bool { return c.Year == nil || *c.Year >= min }
	rwd286 := func(marker, excluded bool, minYear int) bool {
		if excluded || awd || !yearOK(minYear) {
			return false
		}
		if len(powers) > 0 {
			return slices.ContainsFunc(powers, near286)
		}
		return marker
	}
	switch fam {
	case "VW ID.4", "VW ID.5":
		// "Pro Performance" / "Pro Power" are the 150 kW trims.
		if rwd286(has("pro") && !has("performance", "power"), has("gtx", "pure"), 2023) {
			return 1
		}
	case "Audi Q4", "Audi Q4 Sportback":
		if rwd286(has("45"), has("sq4"), 2024) {
			return 1
		}
	case "Škoda Enyaq", "Škoda Enyaq Coupé":
		if rwd286(has("85"), has("85x", "rs"), 0) {
			return 1
		}
	case "Hyundai Ioniq 5":
		if c.BatteryNetKwh != nil {
			if *c.BatteryNetKwh >= 74 && *c.BatteryNetKwh <= 85 {
				return 2
			}
		} else if reIoniqLongRange.MatchString(text) {
			return 2
		}
	case "Kia EV6":
		if !has("gt", "gtline") {
			return 2
		}
	case "XPeng G6":
		return 2
	case "Cupra Tavascan":
		if rwd286(has("endurance"), has("vz"), 0) {
			return 2
		}
	}
	return 3
}

// --- trim score ---------------------------------------------------------------------

type trimOption struct {
	key, label string
	weight     float64
}

// trimOptions: weights from the VAG trim heuristics; yes = +w, no = −w, unknown/missing = 0.
var trimOptions = []trimOption{
	{"electric_seats", "e-seats", 4}, {"power_tailgate", "tailgate", 3}, {"pano", "pano", 1.5},
	{"memory_seats", "memory", 1}, {"premium_audio", "audio", 1}, {"heat_pump", "heat pump", 1},
}

const bigWheelsPenalty = 0.5 // wheels_in ≥ 20

// trimScore: the numeric trim_score fact if present, else the option-weight sum. Source = fact | options.
func trimScore(c *api.CarSummary, fact *string) (float64, string) {
	if fact != nil {
		if v, err := strconv.ParseFloat(strings.Replace(strings.TrimSpace(*fact), ",", ".", 1), 64); err == nil && !math.IsNaN(v) && !math.IsInf(v, 0) {
			return v, "fact"
		}
	}
	s := 0.0
	for _, o := range trimOptions {
		switch c.Options[o.key] {
		case "yes":
			s += o.weight
		case "no":
			s -= o.weight
		}
	}
	if c.WheelsIn != nil && *c.WheelsIn >= 20 {
		s -= bigWheelsPenalty
	}
	return math.Round(s*10) / 10, "options"
}

// --- fair price ---------------------------------------------------------------------

const fairMinN = 3

type fairIndex struct {
	byYear map[string][]int // "family|year"
	byFam  map[string][]int
}

// newFairIndex collects prices of live cars (≥ 1 live listing, price known) per family + year and per family.
func newFairIndex(cars []*api.CarSummary) fairIndex {
	fi := fairIndex{byYear: map[string][]int{}, byFam: map[string][]int{}}
	for _, c := range cars {
		if c.LiveListingCount == 0 || c.Price == nil || c.ModelFamily == nil {
			continue
		}
		fi.byFam[*c.ModelFamily] = append(fi.byFam[*c.ModelFamily], *c.Price)
		if c.Year != nil {
			k := fmt.Sprintf("%s|%d", *c.ModelFamily, *c.Year)
			fi.byYear[k] = append(fi.byYear[k], *c.Price)
		}
	}
	return fi
}

func median(xs []int) int {
	s := slices.Clone(xs)
	slices.Sort(s)
	if len(s)%2 == 1 {
		return s[len(s)/2]
	}
	return int(math.Round(float64(s[len(s)/2-1]+s[len(s)/2]) / 2))
}

// fair returns the fair price, sample size and basis ("VW ID.4 2024" / "VW ID.4 all years") for a car.
func (fi fairIndex) fair(c *api.CarSummary) (*int, int, *string) {
	if c.ModelFamily == nil {
		return nil, 0, nil
	}
	fam := *c.ModelFamily
	if c.Year != nil {
		if ps := fi.byYear[fmt.Sprintf("%s|%d", fam, *c.Year)]; len(ps) >= fairMinN {
			m, b := median(ps), fmt.Sprintf("%s %d", fam, *c.Year)
			return &m, len(ps), &b
		}
	}
	if ps := fi.byFam[fam]; len(ps) >= fairMinN {
		m, b := median(ps), fam+" all years"
		return &m, len(ps), &b
	}
	return nil, 0, nil
}

func priceGapPct(price, fair *int) *float64 {
	if price == nil || fair == nil || *fair <= 0 {
		return nil
	}
	g := math.Round(float64(*price-*fair)/float64(*fair)*1000) / 10
	return &g
}

// --- why line -----------------------------------------------------------------------

const maxWhy = 160

// queueWhy: a good deal shows its note; otherwise known key options, the price gap, then unknowns.
func queueWhy(c *api.CarSummary, gap *float64, fairN int, fairBasis *string) string {
	if c.GoodDeal {
		if n := strings.TrimSpace(optStr(c.GoodDealNote)); n != "" {
			return clipRunes(n, maxWhy)
		}
		return "good deal"
	}
	var parts []string
	for _, o := range trimOptions {
		switch c.Options[o.key] {
		case "yes":
			parts = append(parts, "✓ "+o.label)
		case "no":
			parts = append(parts, "✗ "+o.label)
		}
	}
	if c.WheelsIn != nil && *c.WheelsIn >= 20 {
		parts = append(parts, fmt.Sprintf("✗ %d\" wheels", *c.WheelsIn))
	}
	if gap != nil && fairBasis != nil {
		basis := *fairBasis
		if _, mk, ok := CanonicalFamily(optStr(c.ModelFamily)); ok {
			basis = strings.TrimPrefix(basis, mk+" ")
		}
		parts = append(parts, fmt.Sprintf("%s %% vs %s (n=%d)", signedPct(*gap), basis, fairN))
	}
	var unknown []string
	for _, k := range []struct{ key, label string }{{"electric_seats", "e-seats"}, {"power_tailgate", "tailgate"}} {
		if v := c.Options[k.key]; v != "yes" && v != "no" {
			unknown = append(unknown, "? "+k.label)
		}
	}
	for _, u := range []struct {
		label   string
		missing bool
	}{
		{"power", c.PowerKw == nil}, {"year", c.Year == nil}, {"km", c.Km == nil}, {"price", c.Price == nil},
		{"country", c.Country == nil || *c.Country == ""},
	} {
		if u.missing {
			unknown = append(unknown, "? "+u.label)
		}
	}
	if len(unknown) > 0 {
		parts = append(parts, strings.Join(unknown, " "))
	}
	return clipRunes(strings.Join(parts, " · "), maxWhy)
}

// signedPct rounds to a whole percent: "−8", "+5", "±0".
func signedPct(g float64) string {
	n := int(math.Round(g))
	switch {
	case n < 0:
		return fmt.Sprintf("−%d", -n)
	case n > 0:
		return fmt.Sprintf("+%d", n)
	}
	return "±0"
}

func clipRunes(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max-1]) + "…"
}

// --- ordering + endpoint ------------------------------------------------------------

type queueEntry struct {
	item     api.QueueItem
	deal     dealRankKey
	createdT float64
}

// compareQueue: tier asc; good deal first, then deal_rank (parsed, unparseable, missing); trim score desc;
// price gap asc (missing last); created_at desc; id desc.
func compareQueue(a, b *queueEntry) int {
	if c := cmp.Compare(a.item.Tier, b.item.Tier); c != 0 {
		return c
	}
	if a.item.Car.GoodDeal != b.item.Car.GoodDeal {
		if a.item.Car.GoodDeal {
			return -1
		}
		return 1
	}
	if c := a.deal.compare(b.deal, false); c != 0 {
		return c
	}
	if c := cmp.Compare(b.item.TrimScore, a.item.TrimScore); c != 0 {
		return c
	}
	ga, gb := a.item.PriceGapPct, b.item.PriceGapPct
	switch {
	case ga != nil && gb != nil && *ga != *gb:
		return cmp.Compare(*ga, *gb)
	case (ga == nil) != (gb == nil):
		if ga != nil {
			return -1
		}
		return 1
	}
	if c := cmp.Compare(b.createdT, a.createdT); c != 0 {
		return c
	}
	return cmp.Compare(b.item.Car.ID, a.item.Car.ID)
}

// parseTiers reads tier values ("1", "2,3", "T1"); empty = def.
func parseTiers(vals []string, def []int) ([]int, error) {
	var out []int
	for _, v := range vals {
		for _, p := range strings.Split(v, ",") {
			p = strings.TrimPrefix(strings.ToLower(strings.TrimSpace(p)), "t")
			if p == "" {
				continue
			}
			n, err := strconv.Atoi(p)
			if err != nil || n < 1 || n > 3 {
				return nil, badRequestf("tier must be 1|2|3")
			}
			if !slices.Contains(out, n) {
				out = append(out, n)
			}
		}
	}
	if len(out) == 0 {
		return slices.Clone(def), nil
	}
	sort.Ints(out)
	return out, nil
}

// QueueFilter carries the GET /queue query.
type QueueFilter struct {
	Tier          []string // default 1,2
	Spec          string   // "", "confirmed" or "unknown" (see specMatch)
	Limit, Offset int
}

// specMatch filters on the owner's two must-have options, electric seats and power tailgate:
// confirmed = both yes; unknown = neither is no and at least one is unknown (worth asking the seller).
func specMatch(c *api.CarSummary, spec string) bool {
	if spec == "" {
		return true
	}
	yes := 0
	for _, k := range []string{"electric_seats", "power_tailgate"} {
		switch c.Options[k] {
		case "yes":
			yes++
		case "no":
			return false
		}
	}
	if spec == "confirmed" {
		return yes == 2
	}
	return yes < 2
}

// Queue handles GET /queue.
func (s *Store) Queue(ctx context.Context, f QueueFilter) (*api.Queue, error) {
	tiers, err := parseTiers(f.Tier, defaultTiers)
	if err != nil {
		return nil, err
	}
	if f.Limit <= 0 {
		f.Limit = 200
	}
	f.Limit = min(f.Limit, 1000)
	f.Offset = max(f.Offset, 0)
	if f.Spec != "" && f.Spec != "confirmed" && f.Spec != "unknown" {
		return nil, badRequestf("spec must be confirmed|unknown, got %q", f.Spec)
	}
	var rows []*summaryRow
	var facts map[int64]*queueFacts
	if err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		if rows, err = buildSummaries(tx); err != nil {
			return err
		}
		facts, err = loadQueueFacts(tx)
		return err
	}); err != nil {
		return nil, err
	}
	cars := make([]*api.CarSummary, len(rows))
	for i, r := range rows {
		cars[i] = &r.CarSummary
	}
	fi := newFairIndex(cars)
	out := &api.Queue{Counts: map[string]int{"1": 0, "2": 0, "3": 0}, Items: []api.QueueItem{}}
	var entries []*queueEntry
	for _, r := range rows {
		c := &r.CarSummary
		qf := facts[c.ID]
		if queueExclusion(c, qf) != "" || !specMatch(c, f.Spec) {
			continue
		}
		out.Counts[strconv.Itoa(c.Tier)]++
		if !slices.Contains(tiers, c.Tier) {
			continue
		}
		var tsFact *string
		if qf != nil {
			tsFact = qf.trimScore
		}
		ts, src := trimScore(c, tsFact)
		fair, n, basis := fi.fair(c)
		gap := priceGapPct(c.Price, fair)
		entries = append(entries, &queueEntry{
			item: api.QueueItem{Tier: c.Tier, Car: *c, TrimScore: ts, TrimScoreSource: src, FairPrice: fair, FairN: n,
				FairBasis: basis, PriceGapPct: gap, Why: queueWhy(c, gap, n, basis)},
			deal: parseDealRank(c.DealRank), createdT: r.createdT,
		})
	}
	slices.SortFunc(entries, compareQueue)
	out.Total = len(entries)
	for i := f.Offset; i < len(entries) && i < f.Offset+f.Limit; i++ {
		it := entries[i].item
		it.Position = i + 1
		out.Items = append(out.Items, it)
	}
	return out, nil
}
