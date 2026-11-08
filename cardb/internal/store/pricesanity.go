package store

import (
	"database/sql"
	"fmt"
	"math"
	"regexp"
	"strings"

	"carhunt/cardb/internal/api"
)

// Price sanity on write. A price that looks ×100 (cents), like a monthly/lease rate, or net of VAT is refused
// (422 with a reason) unless the writer sends force; a forced price is stored with price_flags on the listing and a
// price_sanity_override event.
// Bounds come from the profile (search.price.min_eur / cap_eur / max_eur); nothing buyer-specific lives here.

const (
	defaultPriceMinEUR = 1500      // below this a "price" is a monthly rate or a deposit, not a car
	defaultPriceCapEUR = 2_000_000 // above this nothing on a used-car portal is real
	x100Factor         = 8         // price > 8× the family median (or 8× search.price.max_eur) → ×100 mistake
	leaseLowFactor     = 4         // lease wording counts when price < median/4 (or < 10× min without a median)
)

var (
	// A per-month rate: "/mês", "€/mes", "per month", "mensal", "monatlich", "mtl.", "par mois", "al mese", …
	reMonthly = regexp.MustCompile(`(?i)(/\s*(mês|mes|month|mon|monat|mois|mese|maand|mnd|mo)\b|\bper\s+(month|maand)\b|\bpor\s+m[eê]s\b|\bal\s+mese\b|\bpar\s+mois\b|\bpro\s+monat\b|\bmensa(l|lidade|lmente)\b|\bmensual(es)?\b|\bmonatlich\b|\bmtl\b|\bmensuel(le)?\b|\bmensile\b|\bmaandelijks\b|\bmonthly\b)`)
	// A lease product rather than a sale.
	reLease = regexp.MustCompile(`(?i)\b(leasing|lease|renting|loa|lld|noleggio|aluguer|privatleasing)\b`)
	// Net-of-VAT wording.
	reNet   = regexp.MustCompile(`(?i)(\bexcl\.?\s*(vat|btw|iva|mwst|tva)\b|\bex\.?\s*vat\b|\bplus\s+vat\b|\+\s*(iva|vat|btw|mwst|tva)\b|\bzzgl\.?\s*(mwst|ust)\b|\bexkl\.?\s*(mwst|ust)\b|\bnetto\b|\bnet\s+(price|of\s+vat)\b|\bprix\s+ht\b|\bhors\s+taxes?\b|\bsin\s+iva\b|\bsem\s+iva\b|\biva\s+(não|nao)\s+inclu[ií]d[oa]\b|\biva\s+no\s+inclu[ií]d[oa]\b|\biva\s+esclusa\b|\bescluso\s+iva\b)`)
	reNetHT = regexp.MustCompile(`(^|[\s\d€.,(])HT($|[\s.,)])`) // French "hors taxes", upper case only
	// Gross wording wins over net wording ("Brutto 30 000 / Netto 25 210").
	reGross = regexp.MustCompile(`(?i)(\bbrutto\b|\bincl\.?\s*(vat|btw|iva|mwst|tva)\b|\binkl\.?\s*(mwst|ust)\b|\biva\s+inclu[ií]d[oa]\b|\biva\s+incluso\b|\bttc\b|\bmwst\.?\s*ausweisbar\b|\biva\s+dedut[ií]vel\b|\biva\s+deducible\b|\bvat\s+deductible\b|\bcon\s+iva\b|\bcom\s+iva\b)`)
)

// priceGate is one price write to check.
type priceGate struct {
	Price   *int
	Current *int    // the listing's stored price; re-sending it is not re-checked (replays stay idempotent)
	Title   string  // listing title
	Note    string  // price note
	Vat     string  // effective price_vat
	Family  *string // model family of the car, for the median
	CarID   int64   // excluded from the median (0 = new car)
	Force   bool
}

// priceVerdict: Checked = Price was examined (store Flags on the listing); Flags = failed reasons (forced).
type priceVerdict struct {
	Checked bool
	Price   int
	Flags   []string
}

type priceProblem struct {
	reason, msg, expected string
}

// checkPrice returns the verdict, or a 422 (reason/price/expected details) when the price fails and force is off.
func (s *Store) checkPrice(tx *sql.Tx, g priceGate) (priceVerdict, error) {
	if g.Price == nil || (g.Current != nil && *g.Current == *g.Price) {
		return priceVerdict{}, nil
	}
	probs, err := s.priceProblems(tx, g)
	if err != nil {
		return priceVerdict{}, err
	}
	v := priceVerdict{Checked: true, Price: *g.Price, Flags: []string{}}
	for _, p := range probs {
		v.Flags = append(v.Flags, p.reason)
	}
	if len(probs) > 0 && !g.Force {
		p := probs[0]
		return v, &Error{Kind: KindInvalid,
			Msg:     fmt.Sprintf("price rejected (%s): %s; resend with force: true to store it flagged", p.reason, p.msg),
			Details: map[string]any{"reason": p.reason, "price": *g.Price, "expected": p.expected}}
	}
	return v, nil
}

