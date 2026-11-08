// Package secrets reads and writes named secrets with the same storage conventions as carhunt's Python core
// (carhunt/core/secrets.py), so either side reads what the other wrote.
//
// Lookup: env CARHUNT_SECRET_<NAME> → backend. Backend: env CARHUNT_SECRETS_BACKEND > config `secrets.backend` >
// keychain on macOS, file elsewhere.
//   - keychain: macOS generic password, service `carhunt` (config secrets.keychain_service), account NAME; the value
//     is stored raw when printable ASCII, else as `b64:<base64>`; written through `security -i` with the value as hex
//     on stdin, so it never appears in a process list.
//   - file: $CARHUNT_HOME/secrets/NAME (dir 0700, file 0600).
//   - op: 1Password CLI, `op read op://<vault>/<NAME>/password` (vault: config secrets.op_vault, default carhunt);
//     written from a 0600 temp template file.
//
// Nothing here prints a value: callers get it as a return value.
package secrets

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"unicode"
)

// Backends lists the accepted backend names.
var Backends = []string{"keychain", "op", "file"}

// ErrNotFound: the secret is in neither the env nor the backend.
var ErrNotFound = errors.New("secret not found")

var reName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`)

// CheckName rejects names that could escape their directory or break a keychain command line.
func CheckName(name string) error {
	if !reName.MatchString(name) || strings.Contains(name, "..") {
		return fmt.Errorf("invalid secret name %q (letters, digits, _ . - ; max 64)", name)
	}
	return nil
}

// EnvVar is the env override for a secret: CARHUNT_SECRET_<NAME upper, other chars → _>.
func EnvVar(name string) string {
	var b strings.Builder
	for _, r := range strings.ToUpper(name) {
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
		} else {
			b.WriteByte('_')
		}
	}
	return "CARHUNT_SECRET_" + b.String()
}

// Settings is the config `secrets` section.
type Settings struct {
	Backend         string `yaml:"backend"`
	KeychainService string `yaml:"keychain_service"`
	OpVault         string `yaml:"op_vault"`
}

// Backend stores secrets by name. Get returns ErrNotFound when the name is absent.
type Backend interface {
	Name() string
	Get(name string) (string, error)
	Set(name, value string) error
}

// Open picks the backend: kind (e.g. a --backend flag) > env CARHUNT_SECRETS_BACKEND > s.Backend > platform default.
// home is $CARHUNT_HOME (the file backend's root is home/secrets).
func Open(kind string, s Settings, home string) (Backend, error) {
	for _, k := range []string{kind, os.Getenv("CARHUNT_SECRETS_BACKEND"), s.Backend} {
		if k != "" {
			kind = k
			break
		}
	}
	if kind == "" {
		kind = "file"
		if runtime.GOOS == "darwin" {
			kind = "keychain"
		}
	}
	switch kind {
	case "keychain":
		svc := s.KeychainService
		if svc == "" {
			svc = "carhunt"
		}
		if err := CheckName(svc); err != nil {
			return nil, fmt.Errorf("secrets.keychain_service: %w", err)
		}
		return Keychain{Service: svc}, nil
	case "op":
		v := s.OpVault
		if v == "" {
			v = "carhunt"
		}
		return Op{Vault: v}, nil
	case "file":
		return File{Dir: filepath.Join(home, "secrets")}, nil
	}
	return nil, fmt.Errorf("unknown secrets backend %q (one of %s)", kind, strings.Join(Backends, ", "))
}

// Get returns a secret: env CARHUNT_SECRET_<NAME> first, then b. source = "env" or the backend name.
func Get(b Backend, name string) (value, source string, err error) {
	if err := CheckName(name); err != nil {
		return "", "", err
	}
	if v := os.Getenv(EnvVar(name)); v != "" {
		return v, "env", nil
	}
	if b == nil {
		return "", "", ErrNotFound
	}
	v, err := b.Get(name)
	return v, b.Name(), err
}

// --- file ------------------------------------------------------------------------

// File keeps one secret per file under Dir (0700), files 0600.
type File struct{ Dir string }

func (File) Name() string { return "file" }

func (f File) Get(name string) (string, error) {
	if err := CheckName(name); err != nil {
		return "", err
	}
	b, err := os.ReadFile(filepath.Join(f.Dir, name))
	if errors.Is(err, os.ErrNotExist) {
		return "", ErrNotFound
	} else if err != nil {
		return "", err
	}
	return strings.TrimSuffix(string(b), "\n"), nil
}

func (f File) Set(name, value string) error {
	if err := CheckName(name); err != nil {
		return err
	}
	if err := os.MkdirAll(f.Dir, 0o700); err != nil {
		return err
	}
	if err := os.Chmod(f.Dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(f.Dir, ".tmp-") // 0600
	if err != nil {
		return err
	}
	if _, err := tmp.WriteString(value); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	return os.Rename(tmp.Name(), filepath.Join(f.Dir, name))
}

// --- keychain --------------------------------------------------------------------

// Keychain uses the macOS login keychain (generic passwords: service, account = name) via `security`.
type Keychain struct{ Service string }

func (Keychain) Name() string { return "keychain" }

func (k Keychain) Get(name string) (string, error) {
	if err := CheckName(name); err != nil {
		return "", err
	}
	var out, errb bytes.Buffer
	cmd := exec.Command("security", "find-generic-password", "-s", k.Service, "-a", name, "-w")
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) && ee.ExitCode() == 44 {
			return "", ErrNotFound
		}
		return "", fmt.Errorf("keychain read of %s failed: %w", name, err)
	}
	v := strings.TrimSuffix(out.String(), "\n")
	if enc, ok := strings.CutPrefix(v, "b64:"); ok {
		d, err := base64.StdEncoding.DecodeString(enc)
		if err != nil {
			return "", fmt.Errorf("keychain value of %s: bad b64: prefix", name)
		}
		return string(d), nil
	}
	return v, nil
}

func printableASCII(s string) bool {
	for _, r := range s {
		if r > unicode.MaxASCII || !unicode.IsPrint(r) {
			return false
		}
	}
	return true
}

func (k Keychain) Set(name, value string) error {
	if err := CheckName(name); err != nil {
		return err
	}
	raw := value
	if !printableASCII(value) {
		raw = "b64:" + base64.StdEncoding.EncodeToString([]byte(value))
	}
	line := fmt.Sprintf("add-generic-password -U -s %s -a %s -l carhunt -X %s\n", k.Service, name, hex.EncodeToString([]byte(raw)))
	var errb bytes.Buffer
	cmd := exec.Command("security", "-i")
	cmd.Stdin, cmd.Stdout, cmd.Stderr = strings.NewReader(line), nil, &errb
	err := cmd.Run()
	if err != nil || strings.Contains(strings.ToLower(errb.String()), "error") {
		return fmt.Errorf("keychain write of %s failed", name)
	}
	return nil
}

// --- 1Password -------------------------------------------------------------------

// Op uses the 1Password CLI: item title = name in Vault, field `password`.
type Op struct{ Vault string }

func (Op) Name() string { return "op" }

func (o Op) Get(name string) (string, error) {
	if err := CheckName(name); err != nil {
		return "", err
	}
	var out, errb bytes.Buffer
	cmd := exec.Command("op", "read", fmt.Sprintf("op://%s/%s/password", o.Vault, name))
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		msg := strings.ToLower(errb.String())
		if strings.Contains(msg, "isn't an item") || strings.Contains(msg, "not found") {
			return "", ErrNotFound
		}
		return "", fmt.Errorf("op read of %s failed: %w", name, err)
	}
	return strings.TrimSuffix(out.String(), "\n"), nil
}

func (o Op) Set(name, value string) error {
	if err := CheckName(name); err != nil {
		return err
	}
	_ = exec.Command("op", "item", "delete", name, "--vault", o.Vault).Run()
	tpl, _ := json.Marshal(map[string]any{"title": name, "category": "PASSWORD", "fields": []map[string]string{
		{"id": "password", "type": "CONCEALED", "purpose": "PASSWORD", "value": value}}})
	f, err := os.CreateTemp("", "carhunt-op-*.json") // 0600, removed right after
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err := f.Write(tpl); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := exec.Command("op", "item", "create", "--vault", o.Vault, "--template", f.Name()).Run(); err != nil {
		return fmt.Errorf("op write of %s failed: %w", name, err)
	}
	return nil
}
