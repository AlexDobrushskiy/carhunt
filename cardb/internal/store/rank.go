package store

import (
	"fmt"
	"math"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/geo"
	"carhunt/cardb/internal/profile"
)

// The "to rate" queue and its ranking are one pure function of (cars, facts, profile, now): tiers from
// search.models, hard filters from search, then the value model (peer-group fair landed price → value; fit; risk;
// score). DESIGN.md "Ranking" documents the rules; the profile's ranking keys hold every tunable.

// ranker is everything derived from one profile. Read-only; rebuilt by Store.SetProfile.
type ranker struct {
	p     *profile.Profile
	fam   *Families
	rules []tierRule
}

// tierRule is a compiled search.models entry.
type tierRule struct {
	m    profile.Model
	base string // base family the entry names; "" = any family of make
	make string // canonical make
}

const noFamily = "\x00" // a model entry whose family could not be resolved matches nothing

func newRanker(p *profile.Profile) *ranker {
	r := &ranker{p: p, fam: newFamilies(p)}
	for _, m := range p.Search.Models {
		tr := tierRule{m: m, make: r.fam.canonMake(m.Make)}
		if strings.TrimSpace(m.Model) != "" {
			tr.base = noFamily
			if f, _, ok := r.fam.Family(m.Make, m.Model, ""); ok {
				tr.base = r.fam.Base(f)
			}
		}
		r.rules = append(r.rules, tr)
	}
	return r
}

// rankCar is one car's ranking input (summary + what the summary does not carry) and derived values.
type rankCar struct {
	c          *api.CarSummary
	seats      *int
	facts      map[string]string
	redFlags   []string
	hasVIN     bool
	priceFlags []string // CarSummary.PriceFlags: the price listing was forced past the price sanity check
	createdT   float64

	text   carText
	meta   *tierRule // search.models entry for base_fit / model risk
	fam    string    // base family, "" = unmapped
	trim   string    // power band + awd/2wd
	landed *landedCost
}

// --- car text ----------------------------------------------------------------------

type carText struct {
	plain, split []string // folded words of model + variant; split also breaks digit/letter runs ("85x" → "85 x")
	awd          bool
	hps          []int // power_kw as hp, then a figure in the text
}

// awdWords mark all-wheel drive in model/variant text.
var awdWords = [][]string{{"awd"}, {"4wd"}, {"4x4"}, {"quattro"}, {"4motion"}, {"allrad"}, {"xdrive"}, {"4matic"}, {"all4"},
	{"dual", "motor"}, {"dualmotor"}}

func splitDigits(s string) string {
	var b strings.Builder
	var prev rune
	for i, r := range s {
		if i > 0 && prev != ' ' && r != ' ' && unicode.IsDigit(prev) != unicode.IsDigit(r) {
			b.WriteByte(' ')
		}
		b.WriteRune(r)
		prev = r
	}
	return b.String()
}

func newCarText(c *api.CarSummary) carText {
	text := optStr(c.Model) + " " + optStr(c.Variant)
	f := geo.FoldWords(text)
	t := carText{plain: strings.Fields(f), split: strings.Fields(splitDigits(f))}
	t.awd = strings.EqualFold(optStr(c.Drive), "awd") || slices.ContainsFunc(awdWords, func(w []string) bool { return seqAt(t.plain, w, false) })
	if c.PowerKw != nil {
		t.hps = append(t.hps, api.Horsepower(*c.PowerKw))
	}
	if hp := textHorsepower(text); hp != nil {
		t.hps = append(t.hps, *hp)
	}
	return t
}

// has reports whether a word or phrase occurs in the text (either tokenization).
func (t carText) has(phrase string) bool {
	f := strings.Fields(geo.FoldWords(phrase))
	if len(f) == 0 {
		return false
	}
	return seqAt(t.plain, f, false) || seqAt(t.split, strings.Fields(splitDigits(strings.Join(f, " "))), false)
}

func (t carText) hasAny(phrases []string) bool { return slices.ContainsFunc(phrases, t.has) }

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

// --- tiers -------------------------------------------------------------------------

// familyMatch: the entry names the car's (base) family, or the car's make when the entry has no model.
func (r *ranker) familyMatch(tr *tierRule, c *api.CarSummary) bool {
	if tr.base != "" {
		return c.ModelFamily != nil && r.fam.Base(*c.ModelFamily) == tr.base
	}
	mk := ""
	if c.ModelFamily != nil {
		_, mk, _ = r.fam.Canonical(*c.ModelFamily)
	}
	if mk == "" {
		mk = r.fam.canonMake(optStr(c.Make))
	}
	return mk != "" && normFamilyText(mk) == normFamilyText(tr.make)
}

