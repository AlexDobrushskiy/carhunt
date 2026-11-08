package cli

import (
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
)

func cmdQueue(e *env, args []string) error {
	f := newFlags(e, "queue")
	var tiers multi
	f.Var(&tiers, "tier", "tiers to show, 1|2|3 (repeatable/comma; default 1,2)")
	limit := f.Int("limit", 0, "max rows (server default 200)")
	offset := f.Int("offset", 0, "skip rows")
	spec := f.String("spec", "", "confirmed = e-seats and tailgate both yes; unknown = neither no, one or both unknown")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		return usageErrorf("usage: cardb queue [--limit N] [--tier 1,2] [--tier 3] [--spec confirmed|unknown]")
	}
	ts, err := parseTierFlags(tiers)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	q, err := cl.Queue(e.ctx, ts, *spec, *limit, *offset)
	if err != nil {
		return err
	}
	return e.emit(q, func(w io.Writer) { printQueue(w, q) })
}

// parseTierFlags reads --tier values (1|2|3, T1 ok, comma lists).
func parseTierFlags(vals multi) ([]int, error) {
	var out []int
	for _, v := range splitList(vals) {
		n, err := strconv.Atoi(strings.TrimPrefix(strings.ToLower(v), "t"))
		if err != nil || n < 1 || n > 3 {
			return nil, usageErrorf("--tier: want 1|2|3, got %q", v)
		}
		out = append(out, n)
	}
	return out, nil
}

func printQueue(w io.Writer, q api.Queue) {
	counts := fmt.Sprintf("T1 %d · T2 %d · T3 %d", q.Counts["1"], q.Counts["2"], q.Counts["3"])
	if len(q.Items) == 0 {
		fmt.Fprintf(w, "queue empty (%s)\n", counts)
		return
	}
	t := &table{header: []string{"#", "TIER", "DEAL", "ID", "TITLE", "YEAR", "KM", "PRICE", "GAP", "TRIM", "WHY"},
		rightAlign: map[int]bool{0: true, 3: true, 5: true, 6: true, 7: true, 8: true, 9: true}}
	for _, it := range q.Items {
		c := it.Car
		year, km, price, gap := "", "", "", ""
		if c.Year != nil {
			year = strconv.Itoa(*c.Year)
		}
		if c.Km != nil {
			km = groupThousands(*c.Km)
		}
		if c.Price != nil {
			price = groupThousands(*c.Price)
		}
		if it.PriceGapPct != nil {
			gap = fmt.Sprintf("%+d%%", int(math.Round(*it.PriceGapPct)))
		}
		deal := deref(c.DealRank)
		if c.GoodDeal {
			deal = strings.TrimSpace("★ " + deal)
		}
		trim := strconv.FormatFloat(it.TrimScore, 'f', -1, 64)
		if it.TrimScoreSource == "fact" {
			trim += "*"
		}
		t.add(strconv.Itoa(it.Position), "T"+strconv.Itoa(it.Tier), deal, strconv.FormatInt(c.ID, 10), truncate(c.Title, 44), year, km,
			price, gap, trim, it.Why)
	}
	t.render(w)
	shown := fmt.Sprintf("%d–%d of %d", q.Items[0].Position, q.Items[len(q.Items)-1].Position, q.Total)
	fmt.Fprintf(w, "%s to rate (%s; trim* = trim_score fact)\n", shown, counts)
}
