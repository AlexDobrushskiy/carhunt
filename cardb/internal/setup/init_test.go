package setup_test

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"carhunt/cardb/internal/cli"
	"carhunt/cardb/internal/server"
	"carhunt/cardb/internal/setup"
)

// isolate points every carhunt/cardb setting at a fresh temp home (file secrets backend via config).
func isolate(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	for _, k := range []string{"CARHUNT_HOME", "CARHUNT_CONFIG", "CARHUNT_SECRETS_BACKEND", "CARHUNT_SECRET_CARDB_TOKEN",
		"CARDB_DATA_DIR", "CARDB_TOKENS", "CARDB_TOKENS_FILE", "CARDB_URL", "CARDB_TOKEN", "CARDB_AUTHOR"} {
		t.Setenv(k, "")
	}
	t.Setenv("CARDB_CONFIG", filepath.Join(home, "client.json"))
	cfg := "owner: {name: Sam}\ncardb:\n  users: [{name: Bea}]\nsecrets: {backend: file}\n"
	if err := os.WriteFile(filepath.Join(home, "config.yaml"), []byte(cfg), 0o600); err != nil {
		t.Fatal(err)
	}
	return home
}

func perm(t *testing.T, path string) os.FileMode {
	t.Helper()
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return st.Mode().Perm()
}

func runInit(t *testing.T, args ...string) string {
	t.Helper()
	var out bytes.Buffer
	if err := setup.Init(args, &out); err != nil {
		t.Fatalf("init %v: %v", args, err)
	}
	return out.String()
}

// secretsOf reads every stored token (never printed; tests compare them only).
func secretsOf(t *testing.T, home string) map[string]string {
	t.Helper()
	out := map[string]string{}
	for _, n := range []string{"cardb_token", "cardb_owner_token", "cardb_token_bea", "cardb_web_tokens"} {
		b, err := os.ReadFile(filepath.Join(home, "secrets", n))
		if err != nil {
			t.Fatalf("secret %s: %v", n, err)
		}
		if perm(t, filepath.Join(home, "secrets", n)) != 0o600 {
			t.Errorf("secret %s mode %v", n, perm(t, filepath.Join(home, "secrets", n)))
		}
		out[n] = string(b)
	}
	return out
}

