// Package setup resolves where cardb's local state lives ($CARHUNT_HOME, data dir, secrets backend, server URL) from
// the carhunt config, and implements `cardb init`.
package setup

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"go.yaml.in/yaml/v3"

	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/secrets"
)

// DefaultURL is the client's server URL when nothing is configured.
const DefaultURL = "http://127.0.0.1:8484"

// DefaultTokenSecret is the secret holding the default client token (the `agents` token).
const DefaultTokenSecret = "cardb_token"

// Home is $CARHUNT_HOME, else ~/.carhunt.
func Home() string {
	if h := os.Getenv("CARHUNT_HOME"); h != "" {
		return expand(h)
	}
	if h, err := os.UserHomeDir(); err == nil {
		return filepath.Join(h, ".carhunt")
	}
	return ".carhunt"
}

func expand(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if h, err := os.UserHomeDir(); err == nil {
			return filepath.Join(h, p[1:])
		}
	}
	return p
}

// Config is the part of the carhunt config cardb's local tooling reads (secrets backend, client URL/token ref).
// The buyer profile is read by package profile.
type Config struct {
	Cardb struct {
		URL     string `yaml:"url"`
		Token   string `yaml:"token"` // secret:<name> reference
		DataDir string `yaml:"data_dir"`
	} `yaml:"cardb"`
	Secrets secrets.Settings `yaml:"secrets"`
	Path    string           `yaml:"-"`
}

// LoadConfig reads the carhunt config at path (profile.Resolve() when ""); a missing file gives an empty Config.
func LoadConfig(path string) (*Config, error) {
	if path == "" {
		path = profile.Resolve()
	}
	c := &Config{Path: path}
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) || path == "" {
		return c, nil
	} else if err != nil {
		return nil, err
	}
	if err := yaml.NewDecoder(bytes.NewReader(b)).Decode(c); err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return c, nil
}

// TokenSecret is the secret name of the client token: `cardb.token: secret:<name>`, else cardb_token.
func (c *Config) TokenSecret() string {
	if n, ok := strings.CutPrefix(strings.TrimSpace(c.Cardb.Token), "secret:"); ok && n != "" {
		return n
	}
	return DefaultTokenSecret
}

// Backend opens the configured secrets backend under home (kind overrides, e.g. `cardb init --backend`).
func (c *Config) Backend(kind, home string) (secrets.Backend, error) {
	return secrets.Open(kind, c.Secrets, home)
}

// DataDir is the server data dir: env CARDB_DATA_DIR > config cardb.data_dir > <home>/cardb.
// In cardb.data_dir, $CARHUNT_HOME / ${CARHUNT_HOME} mean <home> and a relative path is relative to <home>,
// so a config copied between homes (tests, a second profile) never points at another home's data.
func DataDir(home, configured string) string {
	if d := os.Getenv("CARDB_DATA_DIR"); d != "" {
		return d
	}
	if configured == "" {
		return filepath.Join(home, "cardb")
	}
	for _, v := range []string{"${CARHUNT_HOME}", "$CARHUNT_HOME"} {
		configured = strings.ReplaceAll(configured, v, home)
	}
	configured = expand(configured)
	if !filepath.IsAbs(configured) {
		configured = filepath.Join(home, configured)
	}
	return configured
}

// HashPrefix marks a hashed tokens-file entry: `name:sha256:<64 hex of sha256(token)>`.
const HashPrefix = "sha256:"

// HashToken returns the tokens-file form of a token ("sha256:<hex>").
func HashToken(tok string) string {
	sum := sha256.Sum256([]byte(tok))
	return HashPrefix + hex.EncodeToString(sum[:])
}

// TokensFile is the server's default tokens file inside the data dir.
func TokensFile(dataDir string) string { return filepath.Join(dataDir, "tokens") }