func inRange(v float64, rng []float64) bool { return len(rng) == 2 && v >= rng[0] && v <= rng[1] }

// when evaluates a search.models condition (see profile.When for the unknown-value rules).
func when(w *profile.When, c *api.CarSummary, t carText) bool {
	if w == nil {
		return true
	}
	if t.hasAny(w.VariantNone) {
		return false
	}
	if len(w.Drive) > 0 {
		d := strings.ToLower(optStr(c.Drive))
		if t.awd {
			d = "awd"
		}
		if d != "" && d != "unknown" && !slices.Contains(w.Drive, d) {
			return false
		}
	}
	if f := carFuel(c); len(w.Fuel) > 0 && f != "" && !slices.Contains(w.Fuel, f) {
		return false
	}
	if c.Year != nil && ((w.YearMin > 0 && *c.Year < w.YearMin) || (w.YearMax > 0 && *c.Year > w.YearMax)) {
		return false
	}
	marker := len(w.VariantAny) > 0 && t.hasAny(w.VariantAny)
	unknownOK := len(w.VariantAny) == 0 || marker
	if w.PowerHP != nil {
		if len(t.hps) > 0 {
			if !slices.ContainsFunc(t.hps, func(hp int) bool { return inRange(float64(hp), w.PowerHP) }) {
				return false
			}
		} else if !unknownOK {
			return false
		}
	}
	if w.BatteryNetKwh != nil {
		if c.Powertrain != nil && c.Powertrain.BatteryNetKwh != nil {
			if !inRange(*c.Powertrain.BatteryNetKwh, w.BatteryNetKwh) {
				return false
			}
		} else if !unknownOK {
			return false
		}
	}
	if w.PowerHP == nil && w.BatteryNetKwh == nil && !unknownOK {
		return false
	}
	return true
}

// tierOf: the first search.models entry whose family and `when` match gives the tier, else default_tier. meta is
// that entry, else the first entry of the car's family (for base_fit and model risk).
func (r *ranker) tierOf(c *api.CarSummary) (tier int, meta *tierRule) {
	t := newCarText(c)
	for i := range r.rules {
		tr := &r.rules[i]
		if !r.familyMatch(tr, c) {
			continue
		}
		if meta == nil {
			meta = tr
		}
		if when(tr.m.When, c, t) {
			return tr.m.Tier, tr
		}
	}
	return r.p.Search.DefaultTier, meta
}

// --- location ----------------------------------------------------------------------

// locate fills the read-only location fields: market (vs owner.home.country) and, without a stored distance, the
// great-circle estimate from lat/lon × road_factor.
func (r *ranker) locate(s *api.CarSpecs) {
	h := r.p.Owner.Home
	s.Market = MarketOf(s.Country, h.Country)
	src := "stored"
	switch {
	case s.DistanceKm != nil:
	case s.Lat != nil && s.Lon != nil && h.Located():
		d := int(math.Round(geo.GreatCircleKm(geo.Point{Lat: *h.Lat, Lon: *h.Lon}, geo.Point{Lat: *s.Lat, Lon: *s.Lon}) * r.p.Search.RoadFactor))
		s.DistanceKm, src = &d, "estimate"
	default:
		return
	}
	s.DistanceSource = &src
}

// --- hard filters ------------------------------------------------------------------

var queueClosedStatuses = []string{"closed", "dropped", "bought"}

// ratedBy reports whether user ("" = owner) has a verdict on the car. Summaries are built for that user, so
// Verdict is theirs.
func ratedBy(c *api.CarSummary, user string) bool {
	if user != "" && c.Verdicts != nil {
		return c.VerdictOf(user) != nil
	}
	return c.Verdict != nil
}

func carFuel(c *api.CarSummary) string {
	if c.Powertrain != nil && c.Powertrain.Fuel != nil && *c.Powertrain.Fuel != "unknown" {
		return strings.ToLower(*c.Powertrain.Fuel)
	}
	return ""
}

func fptr(v float64) *float64 { return &v }

func ifptr(p *int) *float64 {
	if p == nil {
		return nil
	}
	return fptr(float64(*p))
}