// TestInitFileBackend: `cardb init --home` on a temp home with the file backend creates the data dir, four tokens in
// the backend and their hashes in <data>/tokens; a second run is a no-op; --rotate replaces them; `cardb serve` with
// default settings accepts the agents token, which the CLI reads from the backend by itself.
func TestInitFileBackend(t *testing.T) {
	home := isolate(t)
	out1 := runInit(t, "--home", home)
	data := filepath.Join(home, "cardb")
	if perm(t, data) != 0o700 || perm(t, filepath.Join(home, "secrets")) != 0o700 || perm(t, filepath.Join(data, "tokens")) != 0o600 {
		t.Fatalf("modes: data %v secrets %v tokens %v", perm(t, data), perm(t, filepath.Join(home, "secrets")), perm(t, filepath.Join(data, "tokens")))
	}
	sec := secretsOf(t, home)
	for k, v := range sec {
		if k != "cardb_web_tokens" && (len(v) != 43 || strings.Contains(out1, v)) {
			t.Fatal("token has the wrong shape or was printed")
		}
	}
	// The web gets each user's own token, named after the user; never the agents token.
	if sec["cardb_web_tokens"] != "Sam:"+sec["cardb_owner_token"]+"\nBea:"+sec["cardb_token_bea"] {
		t.Fatal("cardb_web_tokens is not the owner + viewer name:token lines")
	}
	tokens, _ := os.ReadFile(filepath.Join(data, "tokens"))
	for name, secret := range map[string]string{"agents": "cardb_token", "Sam": "cardb_owner_token", "Bea": "cardb_token_bea"} {
		if !strings.Contains(string(tokens), "\n"+name+":"+setup.HashToken(sec[secret])+"\n") {
			t.Errorf("tokens file lacks the hash of %s for %s", secret, name)
		}
		if strings.Contains(string(tokens), sec[secret]) {
			t.Fatal("tokens file holds a plain token")
		}
	}
	// Each composite line's token is the one the server accepts under that name (hash in the tokens file).
	for _, line := range strings.Split(sec["cardb_web_tokens"], "\n") {
		name, tok, _ := strings.Cut(line, ":")
		if !strings.Contains(string(tokens), "\n"+name+":"+setup.HashToken(tok)+"\n") {
			t.Errorf("cardb_web_tokens entry %s does not match the tokens file", name)
		}
	}
	if strings.Count(out1, "created") != 3 || !strings.Contains(out1, "wrote   web tokens") || !strings.Contains(out1, "next: ") ||
		strings.Contains(string(tokens), "\nweb:") {
		t.Errorf("first run output:\n%s", out1)
	}

	out2 := runInit(t, "--home", home)
	tokens2, _ := os.ReadFile(filepath.Join(data, "tokens"))
	if strings.Count(out2, "kept") != 4 || !strings.Contains(out2, "unchanged") || string(tokens2) != string(tokens) {
		t.Fatalf("second run is not a no-op:\n%s", out2)
	}
	for k, v := range secretsOf(t, home) {
		if sec[k] != v {
			t.Fatalf("second run changed %s", k)
		}
	}

	// A hand-added token survives; --rotate replaces ours.
	if err := os.WriteFile(filepath.Join(data, "tokens"), append(tokens2, []byte("extra:"+setup.HashToken("x")+"\n")...), 0o600); err != nil {
		t.Fatal(err)
	}
	out3 := runInit(t, "--home", home, "--rotate")
	rot := secretsOf(t, home)
	tokens3, _ := os.ReadFile(filepath.Join(data, "tokens"))
	if strings.Count(out3, "rotated") != 3 || rot["cardb_token"] == sec["cardb_token"] || !strings.Contains(string(tokens3), "extra:") ||
		rot["cardb_web_tokens"] != "Sam:"+rot["cardb_owner_token"]+"\nBea:"+rot["cardb_token_bea"] ||
		strings.Contains(string(tokens3), setup.HashToken(sec["cardb_token"])) {
		t.Fatalf("rotate:\n%s", out3)
	}

	// The real user flow: serve with defaults (CARHUNT_HOME → data dir → tokens file), CLI token from the backend.
	t.Setenv("CARHUNT_HOME", home)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	ln.Close()
	t.Setenv("CARDB_LISTEN", addr)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- server.Main(ctx, nil) }()
	t.Cleanup(func() {
		cancel()
		if err := <-done; err != nil {
			t.Errorf("serve: %v", err)
		}
		slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	})
	base := "http://" + addr
	for i := 0; ; i++ {
		resp, err := http.Get(base + "/healthz")
		if err == nil {
			resp.Body.Close()
			break
		}
		if i > 100 {
			t.Fatalf("server did not start: %v", err)
		}
		time.Sleep(20 * time.Millisecond)
	}
	if _, err := os.Stat(filepath.Join(data, "cardb.sqlite3")); err != nil {
		t.Fatalf("serve did not use the init data dir: %v", err)
	}
	var cout, cerr bytes.Buffer
	if code := cli.Run(context.Background(), []string{"--server", base, "stats", "--json"}, &cout, &cerr); code != 0 {
		t.Fatalf("cli stats with the backend token: %d %s", code, cerr.String())
	}
	// The owner's own token (what the web uses for the owner) writes as the owner with full access.
	call := func(method, path, tok, body string) (int, string) {
		req, _ := http.NewRequest(method, base+path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+tok)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return resp.StatusCode, string(b)
	}
	if code, _ := call("POST", "/api/v1/listings/upsert", rot["cardb_owner_token"], `{"url": "https://example.invalid/init/1", "make": "SYNTH"}`); code != 200 {
		t.Fatalf("owner token upsert: %d", code)
	}
	if code, body := call("POST", "/api/v1/cars/1/notes", rot["cardb_owner_token"], `{"text": "mine"}`); code != 201 ||
		!strings.Contains(body, `"author":"Sam"`) || !strings.Contains(body, `"author_kind":"owner"`) {
		t.Fatalf("owner token note: %d %s", code, body)
	}
	req, _ := http.NewRequest("PATCH", base+"/api/v1/cars/1", strings.NewReader(`{"km": 1}`))
	req.Header.Set("Authorization", "Bearer "+rot["cardb_token_bea"])
	resp, err := http.DefaultClient.Do(req)
	if err != nil || resp.StatusCode != http.StatusForbidden {
		t.Fatalf("viewer token PATCH: %v %v", status(resp), err)
	}
	resp.Body.Close()
	req, _ = http.NewRequest("GET", base+"/api/v1/stats", nil)
	req.Header.Set("Authorization", "Bearer "+sec["cardb_token"]) // rotated away
	if resp, err = http.DefaultClient.Do(req); err != nil || resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("old token after rotate: %v %v", status(resp), err)
	}
	resp.Body.Close()
}

func status(r *http.Response) int {
	if r == nil {
		return 0
	}
	return r.StatusCode
}
