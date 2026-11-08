package cli

import (
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

func cmdLs(e *env, args []string) error {
	f := newFlags(e, "ls")
	var statuses, verdicts, countries, sellerTypes, opts, drives, families, tiers multi
	f.Var(&statuses, "status", "status (repeatable or comma list)")
	f.Var(&verdicts, "verdict", "up|maybe|down|none (repeatable/comma; 👍 🤔 👎 ok)")
	user := f.String("user", "", "whose verdict to show and filter on (default the owner)")
	f.Var(&countries, "country", "ISO-2 country (repeatable/comma)")
	f.Var(&sellerTypes, "seller-type", "private|dealer|reseller|unknown (repeatable/comma)")
	f.Var(&opts, "opt", "option filter key:value, value yes|no|unknown|yes_or_unknown (repeatable, ANDed)")
	f.Var(&drives, "drive", "fwd|rwd|awd|unknown (repeatable/comma)")
	f.Var(&families, "family", "model family, e.g. \"Audi Q4,VW ID.4\" (repeatable/comma; none = unmapped; see cardb families)")
	f.Var(&tiers, "tier", "\"To rate\" tier 1|2|3 (repeatable/comma)")
	goodDeal := f.Bool("good-deal", false, "only cars flagged as a good deal (--good-deal=false: only unflagged)")
	minHp := f.String("min-hp", "", "min metric horsepower (rounded kW × 1.36)")
	maxHp := f.String("max-hp", "", "max metric horsepower")
	q := f.String("q", "", "free text (make/model/variant/city/seller/notes/aliases)")
	mk := f.String("make", "", "make")
	model := f.String("model", "", "model substring (matches make+model+variant)")
	maxKm := f.String("max-km", "", "max km")
	minPrice := f.String("min-price", "", "min price €")
	maxPrice := f.String("max-price", "", "max price €")
	yearMin := f.Int("year-min", 0, "min year")
	yearMax := f.Int("year-max", 0, "max year")
	maxDist := f.String("max-dist", "", "max km away")
	needsOwner := f.Bool("needs-owner", false, "only cars flagged for the owner")
	dupes := f.Bool("dupes", false, "only cars with open duplicate proposals")
	market := f.String("market", "", "PT|abroad")
	sortBy := f.String("sort", "", "last_activity|price|km|year|distance_km|created|status|model|deal_rank")
	order := f.String("order", "", "asc|desc")
	limit := f.Int("limit", 0, "max rows (server default 200)")
	offset := f.Int("offset", 0, "skip rows")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		if *q != "" {
			return usageErrorf("ls: unexpected argument %q", pos[0])
		}
		*q = strings.Join(pos, " ") // `cardb ls countryman` = --q countryman
	}
	flt := client.CarFilter{Q: *q, Make: *mk, Model: *model, YearMin: *yearMin, YearMax: *yearMax,
		Market: *market, Sort: *sortBy, Order: *order, Limit: *limit, Offset: *offset}
	for _, it := range []struct {
		name, raw string
		dst       **int
	}{
		{"min-hp", *minHp, &flt.HpMin}, {"max-hp", *maxHp, &flt.HpMax},
	} {
		if it.raw == "" {
			continue
		}
		n, err := strconv.Atoi(it.raw)
		if err != nil || n < 0 {
			return usageErrorf("--%s: want a non-negative integer", it.name)
		}
		*it.dst = &n
	}
	if flt.HpMin != nil && flt.HpMax != nil && *flt.HpMin > *flt.HpMax {
		return usageErrorf("--min-hp must not exceed --max-hp")
	}
	for _, d := range splitList(drives) {
		d = strings.ToLower(d)
		if !contains([]string{"fwd", "rwd", "awd", "unknown"}, d) {
			return usageErrorf("--drive: want fwd|rwd|awd|unknown")
		}
		flt.Drives = append(flt.Drives, d)
	}
	ints := []struct {
		flag string
		raw  *string
		dst  *int
	}{{"max-km", maxKm, &flt.KmMax}, {"min-price", minPrice, &flt.PriceMin}, {"max-price", maxPrice, &flt.PriceMax}, {"max-dist", maxDist, &flt.DistanceKmMax}}
	for _, it := range ints {
		if *it.raw != "" {
			n, err := parseIntLenient(*it.raw)
			if err != nil {
				return usageErrorf("--%s: %v", it.flag, err)
			}
			*it.dst = n
		}
	}
	for _, s := range splitList(statuses) {
		st, err := normalizeStatus(s)
		if err != nil {
			return err
		}
		flt.Statuses = append(flt.Statuses, st)
	}
	for _, v := range splitList(verdicts) {
		if v == "none" {
			flt.Verdicts = append(flt.Verdicts, "none")
			continue
		}
		nv, err := normalizeVerdict(v)
		if err != nil || nv == "" {
			return usageErrorf("--verdict: want up|maybe|down|none, got %q", v)
		}
		flt.Verdicts = append(flt.Verdicts, nv)
	}
	for _, c := range splitList(countries) {
		flt.Countries = append(flt.Countries, strings.ToUpper(c))
	}
	for _, s := range splitList(sellerTypes) {
		if !contains(api.SellerTypes, s) {
			return usageErrorf("--seller-type: want %s", strings.Join(api.SellerTypes, "|"))
		}
		flt.SellerTypes = append(flt.SellerTypes, s)
	}
	for _, o := range splitList(opts) {
		k, v, ok := strings.Cut(o, ":")
		if !ok {
			k, v, ok = strings.Cut(o, "=")
		}
		if !ok {
			v = "yes" // --opt pano means pano:yes
		}
		v = strings.ToLower(v)
		if v != "yes_or_unknown" {
			if v, err = normalizeOptionValue(v); err != nil {
				return err
			}
		}
		flt.Options = append(flt.Options, normalizeKey(k)+":"+v)
	}
	if *market != "" && *market != "PT" && *market != "abroad" {
		if strings.EqualFold(*market, "pt") {
			flt.Market = "PT"
		} else {
			return usageErrorf("--market: want PT|abroad")
		}
	}
	t := true
	if *needsOwner {
		flt.NeedsOwner = &t
	}
	if *dupes {
		flt.HasDuplicates = &t
	}
	if f.isSet("good-deal") {
		flt.GoodDeal = goodDeal
	}
	flt.ModelFamilies = splitList(families)
	if flt.Tiers, err = parseTierFlags(tiers); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	flt.User = *user
	list, err := cl.ListCars(e.ctx, flt)
	if err != nil {
		return err
	}
	return e.emit(list, func(w io.Writer) { printCarTable(w, list) })
}