// fieldValue reads a profile.NumericFields field (nil = unknown).
func (rc *rankCar) fieldValue(field string) *float64 {
	c := rc.c
	pt := c.Powertrain
	if pt == nil {
		pt = &api.Powertrain{}
	}
	f, _ := profile.CanonicalField(field)
	switch f {
	case "year":
		return ifptr(c.Year)
	case "km":
		return ifptr(c.Km)
	case "price":
		return ifptr(c.Price)
	case "power_kw":
		return c.PowerKw
	case "power_hp":
		if c.PowerKw == nil {
			return nil
		}
		return fptr(float64(api.Horsepower(*c.PowerKw)))
	case "wheels_in":
		return ifptr(c.WheelsIn)
	case "seats":
		return ifptr(rc.seats)
	case "distance_km":
		return ifptr(c.DistanceKm)
	case "powertrain.battery_net_kwh":
		return pt.BatteryNetKwh
	case "powertrain.battery_gross_kwh":
		return pt.BatteryGrossKwh
	case "powertrain.engine_cc":
		return ifptr(pt.EngineCc)
	case "powertrain.wltp_range_km":
		return ifptr(pt.WltpRangeKm)
	case "powertrain.wltp_consumption":
		return pt.WltpConsumption
	case "powertrain.co2_g_km":
		return ifptr(pt.Co2GKm)
	}
	return nil
}

var reNumber = regexp.MustCompile(`-?\d+(?:[.,]\d+)?`)

// factNumber reads the first number in a fact value ("77 kWh" → 77).
func factNumber(v string) *float64 {
	m := reNumber.FindString(v)
	if m == "" {
		return nil
	}
	f, err := strconv.ParseFloat(strings.Replace(m, ",", ".", 1), 64)
	if err != nil {
		return nil
	}
	return &f
}

// falsyWords open a fact value that says "no".
var falsyWords = []string{"no", "none", "false", "0", "n", "nao", "nein", "non", "nessuno", "ninguno", "nenhum", "keine", "kein", "aucun", "unknown"}

// truthy: a non-empty fact value not opening with a "no" word.
func truthy(v string) bool {
	f := strings.Fields(geo.FoldWords(v))
	return len(f) > 0 && !slices.Contains(falsyWords, f[0])
}

func outOfRange(v *float64, lo, hi *float64) bool {
	return v != nil && ((lo != nil && *v < *lo) || (hi != nil && *v > *hi))
}

// hardFilterHit reports whether one search.hard_filters rule excludes the car.
func (rc *rankCar) hardFilterHit(f profile.HardFilter) bool {
	switch {
	case f.Field != "":
		return outOfRange(rc.fieldValue(f.Field), f.Min, f.Max)
	case f.Flag != "":
		return truthy(rc.facts[f.Flag]) || slices.Contains(rc.priceFlags, f.Flag)
	}
	for _, k := range f.FactKeys() {
		v, ok := rc.facts[k]
		if !ok {
			continue
		}
		switch {
		case f.Min != nil || f.Max != nil:
			if outOfRange(factNumber(v), f.Min, f.Max) {
				return true
			}
		case len(f.Words) > 0:
			fv := geo.FoldWords(v)
			if slices.ContainsFunc(f.Words, func(w string) bool { return geo.HasPhrase(fv, geo.FoldWords(w)) }) {
				return true
			}
		case len(f.MentionsCountry) > 0:
			if geo.MentionedCountry(v, f.MentionsCountry) != "" {
				return true
			}
		default:
			if truthy(v) {
				return true
			}
		}
	}
	return false
}

// scopeExclusion: why the profile's search scope excludes the car ("" = in scope). A missing value passes.
// withPriceMax=false skips the price cap (the comparable pool keeps dearer cars).
func (r *ranker) scopeExclusion(rc *rankCar, withPriceMax bool) string {
	c, s := rc.c, r.p.Search
	switch {
	case s.YearMin > 0 && c.Year != nil && *c.Year < s.YearMin:
		return fmt.Sprintf("year < %d", s.YearMin)
	case withPriceMax && s.Price.MaxEUR > 0 && c.Price != nil && *c.Price > s.Price.MaxEUR:
		return fmt.Sprintf("price > %d", s.Price.MaxEUR)
	case s.KmMax > 0 && c.Km != nil && *c.Km > s.KmMax:
		return fmt.Sprintf("km > %d", s.KmMax)
	case len(s.Countries) > 0 && optStr(c.Country) != "" && !slices.Contains(s.Countries, strings.ToUpper(*c.Country)):
		return "country " + *c.Country
	}
	if reg := geo.RegionOf(optStr(c.Country), optStr(c.City), s.ExcludeRegions); reg != "" {
		return "region " + reg
	}
	if city := geo.FoldWords(optStr(c.City)); city != "" {
		for _, pl := range s.ExcludePlaces {
			if geo.HasPhrase(city, geo.FoldWords(pl)) {
				return "place " + pl
			}
		}
	}
	if f := carFuel(c); len(s.Powertrain) > 0 && f != "" && !slices.Contains(s.Powertrain, f) {
		return "fuel " + f
	}
	for _, f := range s.HardFilters {
		if rc.hardFilterHit(f) {
			if f.Label != "" {
				return f.Label
			}
			return f.Line()
		}
	}
	return ""
}

