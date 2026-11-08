package cli_test

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

func (e *e2e) show(car string) api.CarDetail {
	e.t.Helper()
	var d api.CarDetail
	e.okJSON(&d, "show", car)
	return d
}

// fails runs a command that must exit with code and returns stderr.
func (e *e2e) fails(code int, args ...string) string {
	e.t.Helper()
	r := e.run(args...)
	if r.code != code {
		e.t.Fatalf("cardb %s: exit %d, want %d\nstdout: %s\nstderr: %s", strings.Join(args, " "), r.code, code, r.stdout, r.stderr)
	}
	return r.stderr
}

func TestCLIPowertrain(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", "https://example.invalid/cli/pt", "--make", "SYNTH", "--model", "Volt", "--price", "30000",
		"--fuel", "BEV", "--battery-net", "77", "--battery-gross", "82 kWh", "--gearbox", "automatic", "--wltp-range", "520",
		"--wltp-consumption", "16,5", "--co2", "0")
	car := id(r.CarID)
	pt := e.show(car).Powertrain
	if pt == nil || *pt.Fuel != "bev" || *pt.BatteryNetKwh != 77 || *pt.BatteryGrossKwh != 82 || *pt.Gearbox != "automatic" ||
		*pt.WltpRangeKm != 520 || *pt.WltpConsumption != 16.5 || *pt.Co2GKm != 0 {
		t.Fatalf("upsert powertrain: %+v", pt)
	}
	out := e.ok("show", car)
	if !strings.Contains(out, "powertrain: bev · battery 77/82 kWh · automatic · WLTP 520 km · 16.5 kWh/100 km · CO2 0 g/km") {
		t.Fatalf("show powertrain line:\n%s", out)
	}

	e.ok("set", car, "--engine-cc", "1 499", "--gearbox", "manual")
	e.ok("set", car, "--clear", "engine-cc", "--clear", "powertrain.co2_g_km", "--clear", "battery_gross_kwh")
	pt = e.show(car).Powertrain
	if pt.EngineCc != nil || pt.Co2GKm != nil || pt.BatteryGrossKwh != nil || *pt.Gearbox != "manual" || *pt.BatteryNetKwh != 77 {
		t.Fatalf("after set/clear: %+v", pt)
	}
	e.fails(2, "set", car, "--fuel", "steam")
	e.fails(2, "set", car, "--gearbox", "manual", "--clear", "gearbox")

	diesel := e.upsert("--url", "https://example.invalid/cli/pt2", "--make", "SYNTH", "--model", "Oil", "--price", "20000", "--fuel", "Gasóleo").CarID
	var l api.CarList
	e.okJSON(&l, "ls", "--fuel", "diesel,unknown")
	if len(l.Cars) != 1 || l.Cars[0].ID != diesel {
		t.Fatalf("ls --fuel diesel: %+v", l.Cars)
	}
	e.okJSON(&l, "ls", "--fuel", "electric")
	if len(l.Cars) != 1 || l.Cars[0].ID != r.CarID {
		t.Fatalf("ls --fuel electric: %+v", l.Cars)
	}
	e.ok("set", car, "--gearbox", "Automático")
	if g := *e.show(car).Powertrain.Gearbox; g != "automatic" {
		t.Fatalf("--gearbox Automático: %q", g)
	}
}