func printCarTable(w io.Writer, list api.CarList) {
	if len(list.Cars) == 0 {
		fmt.Fprintln(w, "no cars match")
		return
	}
	t := &table{header: []string{"ID", "STATUS", "V", "TITLE", "YEAR", "KM", "POWER", "PRICE", "WHERE", "SITES", "FLAGS"},
		rightAlign: map[int]bool{0: true, 4: true, 5: true, 6: true, 7: true}}
	for _, c := range list.Cars {
		year := ""
		if c.Year != nil {
			year = strconv.Itoa(*c.Year)
		}
		km := ""
		if c.Km != nil {
			km = groupThousands(*c.Km)
		}
		price := ""
		if c.Price != nil {
			price = groupThousands(*c.Price)
			if c.PriceDrop != nil && *c.PriceDrop > 0 {
				price += "↓"
			}
		}
		where := strings.Trim(deref(c.City)+", "+deref(c.Country), ", ")
		var flags []string
		if c.GoodDeal {
			flags = append(flags, "★deal")
		}
		if c.NeedsOwner {
			flags = append(flags, "!owner")
		}
		if c.DuplicateCandidateCount > 0 {
			flags = append(flags, fmt.Sprintf("dupe×%d", c.DuplicateCandidateCount))
		}
		if c.LiveListingCount == 0 && c.ListingCount > 0 {
			flags = append(flags, "gone")
		}
		v := verdictEmoji(c.Verdict)
		if v == "" {
			v = "·"
		}
		title := c.Title
		if c.Slug != nil && *c.Slug != "" {
			title += " [" + *c.Slug + "]"
		}
		t.add(strconv.FormatInt(c.ID, 10), c.Status, v, truncate(title, 60), year, km, fmtPower(c.PowerKw), price,
			truncate(where, 22), strings.Join(c.Sites, ","), strings.Join(flags, " "))
	}
	t.render(w)
	if list.Total > len(list.Cars) {
		fmt.Fprintf(w, "%d of %d cars (use --limit/--offset)\n", len(list.Cars), list.Total)
	} else {
		fmt.Fprintf(w, "%s\n", plural(list.Total, "car", "cars"))
	}
}

