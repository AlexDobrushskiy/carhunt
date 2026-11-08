// Package server is the ev-listings HTTP API (`cardb serve`).
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
	"carhunt/cardb/internal/store"
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// ParseTokens parses "name:token" pairs separated by commas or newlines; # starts a comment line.
func ParseTokens(s string) (map[string]string, error) {
	out := map[string]string{}
	sc := bufio.NewScanner(strings.NewReader(strings.ReplaceAll(s, ",", "\n")))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		name, tok, ok := strings.Cut(line, ":")
		name, tok = strings.TrimSpace(name), strings.TrimSpace(tok)
		if !ok || name == "" || tok == "" {
			return nil, fmt.Errorf("bad token entry %q (want name:token)", line)
		}
		out[name] = tok
	}
	return out, sc.Err()
}

func loadTokens() (map[string]string, error) {
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
	if f := os.Getenv("CARDB_TOKENS_FILE"); f != "" {
		b, err := os.ReadFile(f)
		if err != nil {
			return nil, fmt.Errorf("CARDB_TOKENS_FILE: %w", err)
		}
		t, err := ParseTokens(string(b))
		if err != nil {
			return nil, fmt.Errorf("CARDB_TOKENS_FILE: %w", err)
		}
		for k, v := range t {
			tokens[k] = v
		}
	}
	if len(tokens) == 0 {
		return nil, errors.New("no API tokens: set CARDB_TOKENS (name:token,…) or CARDB_TOKENS_FILE")
	}
	return tokens, nil
}

// Main runs `cardb serve [-listen addr] [-data dir]` until ctx is cancelled.
func Main(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	listen := fs.String("listen", envOr("CARDB_LISTEN", "127.0.0.1:8484"), "listen address (env CARDB_LISTEN)")
	config := fs.String("config", profile.Resolve(), "buyer profile: carhunt config.yaml (env CARHUNT_CONFIG / CARHUNT_HOME); missing = neutral profile")
	dataDir := fs.String("data", envOr("CARDB_DATA_DIR", "./data"), "data directory (env CARDB_DATA_DIR)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, nil)))
	tokens, err := loadTokens()
	if err != nil {
		return err
	}
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
	st, err := store.Open(*dataDir)
	if err != nil {
		return err
	}
	defer st.Close()
	st.SetProfile(prof)

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

// Backup runs `cardb backup <dest.sqlite3>`: a VACUUM INTO snapshot of $CARDB_DATA_DIR/cardb.sqlite3.
func Backup(args []string) error {
	if len(args) != 1 || args[0] == "" {
		return errors.New("usage: cardb backup <dest.sqlite3>")
	}
	dataDir := envOr("CARDB_DATA_DIR", "./data")
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
