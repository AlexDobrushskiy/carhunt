package setup

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDataDirResolution(t *testing.T) {
	t.Setenv("CARDB_DATA_DIR", "")
	home := t.TempDir()
	uh, _ := os.UserHomeDir()
	for _, c := range []struct{ configured, want string }{
		{"", filepath.Join(home, "cardb")},
		{"cardb", filepath.Join(home, "cardb")},
		{"$CARHUNT_HOME/db", filepath.Join(home, "db")},
		{"${CARHUNT_HOME}/db", filepath.Join(home, "db")},
		{"~/elsewhere", filepath.Join(uh, "elsewhere")},
		{"/abs/dir", "/abs/dir"},
	} {
		if got := DataDir(home, c.configured); got != c.want {
			t.Errorf("DataDir(%q) = %q, want %q", c.configured, got, c.want)
		}
	}
	t.Setenv("CARDB_DATA_DIR", "/env/wins")
	if got := DataDir(home, "cardb"); got != "/env/wins" {
		t.Errorf("env: got %q", got)
	}
}