// exclusion: why the car is not in user's queue ("" = eligible).
func (r *ranker) exclusion(rc *rankCar, user string) string {
	c := rc.c
	switch {
	case ratedBy(c, user):
		return "rated"
	case slices.Contains(queueClosedStatuses, c.Status):
		return "status " + c.Status
	case c.LiveListingCount == 0:
		return "no live listing"
	}
	return r.scopeExclusion(rc, true)
}

// --- landed cost -------------------------------------------------------------------

type landedCost struct {
	total     int
	distKm    float64
	distGuess bool // no car distance: default_distance_km / country centroid / fallback
	vat       bool // VAT reserve included
}

// fallbackDistanceKm: abroad car with no distance, no configured default and no centroid estimate.
const fallbackDistanceKm = 2500

// distanceGuess: default_distance_km[country] → great-circle(home, country centroid) × road_factor → default
// "other" → 0 at home / fallback abroad.
func (r *ranker) distanceGuess(country string, abroad bool) float64 {
	lc, h := r.p.Search.Ranking.LandedCost, r.p.Owner.Home
	if country == "" {
		country = h.Country
	}
	if d, ok := lc.DefaultDistanceKm[country]; ok {
		return float64(d)
	}
	if pt, ok := geo.Centroids[country]; ok && h.Located() {
		return geo.GreatCircleKm(geo.Point{Lat: *h.Lat, Lon: *h.Lon}, pt) * r.p.Search.RoadFactor
	}
	if d, ok := lc.DefaultDistanceKm["other"]; ok {
		return float64(d)
	}
	if abroad {
		return fallbackDistanceKm
	}
	return 0
}

// recentReg: reg_date within months of now (month precision for YYYY-MM; YYYY alone is never recent).
func recentReg(reg *string, now time.Time, months int) bool {
	if reg == nil || months <= 0 || len(*reg) < 7 {
		return false
	}
	cut := now.AddDate(0, -months, 0)
	if len(*reg) >= 10 {
		return (*reg)[:10] >= cut.Format("2006-01-02")
	}
	return (*reg)[:7] >= cut.Format("2006-01")
}

// landedOf: price + trip + registration + VAT reserve (nil without a price; the price alone without a home country).
// An unknown car country counts as the home market.
func (r *ranker) landedOf(c *api.CarSummary, now time.Time) *landedCost {
	if c.Price == nil {
		return nil
	}
	price := float64(*c.Price)
	home := r.p.Owner.Home.Country
	if home == "" {
		return &landedCost{total: *c.Price}
	}
	lc, vr := r.p.Search.Ranking.LandedCost, r.p.Search.Ranking.VATReserve
	abroad := optStr(c.Country) != "" && !r.p.HomeMarket(*c.Country)
	out := &landedCost{}
	if c.DistanceKm != nil {
		out.distKm = float64(*c.DistanceKm)
	} else {
		out.distKm, out.distGuess = r.distanceGuess(strings.ToUpper(optStr(c.Country)), abroad), true
	}
	d := out.distKm
	cost := price
	if abroad {
		a := lc.Abroad
		nights := 0
		if d > a.NightFreeKm {
			nights = min(a.MaxNights, int(math.Ceil(d/a.KmPerNight)))
		}
		cost += profile.Step(a.Travel, d) + a.Fixed + (a.EnergyPerKm+a.TollsPerKm)*d + a.NightCost*float64(nights) + profile.Step(a.Food, d)
		cost += lc.RegistrationAbrd
		if vr.On() && ((c.Km != nil && *c.Km <= vr.KmMax) || recentReg(c.RegDate, now, vr.MonthsMax)) {
			cost += price * *vr.Pct / 100
			out.vat = true
		}
	} else {
		cost += profile.Step(lc.HomeTrip, d) + lc.RegistrationHome
	}
	out.total = int(math.Round(cost))
	return out
}

// --- peers -------------------------------------------------------------------------

func (r *ranker) kmBand(km *int) int {
	if km == nil {
		return -1
	}
	for i, b := range r.p.Search.Ranking.Peers.KmBands {
		if *km < b {
			return i
		}
	}
	return len(r.p.Search.Ranking.Peers.KmBands)
}

func (r *ranker) kmBandLabel(b int) string {
	bands := r.p.Search.Ranking.Peers.KmBands
	k := func(n int) string { return strconv.Itoa(n/1000) + "k" }
	switch {
	case b < 0:
		return "? km"
	case len(bands) == 0:
		return "any km"
	case b == 0:
		return "<" + k(bands[0]) + " km"
	case b == len(bands):
		return "≥" + k(bands[b-1]) + " km"
	}
	return strconv.Itoa(bands[b-1]/1000) + "–" + k(bands[b]) + " km"
}

