package store

import (
	"cmp"
	"context"
	"database/sql"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

// "To rate" queue: cars the user has not rated that pass the profile's hard filters, ranked by rank.go.
// DESIGN.md "To rate queue" / "Ranking" document every rule; keep them in sync.

// rankInputs loads summaries plus what ranking needs beyond them (facts, red flags, VIN, seats) and
// derives tier/landed cost for every car.
func (s *Store) rankInputs(tx *sql.Tx, now time.Time, user string) ([]*summaryRow, []*rankCar, error) {
	rows, err := s.buildSummaries(tx, user)
	if err != nil {
		return nil, nil, err
	}
	facts := map[int64]map[string]string{}
	if err := eachRow(tx, "SELECT car_id, key, value FROM facts", nil, func(sc scanner) error {
		var id int64
		var k, v string
		if err := sc.Scan(&id, &k, &v); err != nil {
			return err
		}
		if facts[id] == nil {
			facts[id] = map[string]string{}
		}
		facts[id][k] = v
		return nil
	}); err != nil {
		return nil, nil, err
	}
	type extra struct {
		flags  []string
		hasVIN bool
		seats  *int
	}
	extras := map[int64]extra{}
	if err := eachRow(tx, "SELECT id, red_flags, COALESCE(vin, ''), seats FROM cars WHERE merged_into IS NULL", nil, func(sc scanner) error {
		var id int64
		var flags, vin string
		var seats sql.NullInt64
		if err := sc.Scan(&id, &flags, &vin, &seats); err != nil {
			return err
		}
		extras[id] = extra{parseList(flags), vin != "", intPtr(seats)}
		return nil
	}); err != nil {
		return nil, nil, err
	}
	cars := make([]*rankCar, len(rows))
	for i, r := range rows {
		c := &r.CarSummary
		ex := extras[c.ID]
		rc := &rankCar{c: c, seats: ex.seats, facts: facts[c.ID], redFlags: ex.flags, hasVIN: ex.hasVIN, priceFlags: c.PriceFlags, createdT: r.createdT}
		if rc.facts == nil {
			rc.facts = map[string]string{}
		}
		cars[i] = rc
	}
	s.rk.prepare(cars, now)
	return rows, cars, nil
}

type queueEntry struct {
	item     api.QueueItem
	deal     dealRankKey
	createdT float64
}

// compareQueue: tier asc; good deal first; deal_rank (parsed, unparseable, missing); score desc (missing last);
// landed asc (missing last); created_at desc; id desc.
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
	if c := cmpMissingLast(a.item.Score, b.item.Score, true); c != 0 {
		return c
	}
	if c := cmpMissingLast(a.item.Landed, b.item.Landed, false); c != 0 {
		return c
	}
	if c := cmp.Compare(b.createdT, a.createdT); c != 0 {
		return c
	}
	return cmp.Compare(b.item.Car.ID, a.item.Car.ID)
}

func cmpMissingLast[T cmp.Ordered](a, b *T, desc bool) int {
	switch {
	case a == nil && b == nil:
		return 0
	case a == nil:
		return 1
	case b == nil:
		return -1
	case desc:
		return cmp.Compare(*b, *a)
	}
	return cmp.Compare(*a, *b)
}

// parseTiers reads tier values ("1", "2,3", "T1") within the profile's tiers; empty = def.
func parseTiers(vals []string, def, allowed []int) ([]int, error) {
	var out []int
	for _, v := range vals {
		for _, p := range strings.Split(v, ",") {
			p = strings.TrimPrefix(strings.ToLower(strings.TrimSpace(p)), "t")
			if p == "" {
				continue
			}
			n, err := strconv.Atoi(p)
			if err != nil || !slices.Contains(allowed, n) {
				return nil, badRequestf("tier must be one of %s", joinInts(allowed, "|"))
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

func joinInts(xs []int, sep string) string {
	s := make([]string, len(xs))
	for i, x := range xs {
		s[i] = strconv.Itoa(x)
	}
	return strings.Join(s, sep)
}

// QueueFilter carries the GET /queue query.
type QueueFilter struct {
	Tier          []string // default profile queue_default_tiers
	Spec          string   // "", "confirmed" or "unknown" (see specMatch)
	User          string   // whose verdict counts as rated; "" = owner (resolved by the handler)
	Limit, Offset int
}

// specMatch filters on the profile's must_have options: confirmed = all yes; unknown = none is no and at least one
// is not yes (worth asking the seller).
func specMatch(c *api.CarSummary, mustHave []string, spec string) bool {
	if spec == "" {
		return true
	}
	yes := 0
	for _, k := range mustHave {
		switch c.Options[k] {
		case "yes":
			yes++
		case "no":
			return false
		}
	}
	if spec == "confirmed" {
		return yes == len(mustHave)
	}
	return yes < len(mustHave)
}

// Queue handles GET /queue.
func (s *Store) Queue(ctx context.Context, f QueueFilter) (*api.Queue, error) {
	p, rk := s.profile, s.rk
	tiers, err := parseTiers(f.Tier, p.Search.QueueDefaultTiers, p.Tiers())
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
	if f.Spec != "" && len(p.Search.MustHave) == 0 {
		return nil, badRequestf("spec needs search.must_have in the profile")
	}
	now := s.now()
	var cars []*rankCar
	if err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		_, cars, err = s.rankInputs(tx, now, f.User)
		return err
	}); err != nil {
		return nil, err
	}
	pool := rk.pool(cars)
	out := &api.Queue{Counts: map[string]int{}, Items: []api.QueueItem{}}
	for _, t := range p.Tiers() {
		out.Counts[strconv.Itoa(t)] = 0
	}
	var entries []*queueEntry
	for _, rc := range cars {
		c := rc.c
		if rk.exclusion(rc, f.User) != "" || !specMatch(c, p.Search.MustHave, f.Spec) {
			continue
		}
		out.Counts[strconv.Itoa(c.Tier)]++
		if !slices.Contains(tiers, c.Tier) {
			continue
		}
		entries = append(entries, &queueEntry{item: rk.queueItem(rc, pool, now), deal: parseDealRank(c.DealRank), createdT: rc.createdT})
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

// queueItem ranks one car into its wire form.
func (r *ranker) queueItem(rc *rankCar, pool []*rankCar, now time.Time) api.QueueItem {
	res := r.rank(rc, pool, now)
	it := api.QueueItem{Tier: rc.c.Tier, Car: *rc.c, Score: res.score, Value: res.value, Fit: res.fit, Risk: res.risk,
		RiskReasons: res.reasons, TrimScore: res.trimScore, TrimScoreSource: res.trimSource, PriceGapPct: res.gap,
		Why: r.why(rc, res)}
	if it.RiskReasons == nil {
		it.RiskReasons = []string{}
	}
	if rc.landed != nil {
		it.Landed = &rc.landed.total
	}
	if fp := res.fair; fp != nil {
		it.FairPrice, it.FairLanded, it.FairN, it.FairBasis = &fp.fair, &fp.fairLanded, fp.n, &fp.basis
	}
	return it
}
