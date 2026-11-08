package store

import (
	"context"
	"database/sql"
	"slices"
	"sort"
	"strings"

	"carhunt/cardb/internal/api"
)

// OptionFilter is one `option=key:value` filter; Value is yes|no|unknown|yes_or_unknown.
type OptionFilter struct {
	Key   string
	Value string
}

// CarFilter carries the GET /cars query.
type CarFilter struct {
	Q, Make, Model                    string
	YearMin, YearMax, KmMax           *int
	HpMin, HpMax                      *int
	Drive                             []string
	PriceMin, PriceMax, DistanceKmMax *int
	Country, SellerType, Status       []string
	Verdict                           []string
	Options                           []OptionFilter
	NeedsOwner, HasDuplicates         *bool
	GoodDeal                          *bool
	ModelFamily                       []string // canonical names or "none" (unmapped); ORed
	Tier                              []string // "1"|"2"|"3", comma lists ok; ORed
	Market                            string
	Sort, Order                       string
	Limit, Offset                     int

	tiers []int
}

var sortKeys = []string{"last_activity", "price", "km", "year", "distance_km", "created", "status", "model", "deal_rank"}

// ParseOptionFilter parses "key:value".
func ParseOptionFilter(s string) (OptionFilter, error) {
	k, v, ok := strings.Cut(s, ":")
	k, v = strings.TrimSpace(k), strings.ToLower(strings.TrimSpace(v))
	if !ok || k == "" {
		return OptionFilter{}, badRequestf("option filter %q must be key:value", s)
	}
	if !slices.Contains([]string{"yes", "no", "unknown", "yes_or_unknown"}, v) {
		return OptionFilter{}, badRequestf("option filter %q: value must be yes|no|unknown|yes_or_unknown", s)
	}
	return OptionFilter{Key: k, Value: v}, nil
}

func (f *CarFilter) validate() error {
	check := func(name string, vals, allowed []string) error {
		for _, v := range vals {
			if !slices.Contains(allowed, v) {
				return badRequestf("%s must be one of %s", name, strings.Join(allowed, "|"))
			}
		}
		return nil
	}
	if err := check("status", f.Status, api.Statuses); err != nil {
		return err
	}
	if err := check("seller_type", f.SellerType, api.SellerTypes); err != nil {
		return err
	}
	if err := check("verdict", f.Verdict, append(slices.Clone(api.VerdictValues), "none")); err != nil {
		return err
	}
	for i, v := range f.Drive {
		f.Drive[i] = strings.ToLower(strings.TrimSpace(v))
	}
	if err := check("drive", f.Drive, []string{"fwd", "rwd", "awd", "unknown"}); err != nil {
		return err
	}
	if (f.HpMin != nil && *f.HpMin < 0) || (f.HpMax != nil && *f.HpMax < 0) {
		return badRequestf("hp_min and hp_max must be non-negative")
	}
	if f.HpMin != nil && f.HpMax != nil && *f.HpMin > *f.HpMax {
		return badRequestf("hp_min must not exceed hp_max")
	}
	if f.Market != "" && f.Market != "PT" && f.Market != "abroad" {
		return badRequestf("market must be PT|abroad")
	}
	var fams []string
	for _, v := range f.ModelFamily {
		for _, p := range strings.Split(v, ",") {
			if p = strings.TrimSpace(p); p == "" {
				continue
			} else if strings.EqualFold(p, "none") {
				fams = append(fams, "none")
			} else if name, _, ok := CanonicalFamily(p); ok {
				fams = append(fams, name)
			} else {
				return badRequestf("unknown model family %q; GET /model-families", p)
			}
		}
	}
	f.ModelFamily = fams
	tiers, err := parseTiers(f.Tier, nil)
	if err != nil {
		return err
	}
	f.tiers = tiers
	if f.Sort == "" {
		f.Sort = "last_activity"
	}
	if !slices.Contains(sortKeys, f.Sort) {
		return badRequestf("sort must be one of %s", strings.Join(sortKeys, "|"))
	}
	if f.Order == "" {
		f.Order = "asc"
		if f.Sort == "last_activity" || f.Sort == "created" || f.Sort == "year" {
			f.Order = "desc"
		}
	}
	if f.Order != "asc" && f.Order != "desc" {
		return badRequestf("order must be asc|desc")
	}
	if f.Limit <= 0 {
		f.Limit = 200
	}
	if f.Limit > 1000 {
		f.Limit = 1000
	}
	if f.Offset < 0 {
		f.Offset = 0
	}
	return nil
}