// trimOf: power rounded to peers.power_band_hp + awd/2wd ("~275 hp 2wd"; "? hp" when power is unknown).
func (r *ranker) trimOf(t carText) string {
	drive := "2wd"
	if t.awd {
		drive = "awd"
	}
	if len(t.hps) == 0 {
		return "? hp " + drive
	}
	b := r.p.Search.Ranking.Peers.PowerBandHP
	return fmt.Sprintf("~%d hp %s", int(math.Round(float64(t.hps[0])/b)*b), drive)
}

// pool: the comparable asks — live, priced, price not forced past sanity, in scope (price cap aside), no VAT
// reserve, not closed/dropped, mapped family — minus outliers (outside outlier_low…outlier_high × median within a family+trim band of ≥ outlier_min_n).
func (r *ranker) pool(cars []*rankCar) []*rankCar {
	var in []*rankCar
	for _, rc := range cars {
		c := rc.c
		if c.LiveListingCount == 0 || rc.landed == nil || rc.landed.vat || len(rc.priceFlags) > 0 || rc.fam == "" || c.Status == "closed" || c.Status == "dropped" {
			continue
		}
		if r.scopeExclusion(rc, false) != "" {
			continue
		}
		in = append(in, rc)
	}
	pe := r.p.Search.Ranking.Peers
	bands := map[string][]*rankCar{}
	for _, rc := range in {
		bands[rc.fam+"|"+rc.trim] = append(bands[rc.fam+"|"+rc.trim], rc)
	}
	drop := map[*rankCar]bool{}
	for _, g := range bands {
		if len(g) < pe.OutlierMinN {
			continue
		}
		ps := make([]float64, len(g))
		for i, rc := range g {
			ps[i] = float64(*rc.c.Price)
		}
		med := median(ps)
		for _, rc := range g {
			if p := float64(*rc.c.Price); p < med*pe.OutlierLow || p > med*pe.OutlierHigh {
				drop[rc] = true
			}
		}
	}
	out := in[:0:0]
	for _, rc := range in {
		if !drop[rc] {
			out = append(out, rc)
		}
	}
	return out
}

type peerSet struct {
	peers  []*rankCar
	adjust bool
	basis  string
}

// peersOf walks the ladder (family+trim+year+km band → family+trim+year → family+trim → family), each step with its
// min n; the car is never its own peer. Wider steps adjust peer prices for year and km.
func (r *ranker) peersOf(rc *rankCar, pool []*rankCar) peerSet {
	if rc.fam == "" {
		return peerSet{}
	}
	c := rc.c
	minN := r.p.Search.Ranking.Peers.MinN
	band := r.kmBand(c.Km)
	var fam, trim, year, yearKm []*rankCar
	for _, p := range pool {
		if p == rc || p.c.ID == c.ID || p.fam != rc.fam {
			continue
		}
		fam = append(fam, p)
		if p.trim != rc.trim {
			continue
		}
		trim = append(trim, p)
		if c.Year == nil || p.c.Year == nil || *p.c.Year != *c.Year {
			continue
		}
		year = append(year, p)
		if band >= 0 && r.kmBand(p.c.Km) == band {
			yearKm = append(yearKm, p)
		}
	}
	parts := func(xs ...string) string { return strings.Join(append([]string{rc.fam}, xs...), " · ") }
	yr := ""
	if c.Year != nil {
		yr = strconv.Itoa(*c.Year)
	}
	switch {
	case c.Year != nil && band >= 0 && len(yearKm) >= minN[0]:
		return peerSet{yearKm, false, parts(rc.trim, yr, r.kmBandLabel(band))}
	case c.Year != nil && len(year) >= minN[1]:
		return peerSet{year, true, parts(rc.trim, yr)}
	case len(trim) >= minN[2]:
		return peerSet{trim, true, parts(rc.trim)}
	case len(fam) >= minN[3]:
		return peerSet{fam, true, parts("all trims")}
	}
	return peerSet{}
}

func median(xs []float64) float64 {
	s := slices.Clone(xs)
	sort.Float64s(s)
	n := len(s)
	if n == 0 {
		return 0
	}
	if n%2 == 1 {
		return s[n/2]
	}
	return (s[n/2-1] + s[n/2]) / 2
}

func round50(x float64) int { return int(math.Round(x/50)) * 50 }

// medianOfCountryMedians: each country one vote.
func medianOfCountryMedians(byCountry map[string][]float64) float64 {
	var meds []float64
	for _, v := range byCountry {
		meds = append(meds, median(v))
	}
	return median(meds)
}