func (s *Store) priceBounds() (minEUR, capEUR, maxEUR int) {
	minEUR, capEUR = defaultPriceMinEUR, defaultPriceCapEUR
	if p := s.Profile(); p != nil {
		if p.Search.Price.MinEUR > 0 {
			minEUR = p.Search.Price.MinEUR
		}
		if p.Search.Price.CapEUR > 0 {
			capEUR = p.Search.Price.CapEUR
		}
		maxEUR = p.Search.Price.MaxEUR
	}
	return
}

// priceProblems lists every failed check, most severe first: range, x100, lease, net.
func (s *Store) priceProblems(tx *sql.Tx, g priceGate) ([]priceProblem, error) {
	price := *g.Price
	minEUR, capEUR, maxEUR := s.priceBounds()
	eur := func(n int) string { return fmtThousands(int64(n)) + " €" }
	var out []priceProblem
	if price <= 0 {
		return []priceProblem{{"price_range", fmt.Sprintf("price %s is not positive", eur(price)),
			fmt.Sprintf("1 … %s", eur(capEUR))}}, nil
	}
	if price > capEUR {
		if d := price / 100; d >= minEUR && d <= capEUR {
			out = append(out, priceProblem{"price_x100",
				fmt.Sprintf("price %s is above the cap %s while %s (÷100) is plausible — cents instead of euros?", eur(price), eur(capEUR), eur(d)),
				fmt.Sprintf("≤ %s; maybe %s", eur(capEUR), eur(d))})
		} else {
			return []priceProblem{{"price_range", fmt.Sprintf("price %s is above the cap %s", eur(price), eur(capEUR)),
				fmt.Sprintf("1 … %s", eur(capEUR))}}, nil
		}
	}
	median, n := 0, 0
	if g.Family != nil {
		var err error
		if median, n, err = familyMedian(tx, s.rk.fam, *g.Family, g.CarID); err != nil {
			return nil, err
		}
	}
	if len(out) == 0 {
		switch {
		case n >= fairMinN && price > x100Factor*median:
			out = append(out, priceProblem{"price_x100",
				fmt.Sprintf("price %s is more than %d× the %s median %s (n=%d) — cents instead of euros?", eur(price), x100Factor, *g.Family, eur(median), n),
				fmt.Sprintf("fair %s (%s, n=%d)", fmtThousands(int64(median)), *g.Family, n)})
		case n < fairMinN && maxEUR > 0 && price > x100Factor*maxEUR:
			out = append(out, priceProblem{"price_x100",
				fmt.Sprintf("price %s is more than %d× search.price.max_eur %s — cents instead of euros?", eur(price), x100Factor, eur(maxEUR)),
				fmt.Sprintf("≤ %s", eur(x100Factor*maxEUR))})
		}
	}
	text := g.Title + "\n" + g.Note
	low := price < 10*minEUR // no family data: "cheap" = under 10× the minimum
	if n >= fairMinN {
		low = price*leaseLowFactor < median
	}
	switch {
	case price < minEUR:
		out = append(out, priceProblem{"price_lease",
			fmt.Sprintf("price %s is below search.price.min_eur %s — a monthly/lease rate or a deposit?", eur(price), eur(minEUR)),
			fmt.Sprintf("a full purchase price ≥ %s", eur(minEUR))})
	case low && (reMonthly.MatchString(text) || reLease.MatchString(text)):
		w := reMonthly.FindString(text)
		if w == "" {
			w = reLease.FindString(text)
		}
		out = append(out, priceProblem{"price_lease",
			fmt.Sprintf("price %s with %q in the title/price note looks like a monthly/lease rate", eur(price), strings.TrimSpace(w)),
			fmt.Sprintf("a full purchase price%s", medianHint(median, n, g.Family))})
	}
	vat := g.Vat
	switch {
	case vat == "net":
		out = append(out, priceProblem{"price_net", fmt.Sprintf("price %s is net of VAT (price_vat: net); cardb stores gross prices", eur(price)),
			"the gross price incl. VAT"})
	case vat != "gross" && vat != "margin" && !reGross.MatchString(text) && (reNet.MatchString(text) || reNetHT.MatchString(text)):
		w := reNet.FindString(text)
		if w == "" {
			w = reNetHT.FindString(text)
		}
		out = append(out, priceProblem{"price_net",
			fmt.Sprintf("price %s with %q in the title/price note looks net of VAT; cardb stores gross prices", eur(price), strings.TrimSpace(w)),
			"the gross price incl. VAT (or send price_vat: gross|margin if it already is)"})
	}
	return out, nil
}

// fairMinN: cars a family median needs before it judges a price.
const fairMinN = 3

func medianHint(median, n int, fam *string) string {
	if n < fairMinN || fam == nil {
		return ""
	}
	return fmt.Sprintf(" (fair %s, %s, n=%d)", fmtThousands(int64(median)), *fam, n)
}

