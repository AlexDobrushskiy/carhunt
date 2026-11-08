package setup

import (
	"crypto/rand"
	"encoding/base64"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/secrets"
)

// TokenSpec is one API token cardb init manages: the server-side token name and the secret holding the token.
type TokenSpec struct {
	Name   string // token name = default author (agents, web, the owner's name, a viewer's name)
	Secret string
}

var reSlug = regexp.MustCompile(`[^a-z0-9_.-]+`)

// Specs lists the tokens for a profile: agents (the default client token), web, the owner, each viewer.
func Specs(p *profile.Profile, agentsSecret string) ([]TokenSpec, error) {
	specs := []TokenSpec{{"agents", agentsSecret}, {"web", "cardb_web_token"}, {p.Owner.Name, "cardb_owner_token"}}
	for _, u := range p.Users() {
		if u.Role == "viewer" {
			slug := strings.Trim(reSlug.ReplaceAllString(strings.ToLower(u.Name), "_"), "_.-")
			specs = append(specs, TokenSpec{u.Name, "cardb_token_" + slug})
		}
	}
	names, secs := map[string]bool{}, map[string]bool{}
	for _, s := range specs {
		if s.Name == "" || strings.ContainsAny(s.Name, ":,#\n\r") || strings.TrimSpace(s.Name) != s.Name {
			return nil, fmt.Errorf("user name %q cannot be a token name (no : , # or surrounding spaces)", s.Name)
		}
		if names[strings.ToLower(s.Name)] {
			return nil, fmt.Errorf("user name %q collides with another token name (agents and web are built in)", s.Name)
		}
		if err := secrets.CheckName(s.Secret); err != nil {
			return nil, err
		}
		if secs[s.Secret] {
			return nil, fmt.Errorf("two users map to secret %s; rename one", s.Secret)
		}
		names[strings.ToLower(s.Name)], secs[s.Secret] = true, true
	}
	return specs, nil
}

// NewToken returns 32 random bytes, base64url without padding.
func NewToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

type tokenLine struct{ name, value string }

// readTokensFile returns the entries of an existing tokens file (nil when missing). Comments are dropped.
func readTokensFile(path string) ([]tokenLine, error) {
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	var out []tokenLine
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "#") {
			continue
		}
		for _, entry := range strings.Split(line, ",") { // same syntax as server.ParseTokens
			if entry = strings.TrimSpace(entry); entry == "" {
				continue
			}
			name, val, ok := strings.Cut(entry, ":")
			if !ok {
				return nil, fmt.Errorf("%s: bad entry (want name:sha256:<hex> or name:token)", path)
			}
			out = append(out, tokenLine{strings.TrimSpace(name), strings.TrimSpace(val)})
		}
	}
	return out, nil
}

func hashOf(v string) string {
	if strings.HasPrefix(v, HashPrefix) {
		return strings.ToLower(v)
	}
	return HashToken(v)
}

// Init runs `cardb init [--home DIR] [--backend keychain|file|op] [--rotate]`: creates the data dir, generates the
// API tokens, stores each in the secrets backend and writes their hashes to <data dir>/tokens. Never prints a token.
func Init(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	fs.SetOutput(stdout)
	homeFlag := fs.String("home", "", "carhunt home (default $CARHUNT_HOME or ~/.carhunt)")
	backendFlag := fs.String("backend", "", "secrets backend: keychain|file|op (default env CARHUNT_SECRETS_BACKEND, config secrets.backend, keychain on macOS)")
	rotate := fs.Bool("rotate", false, "generate new tokens even when the stored ones are valid")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() > 0 {
		return fmt.Errorf("usage: cardb init [--home DIR] [--backend keychain|file|op] [--rotate]")
	}
	home, cfgPath := Home(), profile.Resolve()
	if *homeFlag != "" {
		abs, err := filepath.Abs(expand(*homeFlag))
		if err != nil {
			return err
		}
		home = abs
		if os.Getenv("CARHUNT_CONFIG") == "" {
			cfgPath = filepath.Join(home, "config.yaml")
		}
	}
	prof, err := profile.Load(cfgPath)
	if errors.Is(err, os.ErrNotExist) {
		prof, err = profile.Default(), nil
		fmt.Fprintf(stdout, "no config at %s: owner %q, no viewers\n", cfgPath, prof.Owner.Name)
	}
	if err != nil {
		return err
	}
	cfg, err := LoadConfig(cfgPath)
	if err != nil {
		return err
	}
	backend, err := cfg.Backend(*backendFlag, home)
	if err != nil {
		return err
	}
	specs, err := Specs(prof, cfg.TokenSecret())
	if err != nil {
		return err
	}

	dataDir := DataDir(home, prof.Cardb.DataDir)
	if err := os.MkdirAll(dataDir, 0o700); err != nil {
		return err
	}
	if err := os.Chmod(dataDir, 0o700); err != nil {
		return err
	}
	tokPath := TokensFile(dataDir)
	old, err := readTokensFile(tokPath)
	if err != nil {
		return err
	}
	known := map[string]bool{}
	for _, l := range old {
		known[hashOf(l.value)] = true
	}

	var lines []string
	ours := map[string]bool{}
	for _, s := range specs {
		ours[strings.ToLower(s.Name)] = true
		cur, err := backend.Get(s.Secret)
		if err != nil && !errors.Is(err, secrets.ErrNotFound) {
			return err
		}
		action := "created"
		switch {
		case err == nil && !*rotate && known[HashToken(cur)]:
			action = "kept"
		default:
			if err == nil {
				action = "rotated"
			}
			if cur, err = NewToken(); err != nil {
				return err
			}
			if err := backend.Set(s.Secret, cur); err != nil {
				return err
			}
		}
		lines = append(lines, s.Name+":"+HashToken(cur))
		fmt.Fprintf(stdout, "%-7s token %-10s → secret %s (%s)\n", action, s.Name, s.Secret, backend.Name())
	}
	for _, l := range old { // hand-added tokens stay
		if !ours[strings.ToLower(l.name)] {
			lines = append(lines, l.name+":"+l.value)
		}
	}
	content := "# cardb API tokens (written by cardb init): name:sha256:<hex of sha256(token)>. The tokens live in the secrets backend.\n" +
		strings.Join(lines, "\n") + "\n"
	cur, _ := os.ReadFile(tokPath)
	if string(cur) == content {
		if err := os.Chmod(tokPath, 0o600); err != nil {
			return err
		}
		fmt.Fprintf(stdout, "unchanged %s\n", tokPath)
	} else {
		if err := writeFile0600(tokPath, content); err != nil {
			return err
		}
		fmt.Fprintf(stdout, "wrote %s\n", tokPath)
	}
	next := "cardb serve"
	if *homeFlag != "" && os.Getenv("CARHUNT_HOME") != home {
		next = "CARHUNT_HOME=" + home + " cardb serve"
	}
	fmt.Fprintf(stdout, "next: (re)start the server so it loads the tokens: %s\n", next)
	return nil
}

func writeFile0600(path, content string) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".tokens-")
	if err != nil {
		return err
	}
	if _, err := tmp.WriteString(content); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	return os.Rename(tmp.Name(), path)
}
