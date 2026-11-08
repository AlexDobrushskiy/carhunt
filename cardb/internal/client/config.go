package client

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

// Config is the on-disk client config (~/.config/cardb/config.json).
type Config struct {
	URL    string `json:"url,omitempty"`
	Token  string `json:"token,omitempty"`
	Author string `json:"author,omitempty"`
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

// LoadConfigFile reads the config file; a missing file yields an empty Config.
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

// SaveConfigFile writes the config with 0600 permissions.
func SaveConfigFile(path string, c Config) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Resolve merges config sources. Precedence per field: explicit override > env > config file.
// Author additionally falls back to $AGTERM_SESSION_ID before the config file's author.
func Resolve(override Config) (Config, error) {
	file, err := LoadConfigFile(ConfigPath())
	pick := func(vals ...string) string {
		for _, v := range vals {
			if v != "" {
				return v
			}
		}
		return ""
	}
	c := Config{
		URL:    pick(override.URL, os.Getenv("CARDB_URL"), file.URL),
		Token:  pick(override.Token, os.Getenv("CARDB_TOKEN"), file.Token),
		Author: pick(override.Author, os.Getenv("CARDB_AUTHOR"), os.Getenv("AGTERM_SESSION_ID"), file.Author),
	}
	return c, err
}

// FromEnv builds a client from Resolve(override).
func FromEnv(override Config) (*Client, error) {
	c, err := Resolve(override)
	if err != nil {
		return nil, err
	}
	return New(c.URL, c.Token, c.Author), nil
}
