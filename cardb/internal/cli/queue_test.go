package cli_test

import (
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

func TestQueueCLI(t *testing.T) {
	e := newE2E(t)
	base := []string{"--make", "VW", "--model", "ID.4 Pro", "--reg", "2024-03", "--km", "20000", "--power-kw", "210", "--drive", "rwd",
		"--country", "PT", "--city", "Porto"}
	car := func(tag string, extra ...string) int64 {
		return e.upsert(append(append([]string{"--url", "https://example.invalid/q/" + tag}, base...), extra...)...).CarID
	}
	a := car("a", "--price", "30000", "--opt", "electric_seats=yes", "--seen-at", "2026-10-01T09:00:00Z")
	b := car("b", "--price", "33000", "--seen-at", "2026-10-02T09:00:00Z")
	cc := car("c", "--price", "36000", "--fact", "deal_rank=T1-1", "--seen-at", "2026-10-03T09:00:00Z")
	t2 := e.upsert("--url", "https://example.invalid/q/ev6", "--make", "Kia", "--model", "EV6", "--variant", "Air", "--reg", "2024-01",
		"--price", "31000", "--country", "ES").CarID
	t3 := e.upsert("--url", "https://example.invalid/q/eqa", "--make", "Mercedes", "--model", "EQA 250", "--reg", "2024-01",
		"--price", "31000", "--country", "DE").CarID
	rated := car("rated", "--price", "31000")
	e.ok("verdict", id(rated), "down")
	e.ok("deal", id(b), "on", "--note", "cheapest T1")

	var q api.Queue
	e.okJSON(&q, "queue")
	got := []int64{}
	for _, it := range q.Items {
		got = append(got, it.Car.ID)
	}
	if want := []int64{b, cc, a, t2}; !equalIDs(got, want) {
		t.Fatalf("queue order %v, want %v", got, want)
	}
	if q.Total != 4 || q.Counts["1"] != 3 || q.Counts["2"] != 1 || q.Counts["3"] != 1 || q.Items[0].Position != 1 || q.Items[0].Why != "cheapest T1" {
		t.Fatalf("queue json: %+v", q)
	}
	e.okJSON(&q, "queue", "--tier", "3")
	if q.Total != 1 || q.Items[0].Car.ID != t3 {
		t.Fatalf("--tier 3: %+v", q)
	}
	e.okJSON(&q, "queue", "--tier", "1,2", "--tier", "3", "--limit", "2")
	if q.Total != 5 || len(q.Items) != 2 {
		t.Fatalf("--tier 1,2 --tier 3 --limit 2: total %d items %d", q.Total, len(q.Items))
	}

	table := e.ok("queue")
	lines := strings.Split(strings.TrimRight(table, "\n"), "\n")
	if len(lines) != 6 {
		t.Fatalf("table:\n%s", table)
	}
	for _, col := range []string{"#", "TIER", "DEAL", "ID", "TITLE", "YEAR", "KM", "PRICE", "LANDED", "GAP", "SCORE", "WHY"} {
		if !strings.Contains(lines[0], col) {
			t.Fatalf("header lacks %s: %q", col, lines[0])
		}
	}
	first := strings.Fields(lines[1])
	if first[0] != "1" || first[1] != "T1" || first[2] != "★" || first[3] != id(b) || !strings.Contains(lines[1], "cheapest T1") {
		t.Fatalf("row 1: %q", lines[1])
	}
	if !strings.Contains(lines[2], "T1-1") || !strings.Contains(lines[2], id(cc)) {
		t.Fatalf("row 2: %q", lines[2])
	}
	// a: peers b, c and the rated car (n=3) → fair landed 33 150 vs landed 30 165 (+165: default PT distance).
	if !strings.Contains(lines[3], "+9%") || !strings.Contains(lines[3], "30 165") || !strings.Contains(lines[3], "✓ e-seats · −9 % vs ID.4 · ~275 hp 2wd (n=3)") {
		t.Fatalf("row 3 (landed, gap, why): %q", lines[3])
	}
	if lines[5] != "1–4 of 4 to rate (T1 3 · T2 1 · T3 1; GAP = landed vs peers' fair landed, + = cheaper)" {
		t.Fatalf("footer: %q", lines[5])
	}

	var list api.CarList
	e.okJSON(&list, "ls", "--tier", "2,3")
	if list.Total != 2 {
		t.Fatalf("ls --tier 2,3: %+v", list)
	}
	for _, bad := range [][]string{{"queue", "--tier", "0"}, {"queue", "extra"}, {"ls", "--tier", "x"}} {
		if r := e.run(bad...); r.code != 2 {
			t.Fatalf("%v: exit %d, want 2 (%s)", bad, r.code, r.stderr)
		}
	}
	// Tiers beyond the profile's are the server's call.
	if r := e.run("queue", "--tier", "4"); r.code != 1 || !strings.Contains(r.stderr, "tier must be one of 1|2|3") {
		t.Fatalf("--tier 4: %+v", r)
	}
}

func TestProfileCLI(t *testing.T) {
	e := newE2E(t)
	out := e.ok("profile")
	for _, want := range []string{"owner: owner · home Lisbon PT", "tiers (queue default 1,2):", "T1 VAG 286 hp RWD",
		"VW ID.4 · 280–290 hp (unknown: pro)", "T3 everything else", "hard filters:", "  - km ≤ 80 000",
		"options wanted: electric_seats 5, power_tailgate 5, pano 1.67", "must have: electric_seats, power_tailgate", "weights: value 1 · fit 1 · risk 1"} {
		if !strings.Contains(out, want) {
			t.Errorf("profile output lacks %q", want)
		}
	}
	if t.Failed() {
		t.Log(out)
	}
	var p api.Profile
	e.okJSON(&p, "profile")
	if p.DefaultTier != 3 || len(p.Tiers) != 3 || p.Owner.Home.Country != "PT" {
		t.Fatalf("profile --json: %+v", p)
	}
	if r := e.run("profile", "x"); r.code != 2 {
		t.Fatalf("profile x: exit %d", r.code)
	}
}

func equalIDs(a, b []int64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
