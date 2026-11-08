package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

// defaultSmokeURL is the compose/`cardb serve` default listener.
const defaultSmokeURL = "http://127.0.0.1:8484"

// smokeTarget picks the server the live smoke test talks to: CARDB_SMOKE_URL, else CARDB_URL, else localhost.
// A non-loopback host is refused unless CARDB_E2E_ALLOW_REMOTE=1, so a stray env or config can't point a test run
// at a production server.
func smokeTarget(getenv func(string) string) (string, error) {
	raw := getenv("CARDB_SMOKE_URL")
	if raw == "" {
		raw = getenv("CARDB_URL")
	}
	if raw == "" {
		raw = defaultSmokeURL
	}
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" {
		return "", fmt.Errorf("bad server URL %q (want http(s)://host[:port])", raw)
	}
	if !isLoopbackHost(u.Hostname()) && getenv("CARDB_E2E_ALLOW_REMOTE") != "1" {
		return "", fmt.Errorf("refusing non-localhost server %q: set CARDB_E2E_ALLOW_REMOTE=1 to run against it", raw)
	}
	return strings.TrimRight(raw, "/"), nil
}

func isLoopbackHost(host string) bool {
	h := strings.ToLower(strings.TrimSuffix(host, "."))
	if h == "localhost" || strings.HasSuffix(h, ".localhost") {
		return true
	}
	ip := net.ParseIP(h)
	return ip != nil && ip.IsLoopback()
}

func TestSmokeTargetGuard(t *testing.T) {
	cases := []struct {
		name string
		env  map[string]string
		want string // "" = refused
	}{
		{"default", nil, defaultSmokeURL},
		{"localhost name", map[string]string{"CARDB_SMOKE_URL": "http://localhost:9000/"}, "http://localhost:9000"},
		{"ipv6 loopback", map[string]string{"CARDB_SMOKE_URL": "http://[::1]:8484"}, "http://[::1]:8484"},
		{"127/8", map[string]string{"CARDB_URL": "http://127.0.0.2:8484"}, "http://127.0.0.2:8484"},
		{"smoke url beats client url", map[string]string{"CARDB_SMOKE_URL": "http://127.0.0.1:1", "CARDB_URL": "https://cardb.example.invalid"}, "http://127.0.0.1:1"},
		{"remote refused", map[string]string{"CARDB_URL": "https://cardb.example.invalid"}, ""},
		{"lan ip refused", map[string]string{"CARDB_SMOKE_URL": "http://192.0.2.10:8484"}, ""},
		{"localhost lookalike refused", map[string]string{"CARDB_SMOKE_URL": "http://localhost.example.invalid"}, ""},
		{"allow flag must be exactly 1", map[string]string{"CARDB_URL": "https://cardb.example.invalid", "CARDB_E2E_ALLOW_REMOTE": "yes"}, ""},
		{"remote allowed", map[string]string{"CARDB_URL": "https://cardb.example.invalid", "CARDB_E2E_ALLOW_REMOTE": "1"}, "https://cardb.example.invalid"},
		{"bad scheme", map[string]string{"CARDB_SMOKE_URL": "ftp://127.0.0.1"}, ""},
		{"no host", map[string]string{"CARDB_SMOKE_URL": "127.0.0.1:8484"}, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := smokeTarget(func(k string) string { return c.env[k] })
			if c.want == "" {
				if err == nil {
					t.Fatalf("want refusal, got %q", got)
				}
				return
			}
			if err != nil || got != c.want {
				t.Fatalf("got %q, %v; want %q", got, err, c.want)
			}
		})
	}
}

// TestLiveSmoke checks a running cardb read-only, through the real CLI and client config (token: --token resolution
// as for any agent: CARDB_TOKEN env, else the configured lookup). No writes, no car ids.
// Run: CARDB_SMOKE=1 go test ./internal/cli -run TestLiveSmoke -count=1 -v   (server: CARDB_SMOKE_URL, default localhost)
func TestLiveSmoke(t *testing.T) {
	if os.Getenv("CARDB_SMOKE") != "1" {
		t.Skip("set CARDB_SMOKE=1 to run against a running server")
	}
	base, err := smokeTarget(os.Getenv)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("server %s", base)

	hc := &http.Client{Timeout: 5 * time.Second}
	resp, err := hc.Get(base + "/healthz")
	if err != nil {
		t.Fatalf("/healthz: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/healthz: %s", resp.Status)
	}
	// Auth is enforced: a protected route without a token must be 401, never data.
	resp, err = hc.Get(base + "/api/v1/stats")
	if err != nil {
		t.Fatalf("/api/v1/stats: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("/api/v1/stats without a token: %s, want 401", resp.Status)
	}

	run := func(dst any, args ...string) {
		t.Helper()
		var out, errb bytes.Buffer
		full := append([]string{"--server", base, "--json"}, args...)
		if code := Run(context.Background(), full, &out, &errb); code != ExitOK {
			t.Fatalf("cardb %s: exit %d: %s", strings.Join(args, " "), code, errb.String())
		}
		if err := json.Unmarshal(out.Bytes(), dst); err != nil {
			t.Fatalf("cardb %s: decode: %v", strings.Join(args, " "), err)
		}
	}

	var health struct {
		OK      bool   `json:"ok"`
		Version string `json:"version"`
	}
	run(&health, "health")
	if !health.OK {
		t.Fatal("health: ok=false")
	}

	var stats struct {
		Total    *int           `json:"total"`
		ByStatus map[string]int `json:"by_status"`
	}
	run(&stats, "stats")
	if stats.Total == nil || stats.ByStatus == nil {
		t.Fatal("stats: missing total/by_status (token rejected or contract drift)")
	}

	var list struct {
		Total *int              `json:"total"`
		Cars  []json.RawMessage `json:"cars"`
	}
	run(&list, "ls", "--limit", "5")
	if list.Total == nil || len(list.Cars) > 5 {
		t.Fatalf("ls: total=%v, %d cars (limit 5)", list.Total, len(list.Cars))
	}

	var queue struct {
		Total  *int              `json:"total"`
		Counts map[string]int    `json:"counts"`
		Items  []json.RawMessage `json:"items"`
	}
	run(&queue, "queue", "--limit", "5")
	if queue.Total == nil || queue.Counts == nil {
		t.Fatal("queue: missing total/counts")
	}
	t.Logf("version %s · %d cars · %d listed · queue %d %v", health.Version, *stats.Total, len(list.Cars), *queue.Total, queue.Counts)
}