// familyMedian is the median price of live, unflagged listings (the lowest per car) of live cars in family,
// excluding car exclude. n = number of cars.
func familyMedian(tx *sql.Tx, fams *Families, family string, exclude int64) (med, n int, err error) {
	cars, err := loadLiveCars(tx)
	if err != nil {
		return 0, 0, err
	}
	inFamily := map[int64]bool{}
	for _, c := range cars {
		if f, _, _ := c.family(fams); f != nil && *f == family && c.ID != exclude {
			inFamily[c.ID] = true
		}
	}
	if len(inFamily) < fairMinN {
		return 0, len(inFamily), nil
	}
	var prices []int
	err = eachRow(tx, `SELECT car_id, MIN(price) FROM listings WHERE status = 'live' AND price > 0 AND price_flags = '[]'
		GROUP BY car_id`, nil, func(sc scanner) error {
		var id int64
		var p int
		if err := sc.Scan(&id, &p); err != nil {
			return err
		}
		if inFamily[id] {
			prices = append(prices, p)
		}
		return nil
	})
	if err != nil || len(prices) < fairMinN {
		return 0, len(prices), err
	}
	fs := make([]float64, len(prices))
	for i, p := range prices {
		fs[i] = float64(p)
	}
	return int(math.Round(median(fs))), len(prices), nil
}

// gateFromListing fills the gate's unset title/note/vat from a stored listing and sets the car's family.
func gateFromListing(tx *sql.Tx, fams *Families, g *priceGate, l *listingRow, carID int64) error {
	var title, note sql.NullString
	var vat string
	if err := tx.QueryRow("SELECT title, price_note, price_vat FROM listings WHERE id = ?", l.ID).Scan(&title, &note, &vat); err != nil {
		return err
	}
	if g.Title == "" {
		g.Title = title.String
	}
	if g.Note == "" {
		g.Note = note.String
	}
	if l.Price.Valid {
		cur := int(l.Price.Int64)
		g.Current = &cur
		if g.Vat != "" && g.Vat != vat && (g.Price == nil || *g.Price == cur) {
			g.Price, g.Current = &cur, nil // a changed price_vat re-checks the stored price
		}
	}
	if g.Vat == "" {
		g.Vat = vat
	}
	return gateFromCar(tx, fams, g, carID)
}

// checkUpsertPrice runs the gate for POST /listings/upsert; l = the existing listing (nil for a new one).
func (s *Store) checkUpsertPrice(tx *sql.Tx, l *listingRow, in *api.ListingUpsert, specs map[string]any) (priceVerdict, error) {
	g := priceGate{Price: in.Price, Title: strings.TrimSpace(in.Title), Note: in.PriceNote, Vat: in.PriceVat, Force: in.Force}
	switch {
	case l != nil:
		cid, err := resolveCar(tx, itoa(l.CarID))
		if err != nil {
			return priceVerdict{}, err
		}
		if err := gateFromListing(tx, s.rk.fam, &g, l, cid); err != nil {
			return priceVerdict{}, err
		}
	case in.Car != "":
		cid, err := resolveCar(tx, string(in.Car))
		if err != nil {
			return priceVerdict{}, err
		}
		if err := gateFromCar(tx, s.rk.fam, &g, cid); err != nil {
			return priceVerdict{}, err
		}
	default:
		g.Family = specsFamily(s.rk.fam, specs)
	}
	return s.checkPrice(tx, g)
}

func gateFromCar(tx *sql.Tx, fams *Families, g *priceGate, carID int64) error {
	car, err := loadCar(tx, carID)
	if err != nil {
		return err
	}
	g.Family, _, _ = car.family(fams)
	g.CarID = carID
	return nil
}

// specsFamily is the derived model family of upsert specs (nil if unmapped).
func specsFamily(fams *Families, specs map[string]any) *string {
	str := func(k string) string { v, _ := specs[k].(string); return v }
	if f, _, ok := fams.Family(str("make"), str("model"), str("variant")); ok {
		return &f
	}
	return nil
}

// applyPriceVerdict stores the listing's price flags after a checked price write; a forced bad price also gets a
// price_sanity_override event.
func applyPriceVerdict(tx *sql.Tx, v priceVerdict, carID, listingID int64, author string, at float64) error {
	if !v.Checked {
		return nil
	}
	price := v.Price
	// Flags describe the listing's current price; a backfilled older observation leaves them alone.
	if _, err := tx.Exec("UPDATE listings SET price_flags = ? WHERE id = ? AND price = ?", jsonList(v.Flags), listingID, price); err != nil {
		return err
	}
	if len(v.Flags) == 0 {
		return nil
	}
	lid := listingID
	_, err := addEvent(tx, ev{CarID: carID, ListingID: &lid, Type: "price_sanity_override", At: at, Author: author,
		Summary: fmt.Sprintf("price %s € stored past the sanity check (%s)", fmtThousands(int64(price)), strings.Join(v.Flags, ", ")),
		Data:    map[string]any{"reason": v.Flags[0], "reasons": v.Flags, "price": price, "listing_id": listingID}})
	return err
}

// normPriceVat validates price_vat ("" = not sent).
func normPriceVat(v string) (string, error) {
	if strings.TrimSpace(v) == "" {
		return "", nil
	}
	return normEnum("price_vat", v)
}
