package cli_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The shipped config.example.yaml loads with zero warnings (every key it uses is known to cardb).
func TestProfileCheckConfigExample(t *testing.T) {
	e := newE2E(t)
	var out struct {
		OK       bool     `json:"ok"`
		Warnings []string `json:"warnings"`
	}
	e.okJSON(&out, "profile", "check", "../../../config.example.yaml")
	if !out.OK || len(out.Warnings) != 0 {
		t.Fatalf("config.example.yaml: %+v", out)
	}

	dir := t.TempDir()
	warn := filepath.Join(dir, "warn.yaml")
	bad := filepath.Join(dir, "bad.yaml")
	_ = os.WriteFile(warn, []byte("search:\n  max_distance_km: 900\n  models: [{make: X, model: Y, tier: 1, match: 'y'}]\n  bogus: 1\n"), 0o600)
	_ = os.WriteFile(bad, []byte("search:\n  powertrain: [steam]\n"), 0o600)
	if r := e.run("profile", "check", warn); r.code != 0 || !strings.Contains(r.stdout, "bogus") || strings.Contains(r.stdout, "max_distance_km") || strings.Contains(r.stdout, "match") {
		t.Fatalf("warn file: exit %d\n%s%s", r.code, r.stdout, r.stderr)
	}
	if r := e.run("profile", "check", bad); r.code == 0 || !strings.Contains(r.stderr, "steam") {
		t.Fatalf("bad file: exit %d\n%s%s", r.code, r.stdout, r.stderr)
	}
}
