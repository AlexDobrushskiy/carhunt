package secrets

import (
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestEnvVarAndLookupOrder(t *testing.T) {
	if got := EnvVar("cardb_token_bea.x"); got != "CARHUNT_SECRET_CARDB_TOKEN_BEA_X" {
		t.Fatalf("EnvVar = %s", got)
	}
	dir := t.TempDir()
	f := File{Dir: filepath.Join(dir, "secrets")}
	if _, err := f.Get("cardb_token"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing secret: %v", err)
	}
	if err := f.Set("cardb_token", "from-file"); err != nil {
		t.Fatal(err)
	}
	if st, _ := os.Stat(f.Dir); st.Mode().Perm() != 0o700 {
		t.Fatalf("dir mode %v", st.Mode().Perm())
	}
	if st, _ := os.Stat(filepath.Join(f.Dir, "cardb_token")); st.Mode().Perm() != 0o600 {
		t.Fatalf("file mode %v", st.Mode().Perm())
	}
	t.Setenv("CARHUNT_SECRET_CARDB_TOKEN", "")
	if v, src, err := Get(f, "cardb_token"); err != nil || v != "from-file" || src != "file" {
		t.Fatalf("file lookup: %q %s %v", v, src, err)
	}
	t.Setenv("CARHUNT_SECRET_CARDB_TOKEN", "from-env")
	if v, src, _ := Get(f, "cardb_token"); v != "from-env" || src != "env" {
		t.Fatalf("env must win: %q %s", v, src)
	}
	if _, _, err := Get(f, "../x"); err == nil {
		t.Fatal("path-escaping name accepted")
	}
	// The Python side writes a trailing-newline-free file; a hand-written file with "\n" reads the same.
	_ = os.WriteFile(filepath.Join(f.Dir, "hand"), []byte("v\n"), 0o600)
	if v, _ := f.Get("hand"); v != "v" {
		t.Fatalf("trailing newline kept: %q", v)
	}
}

func TestOpenBackendChoice(t *testing.T) {
	t.Setenv("CARHUNT_SECRETS_BACKEND", "")
	b, _ := Open("", Settings{Backend: "file"}, "/h")
	if fb, ok := b.(File); !ok || fb.Dir != "/h/secrets" {
		t.Fatalf("config backend: %#v", b)
	}
	t.Setenv("CARHUNT_SECRETS_BACKEND", "op")
	if b, _ := Open("", Settings{Backend: "file"}, "/h"); b.Name() != "op" {
		t.Fatalf("env must beat config: %s", b.Name())
	}
	if b, _ := Open("keychain", Settings{KeychainService: "svc"}, "/h"); b.(Keychain).Service != "svc" {
		t.Fatalf("flag must beat env: %#v", b)
	}
	if _, err := Open("vault", Settings{}, "/h"); err == nil {
		t.Fatal("unknown backend accepted")
	}
}

// TestKeychainProtocol drives Keychain against a fake `security` that records its argv and stdin: the value goes in
// as hex on stdin (never in argv), reads use -w, exit 44 = missing, `b64:` values are decoded.
func TestKeychainProtocol(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell script stub")
	}
	bin, log := t.TempDir(), t.TempDir()
	script := `#!/bin/sh
echo "$@" >> "` + log + `/argv"
case "$1" in
  -i) cat >> "` + log + `/stdin" ;;
  find-generic-password)
    case "$5" in
      missing) exit 44 ;;
      binary) printf 'b64:%s\n' "$(printf 'caf\303\251' | base64)" ;;
      *) printf 'plain-value\n' ;;
    esac ;;
esac
`
	if err := os.WriteFile(filepath.Join(bin, "security"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	k := Keychain{Service: "carhunt"}
	if err := k.Set("cardb_token", "s3cret-value"); err != nil {
		t.Fatal(err)
	}
	argv, _ := os.ReadFile(filepath.Join(log, "argv"))
	stdin, _ := os.ReadFile(filepath.Join(log, "stdin"))
	if strings.Contains(string(argv), "s3cret") || strings.TrimSpace(string(argv)) != "-i" {
		t.Fatalf("value or extra args on argv: %q", argv)
	}
	want := "add-generic-password -U -s carhunt -a cardb_token -l carhunt -X " + hex.EncodeToString([]byte("s3cret-value")) + "\n"
	if string(stdin) != want {
		t.Fatalf("stdin = %q, want %q", stdin, want)
	}
	if err := k.Set("bin", "café"); err != nil {
		t.Fatal(err)
	}
	stdin, _ = os.ReadFile(filepath.Join(log, "stdin"))
	if !strings.Contains(string(stdin), hex.EncodeToString([]byte("b64:Y2Fmw6k="))) {
		t.Fatalf("non-ASCII value not stored as b64: %q", stdin)
	}
	if v, err := k.Get("cardb_token"); err != nil || v != "plain-value" {
		t.Fatalf("get: %q %v", v, err)
	}
	if v, err := k.Get("binary"); err != nil || v != "café" {
		t.Fatalf("get b64: %q %v", v, err)
	}
	if _, err := k.Get("missing"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	argv, _ = os.ReadFile(filepath.Join(log, "argv"))
	if !strings.Contains(string(argv), "find-generic-password -s carhunt -a cardb_token -w") {
		t.Fatalf("read argv: %q", argv)
	}
}