type summaryRow struct {
	api.CarSummary
	haystack string
	sellerT  string
	createdT float64
	activity float64
}

// buildSummaries computes CarSummary rows for every live car.
func buildSummaries(tx *sql.Tx) ([]*summaryRow, error) {
	cars, err := loadLiveCars(tx)
	if err != nil {
		return nil, err
	}
	type sellerInfo struct {
		name, company sql.NullString
		typ           string
	}
	sellers := map[int64]sellerInfo{}
	if err := eachRow(tx, "SELECT id, name, company, type FROM sellers", nil, func(sc scanner) error {
		var id int64
		var si sellerInfo
		if err := sc.Scan(&id, &si.name, &si.company, &si.typ); err != nil {
			return err
		}
		sellers[id] = si
		return nil
	}); err != nil {
		return nil, err
	}

	type lst struct {
		priceInfo
		site, title, status string
	}
	listings := map[int64][]lst{}
	if err := eachRow(tx, `SELECT l.car_id, l.url, l.site, COALESCE(l.title, ''), l.status, l.price, l.price_note, l.last_seen_at,
		(SELECT p.price FROM price_points p WHERE p.listing_id = l.id ORDER BY p.at, p.id LIMIT 1),
		(SELECT COUNT(*) FROM price_points p WHERE p.listing_id = l.id)
		FROM listings l ORDER BY l.first_seen_at, l.id`, nil, func(sc scanner) error {
		var carID int64
		var l lst
		var price, first sql.NullInt64
		var note sql.NullString
		if err := sc.Scan(&carID, &l.URL, &l.site, &l.title, &l.status, &price, &note, &l.LastSeen, &first, &l.Points); err != nil {
			return err
		}
		l.Live, l.Price, l.Note, l.FirstPrice = l.status == "live", intPtr(price), strPtr(note), intPtr(first)
		listings[carID] = append(listings[carID], l)
		return nil
	}); err != nil {
		return nil, err
	}

	type photoAgg struct {
		count int
		cover *int64
	}
	photos := map[int64]*photoAgg{}
	if err := eachRow(tx, "SELECT car_id, id FROM photos ORDER BY car_id, cover DESC, position, id", nil, func(sc scanner) error {
		var carID, id int64
		if err := sc.Scan(&carID, &id); err != nil {
			return err
		}
		pa := photos[carID]
		if pa == nil {
			pa = &photoAgg{}
			photos[carID] = pa
			pid := id
			pa.cover = &pid
		}
		pa.count++
		return nil
	}); err != nil {
		return nil, err
	}

	options := map[int64]map[string]string{}
	optionSources := map[int64]map[string]string{}
	if err := eachRow(tx, "SELECT car_id, key, value, source FROM options", nil, func(sc scanner) error {
		var carID int64
		var k, v, src string
		if err := sc.Scan(&carID, &k, &v, &src); err != nil {
			return err
		}
		if options[carID] == nil {
			options[carID] = map[string]string{}
			optionSources[carID] = map[string]string{}
		}
		options[carID][k] = v
		optionSources[carID][k] = src
		return nil
	}); err != nil {
		return nil, err
	}

	verdicts := map[int64]*api.Verdict{}
	if err := eachRow(tx, "SELECT car_id, value, note, author, updated_at FROM verdicts", nil, func(sc scanner) error {
		var carID int64
		var v api.Verdict
		var note sql.NullString
		var at float64
		if err := sc.Scan(&carID, &v.Value, &note, &v.Author, &at); err != nil {
			return err
		}
		v.Note, v.UpdatedAt = strPtr(note), fromTS(at)
		verdicts[carID] = &v
		return nil
	}); err != nil {
		return nil, err
	}

	type msgAgg struct {
		count int
		last  float64
		dir   string
	}
	msgs := map[int64]*msgAgg{}
	if err := eachRow(tx, "SELECT car_id, at, direction FROM messages WHERE "+liveMessage+" ORDER BY car_id, at, id", nil, func(sc scanner) error {
		var carID int64
		var at float64
		var dir string
		if err := sc.Scan(&carID, &at, &dir); err != nil {
			return err
		}
		m := msgs[carID]
		if m == nil {
			m = &msgAgg{}
			msgs[carID] = m
		}
		m.count++
		m.last, m.dir = at, dir
		return nil
	}); err != nil {
		return nil, err
	}

	maxAt := map[int64]float64{}
	bump := func(id int64, at float64) {
		if at > maxAt[id] {
			maxAt[id] = at
		}
	}
	for _, q := range []string{"SELECT car_id, MAX(at) FROM events GROUP BY car_id", "SELECT car_id, MAX(updated_at) FROM notes GROUP BY car_id"} {
		if err := eachRow(tx, q, nil, func(sc scanner) error {
			var id int64
			var at float64
			if err := sc.Scan(&id, &at); err != nil {
				return err
			}
			bump(id, at)
			return nil
		}); err != nil {
			return nil, err
		}
	}

	notesText := map[int64][]string{}
	if err := eachRow(tx, "SELECT car_id, text FROM notes", nil, func(sc scanner) error {
		var id int64
		var t string
		if err := sc.Scan(&id, &t); err != nil {
			return err
		}
		notesText[id] = append(notesText[id], t)
		return nil
	}); err != nil {
		return nil, err
	}
	aliases := map[int64][]string{}
	if err := eachRow(tx, "SELECT car_id, alias FROM car_aliases", nil, func(sc scanner) error {
		var id int64
		var a string
		if err := sc.Scan(&id, &a); err != nil {
			return err
		}
		aliases[id] = append(aliases[id], a)
		return nil
	}); err != nil {
		return nil, err
	}
	dealRanks := map[int64]*string{}
	if err := eachRow(tx, "SELECT car_id, value FROM facts WHERE key = 'deal_rank'", nil, func(sc scanner) error {
		var id int64
		var v string
		if err := sc.Scan(&id, &v); err != nil {
			return err
		}
		dealRanks[id] = &v
		return nil
	}); err != nil {
		return nil, err
	}
	dupCount := map[int64]int{}
	if err := eachRow(tx, "SELECT car_a, car_b FROM duplicates WHERE status = 'proposed'", nil, func(sc scanner) error {
		var a, b int64
		if err := sc.Scan(&a, &b); err != nil {
			return err
		}
		dupCount[a]++
		dupCount[b]++
		return nil
	}); err != nil {
		return nil, err
	}

	out := make([]*summaryRow, 0, len(cars))
	for _, c := range cars {
		specs := specsStruct(c.Specs)
		cs := api.CarSummary{
			ID: c.ID, Slug: strPtr(c.Slug), Title: c.title(), Make: specs.Make, Model: specs.Model, Variant: specs.Variant,
			Year: specs.Year, RegDate: specs.RegDate, Km: specs.Km, BatteryNetKwh: specs.BatteryNetKwh, PowerKw: specs.PowerKw, Drive: specs.Drive,
			Country: specs.Country, City: specs.City, DistanceKm: specs.DistanceKm, Market: specs.Market, Interior: specs.Interior,
			InteriorTone: specs.InteriorTone, WheelsIn: specs.WheelsIn, SellerType: "unknown", Status: c.Status,
			StatusReason: strPtr(c.StatusReason), NeedsOwner: c.NeedsOwner, NeedsOwnerReason: strPtr(c.NeedsOwnerReason),
			Summary: strPtr(c.Summary), Options: map[string]string{}, OptionSources: map[string]string{}, Sites: []string{}, CreatedAt: fromTS(c.CreatedAt),
			Verdict: verdicts[c.ID], DuplicateCandidateCount: dupCount[c.ID],
		}
		cs.ModelFamily, _, cs.ModelFamilyManual = c.family()
		cs.GoodDeal, cs.GoodDealNote, cs.GoodDealBy, cs.GoodDealAt = c.GoodDeal, strPtr(c.GoodDealNote), strPtr(c.GoodDealBy), fromNullTS(c.GoodDealAt)
		cs.DealRank = dealRanks[c.ID]
		cs.Tier = carTier(&cs)
		hay := []string{c.title(), c.str("city"), c.str("vin"), c.str("plate"), c.str("colour"), c.Summary.String}
		row := &summaryRow{createdT: c.CreatedAt}
		if c.SellerID.Valid {
			si := sellers[c.SellerID.Int64]
			cs.SellerType = si.typ
			cs.SellerName = strPtr(si.name)
			if cs.SellerName == nil {
				cs.SellerName = strPtr(si.company)
			}
			hay = append(hay, si.name.String, si.company.String)
		}
		row.sellerT = cs.SellerType
		activity := c.UpdatedAt
		ls := listings[c.ID]
		pis := make([]priceInfo, 0, len(ls))
		for _, l := range ls {
			pis = append(pis, l.priceInfo)
			if !slices.Contains(cs.Sites, l.site) {
				cs.Sites = append(cs.Sites, l.site)
			}
			cs.ListingCount++
			if l.Live {
				cs.LiveListingCount++
			}
			if l.status == "removed" {
				cs.RemovedListingCount++
			}
			if l.LastSeen > activity {
				activity = l.LastSeen
			}
			hay = append(hay, l.title, l.URL)
		}
		cs.Price, cs.PriceNote, cs.PriceDrop, cs.PrimaryURL = derivePrice(pis)
		if pa := photos[c.ID]; pa != nil {
			cs.PhotoCount, cs.CoverPhotoID = pa.count, pa.cover
		}
		if o := options[c.ID]; o != nil {
			cs.Options, cs.OptionSources = o, optionSources[c.ID]
		}
		if m := msgs[c.ID]; m != nil {
			cs.MessageCount = m.count
			t := fromTS(m.last)
			d := m.dir
			cs.LastMessageAt, cs.LastMessageDirection = &t, &d
			if m.last > activity {
				activity = m.last
			}
		}
		if at := maxAt[c.ID]; at > activity {
			activity = at
		}
		cs.LastActivityAt = fromTS(activity)
		row.activity = activity
		hay = append(hay, notesText[c.ID]...)
		hay = append(hay, aliases[c.ID]...)
		row.haystack = strings.ToLower(strings.Join(hay, "\n"))
		row.CarSummary = cs
		out = append(out, row)
	}
	return out, nil
}