func cmdShow(e *env, args []string) error {
	f := newFlags(e, "show")
	user := f.String("user", "", "whose verdict to show first (default the owner)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("show", pos, 1, 1, "CAR"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.GetCarFor(e.ctx, pos[0], *user)
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) { printCard(w, car, pos[0]) })
}

func printCard(w io.Writer, c api.CarDetail, ref string) {
	head := fmt.Sprintf("#%d %s  [%s]", c.ID, c.Title, c.Status)
	if v := verdictEmoji(c.Verdict); v != "" {
		head += " " + v
	}
	fmt.Fprintln(w, head)
	if isNumeric(ref) && ref != strconv.FormatInt(c.ID, 10) {
		fmt.Fprintf(w, "(car %s was merged into #%d)\n", ref, c.ID)
	}
	var ids []string
	if c.Slug != nil && *c.Slug != "" {
		ids = append(ids, "slug "+*c.Slug)
	}
	var others []string
	for _, a := range c.Aliases {
		if c.Slug == nil || a != *c.Slug {
			others = append(others, a)
		}
	}
	if len(others) > 0 {
		ids = append(ids, "aliases "+strings.Join(others, ", "))
	}
	if len(c.MergedFrom) > 0 {
		ids = append(ids, "merged from "+joinIDs(c.MergedFrom))
	}
	if len(ids) > 0 {
		fmt.Fprintln(w, strings.Join(ids, " · "))
	}
	if c.StatusReason != nil && *c.StatusReason != "" {
		fmt.Fprintf(w, "status reason: %s (since %s)\n", *c.StatusReason, fmtTimePtr(c.StatusChangedAt))
	}
	if c.NeedsOwner {
		fmt.Fprintf(w, "⚠ NEEDS OWNER: %s\n", deref(c.NeedsOwnerReason))
	}
	if c.Summary != nil && *c.Summary != "" {
		fmt.Fprintf(w, "summary: %s\n", *c.Summary)
	}
	price := fmtPrice(c.Price)
	if c.PriceNote != nil && *c.PriceNote != "" {
		price += " (" + *c.PriceNote + ")"
	}
	fmt.Fprintf(w, "price: %s\n", price)
	if c.ModelFamily != nil {
		fam := *c.ModelFamily
		if c.ModelFamilyManual {
			fam += " (manual)"
		}
		fmt.Fprintf(w, "family: %s\n", fam)
	} else {
		fmt.Fprintln(w, "family: — (unmapped; cardb set CAR --family NAME)")
	}
	if c.GoodDeal {
		fmt.Fprintln(w, fmtGoodDeal(api.GoodDeal{GoodDeal: true, Note: c.GoodDealNote, By: c.GoodDealBy, At: c.GoodDealAt}))
	}
	if c.DealRank != nil {
		fmt.Fprintf(w, "deal rank: %s\n", *c.DealRank)
	}

	fmt.Fprintln(w, "\nSPECS")
	s := c.CarSpecs
	var l1, l2, l3 []string
	if s.RegDate != nil {
		l1 = append(l1, "reg "+*s.RegDate)
	} else if s.Year != nil {
		l1 = append(l1, strconv.Itoa(*s.Year))
	}
	if s.Km != nil {
		l1 = append(l1, fmtKm(s.Km))
	}
	if pt := s.Powertrain; pt != nil && (pt.BatteryNetKwh != nil || pt.BatteryGrossKwh != nil) {
		b := "battery "
		if pt.BatteryNetKwh != nil {
			b += fmtFloat(*pt.BatteryNetKwh)
		} else {
			b += "?"
		}
		if pt.BatteryGrossKwh != nil {
			b += "/" + fmtFloat(*pt.BatteryGrossKwh)
		}
		l1 = append(l1, b+" kWh")
	}
	if s.PowerKw != nil {
		l1 = append(l1, fmtPower(s.PowerKw))
	}
	if s.Drive != nil {
		l1 = append(l1, *s.Drive)
	}
	if s.Seats != nil {
		l1 = append(l1, fmt.Sprintf("%d seats", *s.Seats))
	}
	if s.Body != nil {
		l1 = append(l1, *s.Body)
	}
	if s.Colour != nil {
		l2 = append(l2, "colour "+*s.Colour)
	}
	if s.Interior != nil || s.InteriorTone != nil {
		in := "interior " + deref(s.Interior)
		if s.InteriorTone != nil {
			in = strings.TrimSpace(in) + " (" + *s.InteriorTone + ")"
		}
		l2 = append(l2, in)
	}
	if s.WheelsIn != nil {
		l2 = append(l2, fmt.Sprintf("%d\" wheels", *s.WheelsIn))
	}
	if s.VIN != nil {
		l3 = append(l3, "VIN "+*s.VIN)
	}
	if s.Plate != nil {
		l3 = append(l3, "plate "+*s.Plate)
	}
	loc := strings.Trim(deref(s.City)+", "+deref(s.Country), ", ")
	if loc != "" {
		if s.DistanceKm != nil {
			loc += fmt.Sprintf(" (%d km away)", *s.DistanceKm)
		}
		l3 = append(l3, loc)
	}
	for _, l := range [][]string{l1, l2, l3} {
		if len(l) > 0 {
			fmt.Fprintf(w, "  %s\n", strings.Join(l, " · "))
		}
	}
	if len(c.RedFlags) > 0 {
		fmt.Fprintln(w, "\nRED FLAGS")
		for _, r := range c.RedFlags {
			fmt.Fprintf(w, "  ⚑ %s\n", r)
		}
	}
	if len(c.OpenQuestions) > 0 {
		fmt.Fprintln(w, "\nOPEN QUESTIONS")
		for _, q := range c.OpenQuestions {
			fmt.Fprintf(w, "  ? %s\n", q)
		}
	}

	fmt.Fprintln(w, "\nSELLER")
	if c.Seller == nil {
		fmt.Fprintln(w, "  —")
	} else {
		printSeller(w, c.Seller)
	}

	fmt.Fprintf(w, "\nLISTINGS (%d)\n", len(c.Listings))
	for _, l := range c.Listings {
		printListing(w, l)
	}

	fmt.Fprintln(w, "\nOPTIONS")
	if len(c.Options) == 0 {
		fmt.Fprintln(w, "  —")
	}
	for _, o := range c.Options {
		line := fmt.Sprintf("  %s %-18s %s", optionMark(o.Value), o.Key, evidenceSuffix(o.Source, o.SourceRef))
		if o.Note != nil && *o.Note != "" {
			line += " — " + *o.Note
		}
		fmt.Fprintln(w, strings.TrimRight(line, " "))
	}
	if len(c.Facts) > 0 {
		fmt.Fprintln(w, "\nFACTS")
		for _, fa := range c.Facts {
			fmt.Fprintf(w, "  %s: %s %s\n", fa.Key, fa.Value, evidenceSuffix(fa.Source, fa.SourceRef))
		}
	}

	fmt.Fprintln(w, "\nVERDICT")
	printVerdicts(w, c.Verdict, c.Verdicts)

	if len(c.Notes) > 0 {
		fmt.Fprintf(w, "\nNOTES (%d)\n", len(c.Notes))
		for _, n := range c.Notes {
			printNote(w, n)
		}
	}
	if len(c.Photos) > 0 {
		cover := c.Photos[0].ID
		for _, p := range c.Photos {
			if p.Cover {
				cover = p.ID
			}
		}
		fmt.Fprintf(w, "\nPHOTOS: %d (cover %d; cardb photo ls %d)\n", len(c.Photos), cover, c.ID)
	}
	if len(c.Duplicates) > 0 {
		fmt.Fprintln(w, "\nPOSSIBLE DUPLICATES")
		for _, d := range c.Duplicates {
			printDupeLine(w, d, c.ID)
		}
	}
	fmt.Fprintf(w, "\nTIMELINE (%d)\n", len(c.Events))
	for _, ev := range c.Events {
		printEvent(w, ev)
	}
	fmt.Fprintf(w, "\nCHAT (%d)\n", len(c.Messages))
	for _, m := range c.Messages {
		printMessage(w, m)
	}
	fmt.Fprintf(w, "\ncreated %s · updated %s\n", fmtTime(c.CreatedAt), fmtTime(c.UpdatedAt))
}

