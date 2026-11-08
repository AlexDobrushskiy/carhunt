package cli

import (
	"fmt"
	"io"
	"math"
	"sort"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
)

func cmdQueue(e *env, args []string) error {
	f := newFlags(e, "queue")
	var tiers multi
	f.Var(&tiers, "tier", "tiers to show (repeatable/comma; default = profile queue_default_tiers; see cardb profile)")
	limit := f.Int("limit", 0, "max rows (server default 200)")
	offset := f.Int("offset", 0, "skip rows")
	spec := f.String("spec", "", "profile must_have options: confirmed = all yes; unknown = none no, at least one unknown")
	user := f.String("user", "", "whose verdicts count as rated (default the owner)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		return usageErrorf("usage: cardb queue [--limit N] [--tier 1,2] [--tier 3] [--spec confirmed|unknown] [--user NAME]")
	}
	ts, err := parseTierFlags(tiers)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	q, err := cl.Queue(e.ctx, ts, *spec, *user, *limit, *offset)
	if err != nil {
		return err
	}
	return e.emit(q, func(w io.Writer) { printQueue(w, q) })
}

// parseTierFlags reads --tier values (positive integers, T1 ok, comma lists); the server checks them against the profile.
func parseTierFlags(vals multi) ([]int, error) {
	var out []int
	for _, v := range splitList(vals) {
		n, err := strconv.Atoi(strings.TrimPrefix(strings.ToLower(v), "t"))
		if err != nil || n < 1 {
			return nil, usageErrorf("--tier: want a tier number (1, 2, T3…), got %q", v)
		}
		out = append(out, n)
	}
	return out, nil
}

func queueCounts(counts map[string]int) string {
	keys := make([]int, 0, len(counts))
	for k := range counts {
		if n, err := strconv.Atoi(k); err == nil {
			keys = append(keys, n)
		}
	}
	sort.Ints(keys)
	parts := make([]string, len(keys))
	for i, k := range keys {
		parts[i] = fmt.Sprintf("T%d %d", k, counts[strconv.Itoa(k)])
	}
	return strings.Join(parts, " · ")
}

func printQueue(w io.Writer, q api.Queue) {
	counts := queueCounts(q.Counts)
	if len(q.Items) == 0 {
		fmt.Fprintf(w, "queue empty (%s)\n", counts)
		return
	}
	t := &table{header: []string{"#", "TIER", "DEAL", "ID", "TITLE", "YEAR", "KM", "PRICE", "LANDED", "GAP", "SCORE", "WHY"},
		rightAlign: map[int]bool{0: true, 3: true, 5: true, 6: true, 7: true, 8: true, 9: true, 10: true}}
	for _, it := range q.Items {
		c := it.Car
		year, km, price, landed, gap, score := "", "", "", "", "", ""
		if c.Year != nil {
			year = strconv.Itoa(*c.Year)
		}
		if c.Km != nil {
			km = groupThousands(*c.Km)
		}
		if c.Price != nil {
			price = groupThousands(*c.Price)
		}
		if it.Landed != nil {
			landed = groupThousands(*it.Landed)
		}
		if it.PriceGapPct != nil {
			gap = fmt.Sprintf("%+d%%", int(math.Round(*it.PriceGapPct)))
		}
		if it.Score != nil {
			score = strconv.FormatFloat(*it.Score, 'f', 1, 64)
		}
		deal := deref(c.DealRank)
		if c.GoodDeal {
			deal = strings.TrimSpace("★ " + deal)
		}
		t.add(strconv.Itoa(it.Position), "T"+strconv.Itoa(it.Tier), deal, strconv.FormatInt(c.ID, 10), truncate(c.Title, 44), year, km,
			price, landed, gap, score, it.Why)
	}
	t.render(w)
	shown := fmt.Sprintf("%d–%d of %d", q.Items[0].Position, q.Items[len(q.Items)-1].Position, q.Total)
	fmt.Fprintf(w, "%s to rate (%s; GAP = landed vs peers' fair landed, + = cheaper)\n", shown, counts)
}
