// Package server is the cardb HTTP API (`cardb serve`).
//
// In-process use (tests, e2e):
//
//	st, _ := store.Open(t.TempDir())
//	h := server.NewHandler(st, map[string]string{"agents": "secret"}) // token name → token
//	srv := httptest.NewServer(h)                                      // API under srv.URL + "/api/v1"
package server

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/setup"
	"carhunt/cardb/internal/store"
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// ParseTokens parses "name:token" or "name:sha256:<hex>" pairs separated by commas or newlines; # starts a comment line.
func ParseTokens(s string) (map[string]string, error) {
	out := map[string]string{}
	sc := bufio.NewScanner(strings.NewReader(s))
	for sc.Scan() {
		if strings.HasPrefix(strings.TrimSpace(sc.Text()), "#") {
			continue
		}
		for _, entry := range strings.Split(sc.Text(), ",") {
			entry = strings.TrimSpace(entry)
			if entry == "" {
				continue
			}
			name, tok, ok := strings.Cut(entry, ":")
			name, tok = strings.TrimSpace(name), strings.TrimSpace(tok)
			if !ok || name == "" || tok == "" {
				return nil, fmt.Errorf("bad token entry (want name:token or name:sha256:<hex>)")
			}
			out[name] = tok
		}
	}
	return out, sc.Err()
}

// loadTokens reads CARDB_TOKENS and CARDB_TOKENS_FILE; when neither is set, <dataDir>/tokens (written by cardb init).
func loadTokens(dataDir string) (map[string]string, error) {
	tokens := map[string]string{}
	if v := os.Getenv("CARDB_TOKENS"); v != "" {
		t, err := ParseTokens(v)
		if err != nil {
			return nil, fmt.Errorf("CARDB_TOKENS: %w", err)
		}
		for k, v := range t {
			tokens[k] = v
		}
	}
	f := os.Getenv("CARDB_TOKENS_FILE")
	if f == "" && os.Getenv("CARDB_TOKENS") == "" {
		if _, err := os.Stat(setup.TokensFile(dataDir)); err == nil {
			f = setup.TokensFile(dataDir)
		}
	}
	if f != "" {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, fmt.Errorf("tokens file: %w", err)
		}
		t, err := ParseTokens(string(b))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		for k, v := range t {
			tokens[k] = v
		}
	}
	if len(tokens) == 0 {
		return nil, fmt.Errorf("no API tokens: run `cardb init` (writes %s), or set CARDB_TOKENS (name:token,…) / CARDB_TOKENS_FILE", setup.TokensFile(dataDir))
	}
	if _, err := tokenEntries(tokens); err != nil {
		return nil, err
	}
	return tokens, nil
}

// Main runs `cardb serve [-listen addr] [-data dir]` until ctx is cancelled.
func Main(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	listen := fs.String("listen", envOr("CARDB_LISTEN", "127.0.0.1:8484"), "listen address (env CARDB_LISTEN)")
	config := fs.String("config", profile.Resolve(), "buyer profile: carhunt config.yaml (env CARHUNT_CONFIG / CARHUNT_HOME); missing = neutral profile")
	dataDir := fs.String("data", "", "data directory (default env CARDB_DATA_DIR, config cardb.data_dir, $CARHUNT_HOME/cardb)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, nil)))
	prof := profile.Default()
	if *config != "" {
		p, err := profile.Load(*config)
		switch {
		case err == nil:
			prof = p
		case errors.Is(err, os.ErrNotExist):
			slog.Warn("no config file, using the neutral profile", "config", *config)
		default:
			return err
		}
	}
	if *dataDir == "" {
		*dataDir = setup.DataDir(setup.Home(), prof.Cardb.DataDir)
	}
	tokens, err := loadTokens(*dataDir)
	if err != nil {
		return err
	}
	st, err := store.Open(*dataDir)
	if err != nil {
		return err
	}
	defer st.Close()
	if err := st.SetProfile(prof); err != nil {
		return fmt.Errorf("sync users from the profile: %w", err)
	}

	srv := &http.Server{
		Addr:              *listen,
		Handler:           NewHandler(st, tokens),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       2 * time.Minute,
		WriteTimeout:      2 * time.Minute,
		IdleTimeout:       2 * time.Minute,
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	slog.Info("cardb serving", "listen", ln.Addr().String(), "data", *dataDir, "tokens", len(tokens), "version", api.Version)
	errc := make(chan error, 1)
	go func() { errc <- srv.Serve(ln) }()
	select {
	case err := <-errc:
		return err
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	slog.Info("cardb shutting down")
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return err
	}
	if err := <-errc; err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

// Backup runs `cardb backup <dest.sqlite3>`: a VACUUM INTO snapshot of <data dir>/cardb.sqlite3 (data dir as for serve).
func Backup(args []string) error {
	if len(args) != 1 || args[0] == "" {
		return errors.New("usage: cardb backup <dest.sqlite3>")
	}
	prof, err := profile.LoadDefault()
	if err != nil {
		return err
	}
	dataDir := setup.DataDir(setup.Home(), prof.Cardb.DataDir)
	if _, err := os.Stat(dataDir + "/cardb.sqlite3"); err != nil {
		return fmt.Errorf("no database in %s: %w", dataDir, err)
	}
	st, err := store.Open(dataDir)
	if err != nil {
		return err
	}
	defer st.Close()
	return st.BackupTo(context.Background(), args[0])
}

// Healthcheck GETs /healthz on the local listener ($CARDB_LISTEN); used by the Docker HEALTHCHECK.
func Healthcheck() error {
	listen := envOr("CARDB_LISTEN", "127.0.0.1:8484")
	host, port, err := net.SplitHostPort(listen)
	if err != nil {
		return fmt.Errorf("bad CARDB_LISTEN %q: %w", listen, err)
	}
	if host == "" || host == "0.0.0.0" || host == "::" {
		host = "127.0.0.1"
	}
	c := &http.Client{Timeout: 3 * time.Second}
	resp, err := c.Get("http://" + net.JoinHostPort(host, port) + "/healthz")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("healthz returned %s", resp.Status)
	}
	return nil
}