func TestCLIIfVersionConflict(t *testing.T) {
	e := newE2E(t)
	car := id(e.upsert("--url", "https://example.invalid/cli/v", "--make", "SYNTH", "--model", "Shared", "--price", "25000").CarID)
	v := e.show(car).Version
	if !strings.Contains(e.ok("show", car), fmt.Sprintf("version %d", v)) {
		t.Fatal("show does not print the version")
	}
	e.ok("set", car, "--summary", "agent A", "--if-version", fmt.Sprint(v))
	now := e.show(car).Version

	stderr := e.fails(1, "set", car, "--summary", "agent B", "--if-version", fmt.Sprint(v))
	if want := fmt.Sprintf("conflict: car changed (version %d)", now); !strings.Contains(stderr, want) {
		t.Fatalf("stderr %q, want %q", stderr, want)
	}
	if s := e.show(car).Summary; *s != "agent A" {
		t.Fatalf("stale set applied: %q", *s)
	}
	stderr = e.fails(1, "status", car, "talking", "--if-version", fmt.Sprint(v))
	if !strings.Contains(stderr, "conflict: car changed") {
		t.Fatalf("status stderr %q", stderr)
	}
	r := e.run("--json", "status", car, "talking", "--if-version", fmt.Sprint(v))
	var je map[string]any
	if r.code != 1 || json.Unmarshal([]byte(r.stderr), &je) != nil || je["status"] != float64(412) || je["version"] != float64(now) {
		t.Fatalf("--json conflict: %d %s", r.code, r.stderr)
	}
	e.ok("status", car, "talking", "--if-version", fmt.Sprint(now))
	if d := e.show(car); d.Status != "talking" {
		t.Fatalf("status with fresh version: %s", d.Status)
	}
	e.fails(2, "set", car, "--km", "1", "--if-version", "x")
}

func TestCLIListOps(t *testing.T) {
	e := newE2E(t)
	car := id(e.upsert("--url", "https://example.invalid/cli/l", "--make", "SYNTH", "--model", "Listy", "--price", "25000").CarID)
	e.ok("set", car, "--red-flag-add", "accident 2023")
	e.ok("set", car, "--red-flag-add", "no service book", "--question-add", "second key?")
	e.ok("set", car, "--red-flag-add", "accident 2023") // idempotent
	d := e.show(car)
	if !slices.Equal(d.RedFlags, []string{"accident 2023", "no service book"}) || !slices.Equal(d.OpenQuestions, []string{"second key?"}) {
		t.Fatalf("after adds: %q %q", d.RedFlags, d.OpenQuestions)
	}
	e.ok("set", car, "--red-flag-rm", "accident 2023", "--question-rm", "second key?", "--question-add", "tyres?")
	d = e.show(car)
	if !slices.Equal(d.RedFlags, []string{"no service book"}) || !slices.Equal(d.OpenQuestions, []string{"tyres?"}) {
		t.Fatalf("after removes: %q %q", d.RedFlags, d.OpenQuestions)
	}
	e.fails(2, "set", car, "--red-flag", "x", "--red-flag-add", "y")
}

func TestCLIPriceSanity(t *testing.T) {
	e := newE2E(t)
	u := "https://example.invalid/cli/p"
	stderr := e.fails(1, "upsert", "--url", u, "--make", "SYNTH", "--model", "Cents", "--price", "3 150 000")
	if !strings.Contains(stderr, "price_x100") || !strings.Contains(stderr, "--force") {
		t.Fatalf("x100 stderr: %q", stderr)
	}
	r := e.run("--json", "upsert", "--url", u, "--make", "SYNTH", "--model", "Cents", "--price", "399")
	var je map[string]any
	if r.code != 1 || json.Unmarshal([]byte(r.stderr), &je) != nil || je["reason"] != "price_lease" || je["status"] != float64(422) {
		t.Fatalf("--json lease rejection: %d %s", r.code, r.stderr)
	}
	e.fails(2, "upsert", "--url", u, "--price", "30000", "--price-vat", "incl")

	res := e.upsert("--url", u, "--make", "SYNTH", "--model", "Cents", "--price", "3150000", "--force")
	out := e.ok("listing", "show", id(res.ListingID))
	if !strings.Contains(out, "price forced past sanity check: price_x100") {
		t.Fatalf("listing show:\n%s", out)
	}
	e.fails(1, "listing", "set", id(res.ListingID), "--price", "29000", "--price-vat", "net")
	var l api.Listing
	e.okJSON(&l, "listing", "set", id(res.ListingID), "--price", "31500", "--price-vat", "gross")
	if *l.Price != 31500 || l.PriceVat != "gross" || len(l.PriceFlags) != 0 {
		t.Fatalf("listing set: %+v", l)
	}
	e.okJSON(&l, "listing", "set", id(res.ListingID), "--price", "450", "--force")
	if !slices.Equal(l.PriceFlags, []string{"price_lease"}) {
		t.Fatalf("listing set --force flags: %v", l.PriceFlags)
	}
}