type fairPrice struct {
	fair, fairLanded int
	n                int
	basis            string
	iqr              [2]int // 25th / 75th percentile of peers' landed
}

func (r *ranker) fairOf(rc *rankCar, ps peerSet) *fairPrice {
	if len(ps.peers) == 0 {
		return nil
	}
	pe := r.p.Search.Ranking.Peers
	c := rc.c
	prices, landed := map[string][]float64{}, map[string][]float64{}
	var all []float64
	for _, p := range ps.peers {
		adj := 0.0
		if ps.adjust {
			if c.Year != nil && p.c.Year != nil {
				adj += float64(*c.Year-*p.c.Year) * pe.YearEUR
			}
			if c.Km != nil && p.c.Km != nil {
				adj += float64(*p.c.Km-*c.Km) * pe.KmEUR
			}
		}
		k := strings.ToUpper(optStr(p.c.Country))
		prices[k] = append(prices[k], float64(*p.c.Price)+adj)
		l := float64(p.landed.total) + adj
		landed[k] = append(landed[k], l)
		all = append(all, l)
	}
	sort.Float64s(all)
	q := func(f float64) int { return round50(all[int(float64(len(all)-1)*f)]) }
	return &fairPrice{fair: round50(medianOfCountryMedians(prices)), fairLanded: round50(medianOfCountryMedians(landed)),
		n: len(ps.peers), basis: ps.basis, iqr: [2]int{q(0.25), q(0.75)}}
}

// --- fit / risk / score ------------------------------------------------------------

type riskItem struct {
	label  string
	points float64
}

type rankResult struct {
	score, value *float64
	fit, risk    float64
	reasons      []string
	fair         *fairPrice
	gap          *float64
	trimScore    float64
	trimSource   string
}

func round(x float64, decimals int) float64 {
	p := math.Pow(10, float64(decimals))
	return math.Round(x*p) / p
}

// factPresent: any of the keys has a non-empty value.
func (rc *rankCar) factPresent(keys ...string) bool {
	return slices.ContainsFunc(keys, func(k string) bool { return strings.TrimSpace(rc.facts[k]) != "" })
}

var (
	serviceKeys  = []string{"service_history", "service"}
	accidentKeys = []string{"accidents", "accident_free", "accident"}
)

// accidentFree: accident_free says yes, or accidents/accident says no/none/0.
func (rc *rankCar) accidentFree() bool {
	if truthy(rc.facts["accident_free"]) {
		return true
	}
	for _, k := range []string{"accidents", "accident"} {
		if v := strings.TrimSpace(rc.facts[k]); v != "" && !truthy(v) && !strings.HasPrefix(geo.FoldWords(v), "unknown") {
			return true
		}
	}
	return false
}

// penaltyHit returns the value of a penalty's field when the penalty applies.
func (rc *rankCar) penaltyHit(pn profile.Penalty) (float64, bool) {
	v := rc.fieldValue(pn.Field)
	if v == nil || (pn.Min != nil && *v < *pn.Min) || (pn.Max != nil && *v > *pn.Max) {
		return 0, false
	}
	return *v, true
}

func (r *ranker) fitOf(rc *rankCar, now time.Time) float64 {
	s, fp := r.p.Search, r.p.Search.Ranking.Fit
	c := rc.c
	base := fp.BaseDefault
	if rc.meta != nil && rc.meta.m.BaseFit != nil {
		base = *rc.meta.m.BaseFit
	}
	terms := 0.0
	for _, k := range r.p.TopOptions() {
		w := s.OptionsWanted[k]
		switch c.Options[k] {
		case "yes":
			terms += w * fp.OptionUnit
		case "no":
			terms -= w * fp.OptionUnit
		}
	}
	for _, pn := range s.Penalties {
		if _, ok := rc.penaltyHit(pn); ok {
			terms -= pn.Weight * fp.OptionUnit
		}
	}
	switch c.SellerType {
	case "private":
		terms += fp.SellerPrivate
	case "reseller":
		terms += fp.SellerReseller
	}
	if optStr(c.Market) == "home" {
		terms += fp.HomeMarket
	}
	if c.Year != nil {
		terms += fp.AgePerYear * math.Max(0, fp.AgeYears-float64(now.Year()-*c.Year))
	}
	if c.Km != nil && fp.KmRef > 0 {
		terms += fp.Km * (1 - float64(*c.Km)/float64(fp.KmRef))
	}
	if n := factNumber(rc.facts["owners"]); n != nil && *n == 1 {
		terms += fp.HistoryFact
	}
	if truthy(rc.facts["service_history"]) || truthy(rc.facts["service"]) {
		terms += fp.HistoryFact
	}
	if rc.accidentFree() {
		terms += fp.HistoryFact
	}
	return round(base+r.p.Weight("fit")*terms, 3)
}

