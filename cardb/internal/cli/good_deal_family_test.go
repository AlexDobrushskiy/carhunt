package cli_test

import (
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

func TestGoodDealCLI(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", "https://example.invalid/a", "--make", "VW", "--model", "ID.4 Pro", "--fact", "deal_rank=T1-3")
	b := e.upsert("--url", "https://example.invalid/b", "--make", "Kia", "--model", "EV6", "--fact", "deal_rank=T1-1")
	c := e.upsert("--url", "https://example.invalid/c", "--make", "Kia", "--model", "EV6 GT")

	out := e.ok("deal", id(a.CarID), "on", "--note", "cheapest  with pano", "--at", "2026-11-04T09:30:00Z", "--author", "deal-finder")
	if !strings.Contains(out, "★ good deal — cheapest with pano (deal-finder,") || strings.Count(out, "\n") != 1 {
		t.Fatalf("deal on: %q", out)
	}
	var gd api.GoodDeal
	e.okJSON(&gd, "deal", id(a.CarID), "yes")
	if !gd.GoodDeal || gd.Note == nil || *gd.Note != "cheapest with pano" || *gd.By != "deal-finder" {
		t.Fatalf("on without --note keeps the note: %+v", gd)
	}
	e.okJSON(&gd, "deal", id(a.CarID), "✓", "--note", "")
	if gd.Note != nil {
		t.Fatalf("--note \"\" clears: %+v", gd)
	}
	e.ok("deal", id(b.CarID), "true")
	if out := e.ok("deal", id(b.CarID), "off"); out != "car "+id(b.CarID)+": not a good deal\n" {
		t.Fatalf("deal off: %q", out)
	}
	if r := e.run("deal", id(a.CarID), "maybe"); r.code != 2 {
		t.Fatalf("bad value: %+v", r)
	}
	if r := e.run("deal", "nope", "on"); r.code != 3 {
		t.Fatalf("unknown car: %+v", r)
	}

	var list api.CarList
	e.okJSON(&list, "ls", "--good-deal")
	if list.Total != 1 || list.Cars[0].ID != a.CarID {
		t.Fatalf("--good-deal: %+v", list)
	}
	e.okJSON(&list, "ls", "--good-deal=false")
	if list.Total != 2 {
		t.Fatalf("--good-deal=false: %+v", list)
	}
	table := e.ok("ls")
	for _, line := range strings.Split(table, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), id(a.CarID)+" ") != strings.Contains(line, "★deal") {
			t.Fatalf("★deal flag on the wrong row:\n%s", table)
		}
	}
	e.okJSON(&list, "ls", "--sort", "deal_rank")
	if got := []int64{list.Cars[0].ID, list.Cars[1].ID, list.Cars[2].ID}; got[0] != b.CarID || got[1] != a.CarID || got[2] != c.CarID {
		t.Fatalf("--sort deal_rank: %v", got)
	}

	show := e.ok("show", id(a.CarID))
	for _, want := range []string{"family: VW ID.4\n", "★ good deal (agent-session-1,", "deal rank: T1-3\n"} {
		if !strings.Contains(show, want) {
			t.Fatalf("show lacks %q:\n%s", want, show)
		}
	}
	if show := e.ok("show", id(c.CarID)); strings.Contains(show, "good deal") || strings.Contains(show, "deal rank") || !strings.Contains(show, "family: Kia EV6\n") {
		t.Fatalf("show of an unflagged car:\n%s", show)
	}
}

func TestModelFamilyCLI(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", "https://example.invalid/a", "--make", "Audi", "--model", "Q4 e-tron", "--variant", "Sportback 45")
	b := e.upsert("--url", "https://example.invalid/b", "--make", "VW", "--model", "ID.4")
	c := e.upsert("--url", "https://example.invalid/c", "--make", "Lada", "--model", "Niva Electric")

	var list api.CarList
	e.okJSON(&list, "ls", "--family", "Audi Q4 Sportback,vw id.4")
	if list.Total != 2 {
		t.Fatalf("--family comma: %+v", list)
	}
	e.okJSON(&list, "ls", "--family", "none", "--family", "VW ID.4")
	if list.Total != 2 || list.Cars[0].ID == a.CarID || list.Cars[1].ID == a.CarID {
		t.Fatalf("--family repeat + none: %+v", list)
	}
	if r := e.run("ls", "--family", "Audi Q5"); r.code != 1 || !strings.Contains(r.stderr, "unknown model family") {
		t.Fatalf("unknown family: %+v", r)
	}

	out := e.ok("families")
	for _, want := range []string{"Audi Q4 Sportback", "VW ID.4", "unmapped: 1"} {
		if !strings.Contains(out, want) {
			t.Fatalf("families lacks %q:\n%s", want, out)
		}
	}
	var fams api.ModelFamilies
	e.okJSON(&fams, "families")
	if len(fams.Families) != 2 || fams.Unmapped != 1 || fams.Families[0].Family != "Audi Q4 Sportback" || fams.Families[0].Count != 1 {
		t.Fatalf("families --json: %+v", fams)
	}
	if out := e.ok("families", "--known"); !strings.Contains(out, "Škoda Enyaq Coupé\n") {
		t.Fatalf("families --known:\n%s", out)
	}

	e.ok("set", id(c.CarID), "--family", "Skoda Enyaq")
	if show := e.ok("show", id(c.CarID)); !strings.Contains(show, "family: Škoda Enyaq (manual)\n") {
		t.Fatalf("show manual family:\n%s", show)
	}
	e.okJSON(&list, "ls", "--family", "none")
	if list.Total != 0 {
		t.Fatalf("override still unmapped: %+v", list)
	}
	if r := e.run("set", id(c.CarID), "--family", "Tesla Roadster"); r.code != 1 || !strings.Contains(r.stderr, "unknown model family") {
		t.Fatalf("set unknown family: %+v", r)
	}
	e.ok("set", id(c.CarID), "--clear", "model_family")
	if show := e.ok("show", id(c.CarID)); !strings.Contains(show, "family: — (unmapped") {
		t.Fatalf("show after --clear:\n%s", show)
	}
	e.ok("set", id(b.CarID), "--family", "VW ID.5")
	e.ok("set", id(b.CarID), "--clear", "family")
	var d api.CarDetail
	e.okJSON(&d, "show", id(b.CarID))
	if d.ModelFamily == nil || *d.ModelFamily != "VW ID.4" || d.ModelFamilyManual {
		t.Fatalf("--clear family alias: %v %v", d.ModelFamily, d.ModelFamilyManual)
	}
}
