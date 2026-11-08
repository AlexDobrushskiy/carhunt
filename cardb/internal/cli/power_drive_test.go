package cli_test

import (
	"carhunt/cardb/internal/api"
	"strings"
	"testing"
)

func TestPowerDriveCLI(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", "https://example.invalid/rear", "--make", "Rear", "--power-kw", "150", "--drive", "rwd")
	e.upsert("--url", "https://example.invalid/all", "--make", "All", "--power-kw", "220", "--drive", "awd")
	e.upsert("--url", "https://example.invalid/missing", "--make", "Missing")
	var got api.CarList
	e.okJSON(&got, "ls", "--min-hp", "204", "--max-hp", "204", "--drive", "RWD,AWD")
	if got.Total != 1 || got.Cars[0].ID != a.CarID {
		t.Fatalf("unexpected filtered list: %+v", got)
	}
	for _, out := range []string{e.ok("ls", "--drive", "rwd"), e.ok("show", id(a.CarID))} {
		if !strings.Contains(out, "204 hp") || strings.Contains(out, "150 kW") {
			t.Fatalf("power display: %s", out)
		}
	}
	e.okJSON(&got, "ls", "--drive", "unknown")
	if got.Total != 1 {
		t.Fatalf("unknown drive: %+v", got)
	}
	e.okJSON(&got, "ls", "--max-hp", "0")
	if got.Total != 0 {
		t.Fatal("zero upper bound was omitted")
	}
	for _, args := range [][]string{{"ls", "--min-hp", "-1"}, {"ls", "--drive", "4wd"}, {"ls", "--min-hp", "300", "--max-hp", "200"}} {
		if r := e.run(args...); r.code != 2 {
			t.Fatalf("%v: %+v", args, r)
		}
	}
}