// riskOptions: must_have + the top unknown_option_top options_wanted (by weight).
func (r *ranker) riskOptions() []string {
	out := slices.Clone(r.p.Search.MustHave)
	n := 0
	for _, k := range r.p.TopOptions() {
		if n >= r.p.Search.Ranking.Risk.UnknownOptionTop {
			break
		}
		n++
		if !slices.Contains(out, k) {
			out = append(out, k)
		}
	}
	return out
}

func (r *ranker) riskOf(rc *rankCar, fp *fairPrice) []riskItem {
	rk := r.p.Search.Ranking.Risk
	c := rc.c
	var items []riskItem
	add := func(points float64, label string) {
		if points != 0 {
			items = append(items, riskItem{label, points})
		}
	}
	var unknown []string
	for _, k := range r.riskOptions() {
		if v := c.Options[k]; v != "yes" && v != "no" {
			unknown = append(unknown, r.optionLabel(k))
		}
	}
	if len(unknown) > 0 {
		add(rk.UnknownOption*float64(len(unknown)), "? "+strings.Join(unknown, ", "))
	}
	if !rc.hasVIN {
		add(rk.NoVIN, "no VIN")
	}
	if !rc.factPresent(serviceKeys...) {
		add(rk.NoServiceHistory, "no service history")
	}
	if !rc.factPresent("owners") {
		add(rk.NoOwners, "no owners")
	}
	if !rc.factPresent(accidentKeys...) {
		add(rk.NoAccidents, "no accident history")
	}
	fuel := carFuel(c)
	if fuel == "" && len(r.p.Search.Powertrain) == 1 {
		fuel = r.p.Search.Powertrain[0]
	}
	if keys := rk.HealthFacts[fuel]; len(keys) > 0 && !rc.factPresent(keys...) {
		add(rk.NoHealth, "no "+keys[0])
	}
	if rc.landed != nil && rc.landed.distGuess {
		add(rk.DistanceUnknown, "distance unknown")
	}
	if c.SellerType == "reseller" {
		add(rk.Reseller, "reseller")
	}
	if rc.landed != nil && rc.landed.vat {
		add(rk.VATReserve, "VAT reserve")
	}
	n := 0
	if fp != nil {
		n = fp.n
	}
	if n < rk.ThinPeersN {
		add(rk.ThinPeers, fmt.Sprintf("thin peers (n=%d)", n))
	}
	if fp != nil && fp.fairLanded > 0 && float64(fp.iqr[1]-fp.iqr[0])/float64(fp.fairLanded) > rk.SpreadMax {
		add(rk.Spread, "wide price spread")
	}
	if rc.meta != nil {
		add(rc.meta.m.Risk, "model risk")
	}
	for _, f := range rc.redFlags {
		add(rk.RedFlag, "red flag: "+f)
	}
	if len(rc.priceFlags) > 0 {
		add(rk.PriceForced, "price forced ("+strings.Join(rc.priceFlags, ", ")+")")
	}
	return items
}

// trimScoreOf: the numeric trim_score fact if present, else Σ options_wanted (yes +w, no −w) − penalties hit.
func (r *ranker) trimScoreOf(rc *rankCar) (float64, string) {
	if v, ok := rc.facts["trim_score"]; ok {
		if f, err := strconv.ParseFloat(strings.Replace(strings.TrimSpace(v), ",", ".", 1), 64); err == nil && !math.IsNaN(f) && !math.IsInf(f, 0) {
			return f, "fact"
		}
	}
	s := 0.0
	for _, k := range r.p.TopOptions() {
		w := r.p.Search.OptionsWanted[k]
		switch rc.c.Options[k] {
		case "yes":
			s += w
		case "no":
			s -= w
		}
	}
	for _, pn := range r.p.Search.Penalties {
		if _, ok := rc.penaltyHit(pn); ok {
			s -= pn.Weight
		}
	}
	return round(s, 1), "options"
}

// valueOfGap: 50 + 2·clamp(gap %, −15, 20) → 20…90.
func valueOfGap(g float64) float64 { return round(50+2*math.Max(-15, math.Min(20, g)), 2) }