func eachRow(tx *sql.Tx, q string, args []any, fn func(sc scanner) error) error {
	rows, err := tx.Query(q, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		if err := fn(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

func (f *CarFilter) match(r *summaryRow) bool {
	c := &r.CarSummary
	if f.Q != "" {
		for _, w := range strings.Fields(strings.ToLower(f.Q)) {
			if !strings.Contains(r.haystack, w) {
				return false
			}
		}
	}
	if f.Make != "" && !strings.EqualFold(optStr(c.Make), strings.TrimSpace(f.Make)) {
		return false
	}
	if f.Model != "" {
		full := strings.ToLower(strings.Join([]string{optStr(c.Make), optStr(c.Model), optStr(c.Variant)}, " "))
		if !strings.Contains(full, strings.ToLower(strings.TrimSpace(f.Model))) {
			return false
		}
	}
	intMin := func(v *int, lim *int) bool { return lim == nil || (v != nil && *v >= *lim) }
	intMax := func(v *int, lim *int) bool { return lim == nil || (v != nil && *v <= *lim) }
	if !intMin(c.Year, f.YearMin) || !intMax(c.Year, f.YearMax) || !intMax(c.Km, f.KmMax) ||
		!intMin(c.Price, f.PriceMin) || !intMax(c.Price, f.PriceMax) || !intMax(c.DistanceKm, f.DistanceKmMax) {
		return false
	}
	if f.HpMin != nil || f.HpMax != nil {
		if c.PowerKw == nil {
			return false
		}
		hp := api.Horsepower(*c.PowerKw)
		if !intMin(&hp, f.HpMin) || !intMax(&hp, f.HpMax) {
			return false
		}
	}
	drive := strings.ToLower(optStr(c.Drive))
	if drive == "" {
		drive = "unknown"
	}
	if len(f.Drive) > 0 && !slices.Contains(f.Drive, drive) {
		return false
	}
	if len(f.Country) > 0 && !slices.ContainsFunc(f.Country, func(x string) bool { return strings.EqualFold(x, optStr(c.Country)) }) {
		return false
	}
	if len(f.SellerType) > 0 && !slices.Contains(f.SellerType, r.sellerT) {
		return false
	}
	if len(f.Status) > 0 && !slices.Contains(f.Status, c.Status) {
		return false
	}
	if len(f.Verdict) > 0 {
		v := "none"
		if c.Verdict != nil {
			v = c.Verdict.Value
		}
		if !slices.Contains(f.Verdict, v) {
			return false
		}
	}
	for _, of := range f.Options {
		v, ok := c.Options[of.Key]
		if !ok {
			v = "unknown"
		}
		switch of.Value {
		case "yes_or_unknown":
			if v == "no" {
				return false
			}
		default:
			if v != of.Value {
				return false
			}
		}
	}
	if f.NeedsOwner != nil && c.NeedsOwner != *f.NeedsOwner {
		return false
	}
	if f.HasDuplicates != nil && (c.DuplicateCandidateCount > 0) != *f.HasDuplicates {
		return false
	}
	if f.Market != "" && optStr(c.Market) != f.Market {
		return false
	}
	if f.GoodDeal != nil && c.GoodDeal != *f.GoodDeal {
		return false
	}
	if len(f.tiers) > 0 && !slices.Contains(f.tiers, c.Tier) {
		return false
	}
	if len(f.ModelFamily) > 0 {
		fam := "none"
		if c.ModelFamily != nil {
			fam = *c.ModelFamily
		}
		if !slices.Contains(f.ModelFamily, fam) {
			return false
		}
	}
	return true
}

// sortValue returns (value, present) for numeric sorts; strings handled separately.
func sortValue(r *summaryRow, key string) (float64, bool) {
	c := &r.CarSummary
	ip := func(p *int) (float64, bool) {
		if p == nil {
			return 0, false
		}
		return float64(*p), true
	}
	switch key {
	case "last_activity":
		return r.activity, true
	case "created":
		return r.createdT, true
	case "price":
		return ip(c.Price)
	case "km":
		return ip(c.Km)
	case "year":
		if c.Year == nil {
			return 0, false
		}
		// Within a year, newer registration first.
		v := float64(*c.Year)
		if c.RegDate != nil && len(*c.RegDate) >= 7 {
			if m := (*c.RegDate)[5:7]; m >= "01" && m <= "12" {
				v += float64((m[0]-'0')*10+(m[1]-'0')) / 100
			}
		}
		return v, true
	case "distance_km":
		return ip(c.DistanceKm)
	case "status":
		return float64(statusRank(c.Status)), true
	}
	return 0, false
}

// ListCars handles GET /cars.
func (s *Store) ListCars(ctx context.Context, f CarFilter) (*api.CarList, error) {
	if err := f.validate(); err != nil {
		return nil, err
	}
	var rows []*summaryRow
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		rows, err = buildSummaries(tx)
		return err
	})
	if err != nil {
		return nil, err
	}
	matched := rows[:0]
	for _, r := range rows {
		if f.match(r) {
			matched = append(matched, r)
		}
	}
	desc := f.Order == "desc"
	sort.SliceStable(matched, func(i, j int) bool {
		a, b := matched[i], matched[j]
		if f.Sort == "deal_rank" {
			if c := parseDealRank(a.DealRank).compare(parseDealRank(b.DealRank), desc); c != 0 {
				return c < 0
			}
			return a.ID > b.ID
		}
		if f.Sort == "model" {
			ta, tb := strings.ToLower(a.Title), strings.ToLower(b.Title)
			if ta != tb {
				return (ta < tb) != desc
			}
			return a.ID > b.ID
		}
		va, oka := sortValue(a, f.Sort)
		vb, okb := sortValue(b, f.Sort)
		if oka != okb {
			return oka // missing values last in either order
		}
		if va != vb {
			return (va < vb) != desc
		}
		return a.ID > b.ID
	})
	out := &api.CarList{Total: len(matched), Cars: []api.CarSummary{}}
	for i := f.Offset; i < len(matched) && i < f.Offset+f.Limit; i++ {
		out.Cars = append(out.Cars, matched[i].CarSummary)
	}
	return out, nil
}

// ModelFamilies handles GET /model-families: effective families over live cars, by make then family.
func (s *Store) ModelFamilies(ctx context.Context) (*api.ModelFamilies, error) {
	out := &api.ModelFamilies{Families: []api.ModelFamilyCount{}, Known: FamilyNames()}
	err := s.tx(ctx, func(tx *sql.Tx) error {
		cars, err := loadLiveCars(tx)
		if err != nil {
			return err
		}
		counts := map[familyInfo]int{}
		for _, c := range cars {
			fam, mk, _ := c.family()
			if fam == nil {
				out.Unmapped++
				continue
			}
			counts[familyInfo{*fam, *mk}]++
		}
		infos := make([]familyInfo, 0, len(counts))
		for fi := range counts {
			infos = append(infos, fi)
		}
		sortFamilies(infos)
		for _, fi := range infos {
			out.Families = append(out.Families, api.ModelFamilyCount{Family: fi.name, Make: fi.make, Count: counts[fi]})
		}
		return nil
	})
	return out, err
}

// Stats handles GET /stats.
func (s *Store) Stats(ctx context.Context) (*api.Stats, error) {
	st := &api.Stats{ByStatus: map[string]int{}, ByVerdict: map[string]int{"up": 0, "maybe": 0, "down": 0, "none": 0}}
	for _, s := range api.Statuses {
		st.ByStatus[s] = 0
	}
	err := s.tx(ctx, func(tx *sql.Tx) error {
		if err := eachRow(tx, `SELECT c.status, COALESCE(v.value, 'none'), c.needs_owner FROM cars c
			LEFT JOIN verdicts v ON v.car_id = c.id WHERE c.merged_into IS NULL`, nil, func(sc scanner) error {
			var status, verdict string
			var needs int
			if err := sc.Scan(&status, &verdict, &needs); err != nil {
				return err
			}
			st.Total++
			st.ByStatus[status]++
			st.ByVerdict[verdict]++
			if needs != 0 {
				st.NeedsOwner++
			}
			return nil
		}); err != nil {
			return err
		}
		if err := tx.QueryRow("SELECT COUNT(*) FROM duplicates WHERE status = 'proposed'").Scan(&st.DuplicateProposals); err != nil {
			return err
		}
		if err := tx.QueryRow("SELECT COUNT(*) FROM listings").Scan(&st.Listings); err != nil {
			return err
		}
		return tx.QueryRow("SELECT COUNT(*) FROM messages WHERE " + liveMessage).Scan(&st.Messages)
	})
	return st, err
}