func printSeller(w io.Writer, s *api.Seller) {
	parts := []string{fmt.Sprintf("seller %d", s.ID)}
	if s.Name != nil && *s.Name != "" {
		parts = append(parts, *s.Name)
	}
	parts = append(parts, s.Type)
	if s.Company != nil && *s.Company != "" {
		parts = append(parts, *s.Company)
	}
	if s.City != nil && *s.City != "" {
		parts = append(parts, *s.City)
	}
	fmt.Fprintf(w, "  %s\n", strings.Join(parts, " · "))
	for _, ct := range s.Contacts {
		line := fmt.Sprintf("    %-9s %s", ct.Kind, ct.Value)
		if ct.Note != nil && *ct.Note != "" {
			line += " (" + *ct.Note + ")"
		}
		fmt.Fprintln(w, line)
	}
	if s.Note != nil && *s.Note != "" {
		fmt.Fprintf(w, "    note: %s\n", *s.Note)
	}
}

func printListing(w io.Writer, l api.Listing) {
	price := fmtPrice(l.Price)
	if l.PriceNote != nil && *l.PriceNote != "" {
		price += " (" + *l.PriceNote + ")"
	}
	fmt.Fprintf(w, "  listing %d · car %d · %s · %s · %s\n", l.ID, l.CarID, l.Site, l.Status, price)
	fmt.Fprintf(w, "    %s\n", l.URL)
	if l.Title != nil && *l.Title != "" {
		fmt.Fprintf(w, "    %q\n", *l.Title)
	}
	if len(l.PriceHistory) > 1 {
		var pts []string
		for _, p := range l.PriceHistory {
			pts = append(pts, fmt.Sprintf("%s (%s)", groupThousands(p.Price), fmtDate(p.At)))
		}
		fmt.Fprintf(w, "    price history: %s\n", strings.Join(pts, " → "))
	}
	seen := fmt.Sprintf("    seen %s … %s", fmtDate(l.FirstSeenAt), fmtDate(l.LastSeenAt))
	if l.RemovedAt != nil {
		seen += " · removed " + fmtDate(*l.RemovedAt)
	}
	fmt.Fprintln(w, seen)
}