// rank computes the value model for one car against the pool.
func (r *ranker) rank(rc *rankCar, pool []*rankCar, now time.Time) *rankResult {
	res := &rankResult{fair: r.fairOf(rc, r.peersOf(rc, pool))}
	if rc.landed != nil {
		v := 50.0
		if fp := res.fair; fp != nil && fp.fairLanded > 0 {
			g := round(float64(fp.fairLanded-rc.landed.total)/float64(fp.fairLanded)*100, 1)
			res.gap = &g
			v = valueOfGap(g)
		}
		res.value = fptr(v)
	}
	res.fit = r.fitOf(rc, now)
	items := r.riskOf(rc, res.fair)
	for _, it := range items {
		res.risk += it.points
	}
	res.risk = round(res.risk, 2)
	sort.SliceStable(items, func(i, j int) bool { return items[i].points > items[j].points })
	for i, it := range items {
		if i >= r.p.Search.Ranking.Risk.ReasonsMax {
			break
		}
		res.reasons = append(res.reasons, fmt.Sprintf("%s +%s", it.label, strconv.FormatFloat(round(it.points, 2), 'f', -1, 64)))
	}
	if res.value != nil {
		res.score = fptr(round(r.p.Weight("value")**res.value*res.fit-r.p.Weight("risk")*res.risk, 2))
	}
	res.trimScore, res.trimSource = r.trimScoreOf(rc)
	return res
}

// prepare derives tier, family, trim and landed cost for every car (sets c.Tier).
func (r *ranker) prepare(cars []*rankCar, now time.Time) {
	for _, rc := range cars {
		c := rc.c
		rc.text = newCarText(c)
		c.Tier, rc.meta = r.tierOf(c)
		rc.fam = ""
		if c.ModelFamily != nil {
			rc.fam = r.fam.Base(*c.ModelFamily)
		}
		rc.trim = r.trimOf(rc.text)
		rc.landed = r.landedOf(c, now)
	}
}

// --- why line ----------------------------------------------------------------------

const maxWhy = 160

// builtinOptionLabels: short labels for the built-in option keys (search.option_labels overrides).
var builtinOptionLabels = map[string]string{
	"electric_seats": "e-seats", "power_tailgate": "tailgate", "pano": "pano", "pano_opening": "opening pano",
	"memory_seats": "memory", "heated_seats": "heated seats", "ventilated_seats": "vented seats", "premium_audio": "audio",
	"hud": "HUD", "camera_360": "360 cam", "adaptive_cruise": "ACC", "heat_pump": "heat pump", "towbar": "towbar",
	"matrix_led": "matrix LED", "keyless": "keyless", "massage_seats": "massage", "rear_recline": "rear recline",
	"air_suspension": "air suspension", "adaptive_dampers": "adaptive dampers",
}

func (r *ranker) optionLabel(k string) string {
	if l := r.p.Search.OptionLabels[k]; l != "" {
		return l
	}
	if l := builtinOptionLabels[k]; l != "" {
		return l
	}
	return strings.ReplaceAll(k, "_", " ")
}

func penaltyLabel(pn profile.Penalty, v float64) string {
	val := strconv.FormatFloat(v, 'f', -1, 64)
	if pn.Label == "" {
		return pn.Field + " " + val
	}
	return strings.ReplaceAll(pn.Label, "{v}", val)
}

// why: a good deal shows its note; otherwise wanted options known yes/no (by weight), penalties hit, the gap vs
// peers, then unknown must-haves and missing core fields.
func (r *ranker) why(rc *rankCar, res *rankResult) string {
	c := rc.c
	if c.GoodDeal {
		if n := strings.TrimSpace(optStr(c.GoodDealNote)); n != "" {
			return clipRunes(n, maxWhy)
		}
		return "good deal"
	}
	var parts []string
	for _, k := range r.p.TopOptions() {
		switch c.Options[k] {
		case "yes":
			parts = append(parts, "✓ "+r.optionLabel(k))
		case "no":
			parts = append(parts, "✗ "+r.optionLabel(k))
		}
	}
	for _, pn := range r.p.Search.Penalties {
		if v, ok := rc.penaltyHit(pn); ok {
			parts = append(parts, "✗ "+penaltyLabel(pn, v))
		}
	}
	if res.gap != nil && res.fair != nil {
		basis := res.fair.basis
		if _, mk, ok := r.fam.Canonical(rc.fam); ok {
			basis = strings.TrimPrefix(basis, mk+" ")
		}
		parts = append(parts, fmt.Sprintf("%s %% vs %s (n=%d)", signedPct(-*res.gap), basis, res.fair.n))
	}
	var unknown []string
	for _, k := range r.p.Search.MustHave {
		if v := c.Options[k]; v != "yes" && v != "no" {
			unknown = append(unknown, "? "+r.optionLabel(k))
		}
	}
	for _, u := range []struct {
		label   string
		missing bool
	}{
		{"power", len(rc.text.hps) == 0}, {"year", c.Year == nil}, {"km", c.Km == nil}, {"price", c.Price == nil},
		{"country", optStr(c.Country) == ""},
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
