package client

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"

	"carhunt/cardb/internal/secrets"
	"carhunt/cardb/internal/setup"
)

// Config is the client's resolved settings. Only URL and Author are stored in the client config file; the token
// comes from the env or the carhunt secrets backend (see Resolve).
type Config struct {
	URL         string `json:"url,omitempty"`
	Token       string `json:"-"`
	Author      string `json:"author,omitempty"`
	TokenSource string `json:"-"` // where Token came from (--token, CARDB_TOKEN, env, keychain:<name>, …) or why it is missing
}

// ConfigPath returns $CARDB_CONFIG, else ~/.config/cardb/config.json (XDG_CONFIG_HOME respected).
func ConfigPath() string {
	if p := os.Getenv("CARDB_CONFIG"); p != "" {
		return p
	}
	dir := os.Getenv("XDG_CONFIG_HOME")
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return filepath.Join(".config", "cardb", "config.json")
		}
		dir = filepath.Join(home, ".config")
	}
	return filepath.Join(dir, "cardb", "config.json")
}

// LoadConfigFile reads the config file (url, author; a legacy `token` key is ignored); a missing file yields an empty Config.
func LoadConfigFile(path string) (Config, error) {
	var c Config
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return c, nil
	}
	if err != nil {
		return c, err
	}
	if err := json.Unmarshal(data, &c); err != nil {
		return c, fmt.Errorf("parse %s: %w", path, err)
	}
	return c, nil
}

// SaveConfigFile writes url + author with 0600 permissions (a token from an older file is dropped).
func SaveConfigFile(path string, c Config) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(Config{URL: c.URL, Author: c.Author}, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Resolve merges config sources:
//   - URL: override (--server) > CARDB_URL > client config file > carhunt config cardb.url > http://127.0.0.1:8484
//   - Token: override (--token) > CARDB_TOKEN > secret cardb_token (or cardb.token: secret:<name>): env
//     CARHUNT_SECRET_CARDB_TOKEN, then the configured secrets backend
//   - Author: override (--author) > CARDB_AUTHOR > client config file > none (the server uses the token name)
func Resolve(override Config) (Config, error) {
	file, err := LoadConfigFile(ConfigPath())
	ch, cerr := setup.LoadConfig("")
	if cerr != nil {
		ch = &setup.Config{} // a broken carhunt config must not lock the client out
	}
	pick := func(vals ...string) string {
		for _, v := range vals {
			if v != "" {
				return v
			}
		}
		return ""
	}
	c := Config{
		URL:    pick(override.URL, os.Getenv("CARDB_URL"), file.URL, ch.Cardb.URL, setup.DefaultURL),
		Author: pick(override.Author, os.Getenv("CARDB_AUTHOR"), file.Author),
	}
	switch {
	case override.Token != "":
		c.Token, c.TokenSource = override.Token, "--token"
	case os.Getenv("CARDB_TOKEN") != "":
		c.Token, c.TokenSource = os.Getenv("CARDB_TOKEN"), "CARDB_TOKEN"
	default:
		name := ch.TokenSecret()
		b, berr := ch.Backend("", setup.Home())
		if berr != nil {
			b = nil
		}
		tok, src, terr := secrets.Get(b, name)
		switch {
		case terr == nil:
			c.Token, c.TokenSource = tok, src+":"+name
			if src == "env" {
				c.TokenSource = secrets.EnvVar(name)
			}
		case errors.Is(terr, secrets.ErrNotFound) && berr == nil:
			c.TokenSource = fmt.Sprintf("not found (CARDB_TOKEN, %s, %s:%s; run `cardb init`)", secrets.EnvVar(name), b.Name(), name)
		case berr != nil:
			c.TokenSource = fmt.Sprintf("not found (CARDB_TOKEN, %s; secrets backend: %v)", secrets.EnvVar(name), berr)
		default:
			c.TokenSource = "lookup failed: " + terr.Error()
		}
	}
	return c, err
}

// FromEnv builds a client from Resolve(override).
func FromEnv(override Config) (*Client, error) {
	c, err := Resolve(override)
	if err != nil {
		return nil, err
	}
	cl := New(c.URL, c.Token, c.Author)
	cl.TokenSource = c.TokenSource
	return cl, nil
}