func cmdFindListing(e *env, args []string) error {
	f := newFlags(e, "find-listing")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("find-listing", pos, 1, 1, "URL"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ls, err := cl.FindListings(e.ctx, pos[0], "", "")
	if err != nil {
		return err
	}
	if ls == nil {
		ls = []api.Listing{}
	}
	if err := e.emit(ls, func(w io.Writer) {
		for _, l := range ls {
			printListing(w, l)
		}
	}); err != nil {
		return err
	}
	if len(ls) == 0 {
		return &notFoundError{"no listing for " + pos[0]}
	}
	return nil
}

func cmdDupes(e *env, args []string) error {
	f := newFlags(e, "dupes")
	car := f.String("car", "", "only proposals involving this car")
	status := f.String("status", "", "proposed|rejected|merged (default proposed)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) == 1 && *car == "" {
		*car = pos[0]
	} else if len(pos) > 0 {
		return usageErrorf("usage: cardb dupes [--car CAR] [--status S]")
	}
	if *status != "" && !contains([]string{"proposed", "rejected", "merged"}, *status) {
		return usageErrorf("--status: want proposed|rejected|merged")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ds, err := cl.ListDuplicates(e.ctx, *status, *car)
	if err != nil {
		return err
	}
	if ds == nil {
		ds = []api.DuplicateCandidate{}
	}
	return e.emit(ds, func(w io.Writer) {
		if len(ds) == 0 {
			fmt.Fprintln(w, "no duplicate proposals")
			return
		}
		t := &table{header: []string{"ID", "CARS", "SCORE", "STATUS", "REASONS"}, rightAlign: map[int]bool{0: true}}
		for _, d := range ds {
			cars := fmt.Sprintf("%d ↔ %d", d.CarA, d.CarB)
			if d.OtherTitle != "" {
				cars += " " + truncate(d.OtherTitle, 30)
			}
			t.add(strconv.FormatInt(d.ID, 10), cars, fmt.Sprintf("%.2f", d.Score), d.Status, strings.Join(d.Reasons, "; "))
		}
		t.render(w)
		fmt.Fprintln(w, "same car → cardb merge TARGET SOURCE · different → cardb dupe-reject ID")
	})
}

func cmdDupeReject(e *env, args []string) error {
	f := newFlags(e, "dupe-reject")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("dupe-reject", pos, 1, -1, "ID…"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var out []api.DuplicateCandidate
	for _, s := range pos {
		id, err := parseID("duplicate id", s)
		if err != nil {
			return err
		}
		d, err := cl.RejectDuplicate(e.ctx, id)
		if err != nil {
			return fmt.Errorf("duplicate %d: %w", id, err)
		}
		out = append(out, d)
	}
	return e.emit(out, func(w io.Writer) {
		for _, d := range out {
			fmt.Fprintf(w, "duplicate %d (cars %d, %d): %s\n", d.ID, d.CarA, d.CarB, d.Status)
		}
	})
}

type deletePlan struct {
	CarID    int64    `json:"car_id"`
	Title    string   `json:"title"`
	Status   string   `json:"status"`
	Listings []string `json:"listings"`
	Messages int      `json:"messages"`
	Photos   int      `json:"photos"`
	Notes    int      `json:"notes"`
	Events   int      `json:"events"`
	Deleted  bool     `json:"deleted"`
}

func cmdRm(e *env, args []string) error {
	f := newFlags(e, "rm")
	yes := f.Bool("yes", false, "really delete (no undo)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("rm", pos, 1, 1, "CAR --yes"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.GetCar(e.ctx, pos[0])
	if err != nil {
		return err
	}
	// An old id of a merged car resolves to the merge target; never delete the target by accident.
	if isNumeric(pos[0]) && pos[0] != strconv.FormatInt(car.ID, 10) {
		return usageErrorf("car %s was merged into car %d (%s); to delete that car run `cardb rm %d --yes`", pos[0], car.ID, car.Title, car.ID)
	}
	plan := deletePlan{CarID: car.ID, Title: car.Title, Status: car.Status, Listings: []string{},
		Messages: len(car.Messages), Photos: len(car.Photos), Notes: len(car.Notes), Events: len(car.Events)}
	for _, l := range car.Listings {
		plan.Listings = append(plan.Listings, l.URL)
	}
	describe := func(w io.Writer, verb string) {
		fmt.Fprintf(w, "%s car %d %s [%s]: %s, %s, %s, %s\n", verb, plan.CarID, plan.Title, plan.Status,
			plural(len(plan.Listings), "listing", "listings"), plural(plan.Messages, "message", "messages"),
			plural(plan.Photos, "photo", "photos"), plural(plan.Notes, "note", "notes"))
		for _, u := range plan.Listings {
			fmt.Fprintf(w, "  %s\n", u)
		}
	}
	if !*yes {
		if err := e.emit(plan, func(w io.Writer) { describe(w, "would delete") }); err != nil {
			return err
		}
		return usageErrorf("not deleted: re-run with --yes to delete car %d permanently", car.ID)
	}
	if err := cl.DeleteCar(e.ctx, strconv.FormatInt(car.ID, 10), car.ID); err != nil {
		return err
	}
	plan.Deleted = true
	return e.emit(plan, func(w io.Writer) { describe(w, "deleted") })
}

func cmdMerge(e *env, args []string) error {
	f := newFlags(e, "merge")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("merge", pos, 2, -1, "TARGET SOURCE…"); err != nil {
		return err
	}
	for _, s := range pos[1:] {
		if s == pos[0] {
			return usageErrorf("merge: cannot merge car %s into itself", s)
		}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.Merge(e.ctx, pos[0], api.MergeInput{From: pos[1:]})
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) {
		fmt.Fprintf(w, "merged %s into car %d %s (%s, %s)\n", strings.Join(pos[1:], ", "), car.ID, car.Title,
			plural(len(car.Listings), "listing", "listings"), plural(len(car.Messages), "message", "messages"))
	})
}

func cmdSplit(e *env, args []string) error {
	f := newFlags(e, "split")
	var listings multi
	f.Var(&listings, "listing", "listing id to move (repeatable or comma list)")
	moveMsgs := f.Bool("move-messages", false, "also move messages from the moved listings' seller contacts")
	keepPhotos := f.Bool("keep-photos", false, "leave the moved listings' photos on the original car")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("split", pos, 1, 1, "CAR --listing ID… [--move-messages]"); err != nil {
		return err
	}
	in := api.SplitInput{MoveMessages: *moveMsgs}
	for _, s := range splitList(listings) {
		id, err := parseID("--listing", s)
		if err != nil {
			return err
		}
		in.ListingIDs = append(in.ListingIDs, id)
	}
	if len(in.ListingIDs) == 0 {
		return usageErrorf("split: give at least one --listing ID")
	}
	if *keepPhotos {
		no := false
		in.MovePhotos = &no
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.Split(e.ctx, pos[0], in)
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) {
		fmt.Fprintf(w, "split into new car %d %s (%s)\n", car.ID, car.Title, plural(len(car.Listings), "listing", "listings"))
	})
}

func cmdStats(e *env, args []string) error {
	f := newFlags(e, "stats")
	user := f.String("user", "", "whose verdicts to count (default the owner)")
	if _, err := f.parse(args); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	s, err := cl.StatsFor(e.ctx, *user)
	if err != nil {
		return err
	}
	return e.emit(s, func(w io.Writer) {
		fmt.Fprintf(w, "cars %d · listings %d · messages %d · needs owner %d · duplicate proposals %d\n",
			s.Total, s.Listings, s.Messages, s.NeedsOwner, s.DuplicateProposals)
		var st []string
		for _, k := range api.Statuses {
			if n := s.ByStatus[k]; n > 0 {
				st = append(st, fmt.Sprintf("%s %d", k, n))
			}
		}
		fmt.Fprintf(w, "status: %s\n", strings.Join(st, " · "))
		var vs []string
		for _, k := range []string{"up", "maybe", "down", "none"} {
			if n := s.ByVerdict[k]; n > 0 {
				label := k
				if k != "none" {
					label = verdictEmoji(&api.Verdict{Value: k})
				}
				vs = append(vs, fmt.Sprintf("%s %d", label, n))
			}
		}
		fmt.Fprintf(w, "verdict: %s\n", strings.Join(vs, " · "))
	})
}

func cmdFamilies(e *env, args []string) error {
	f := newFlags(e, "families")
	known := f.Bool("known", false, "list every known family name (valid for --family and set --family)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		return usageErrorf("usage: cardb families [--known]")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	fams, err := cl.ModelFamilies(e.ctx)
	if err != nil {
		return err
	}
	return e.emit(fams, func(w io.Writer) {
		if *known {
			for _, n := range fams.Known {
				fmt.Fprintln(w, n)
			}
			return
		}
		t := &table{header: []string{"FAMILY", "CARS"}, rightAlign: map[int]bool{1: true}}
		for _, fc := range fams.Families {
			t.add(fc.Family, strconv.Itoa(fc.Count))
		}
		t.render(w)
		fmt.Fprintf(w, "unmapped: %d (cardb ls --family none)\n", fams.Unmapped)
	})
}

func cmdActivity(e *env, args []string) error {
	f := newFlags(e, "activity")
	since := f.String("since", "", "RFC 3339 time or a duration back from now (30m, 24h, 7d)")
	limit := f.Int("limit", 0, "max items (server default 100)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		return usageErrorf("usage: cardb activity [--since 24h] [--limit N]")
	}
	var sp *time.Time
	if *since != "" {
		t, err := parseSince(*since)
		if err != nil {
			return err
		}
		sp = &t
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	items, err := cl.Activity(e.ctx, sp, *limit)
	if err != nil {
		return err
	}
	if items == nil {
		items = []api.ActivityItem{}
	}
	return e.emit(items, func(w io.Writer) {
		if len(items) == 0 {
			fmt.Fprintln(w, "no activity")
		}
		for _, it := range items {
			what := it.Kind
			switch {
			case it.Event != nil:
				what = fmt.Sprintf("%s: %s", it.Event.Type, firstLine(it.Event.Summary))
			case it.Message != nil:
				m := it.Message
				what = fmt.Sprintf("%s %s %s: %s", m.Channel, arrow(m.Direction), m.Sender, truncate(firstLine(m.Text), 80))
			}
			fmt.Fprintf(w, "%s  #%-4d %-28s %s\n", fmtTime(it.At), it.CarID, truncate(it.CarTitle, 28), what)
		}
	})
}

func cmdHealth(e *env, args []string) error {
	f := newFlags(e, "health")
	if _, err := f.parse(args); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	h, err := cl.Health(e.ctx)
	if err != nil {
		return err
	}
	if err := e.emit(h, func(w io.Writer) {
		fmt.Fprintf(w, "ok=%v version=%s server=%s\n", h.OK, h.Version, cl.BaseURL)
	}); err != nil {
		return err
	}
	if !h.OK {
		return fmt.Errorf("server reports not ok")
	}
	return nil
}

func fmtPower(kw *float64) string {
	if kw == nil {
		return "—"
	}
	return fmt.Sprintf("%d hp", api.Horsepower(*kw))
}
