package cli_test

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/cli"
	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/server"
	"carhunt/cardb/internal/store"
)

// TestVerdictPerUserCLI: `verdict --user`, `show --user`, `ls --user`; a viewer token cannot set the owner's verdict.
func TestVerdictPerUserCLI(t *testing.T) {
	newE2E(t) // env isolation
	st, err := store.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	p, err := profile.Parse([]byte("owner: {name: Sam}\ncardb: {users: [{name: Bea}]}\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := st.SetProfile(p); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(server.NewHandler(st, map[string]string{"agents": "tok-users-agents", "Bea": "tok-users-bea"}))
	defer srv.Close()
	run := func(token string, args ...string) (int, string) {
		var out bytes.Buffer
		code := cli.RunWithStdin(context.Background(), append([]string{"--server", srv.URL, "--token", token}, args...), strings.NewReader(""), &out, &out)
		return code, out.String()
	}
	ok := func(token string, args ...string) string {
		t.Helper()
		code, out := run(token, args...)
		if code != 0 {
			t.Fatalf("%v: exit %d\n%s", args, code, out)
		}
		return out
	}
	var up api.UpsertResult
	if err := json.Unmarshal([]byte(ok("tok-users-agents", "--json", "upsert", "--url", "https://example.invalid/cli-users/1", "--make", "VW")), &up); err != nil {
		t.Fatal(err)
	}
	id := strconv.FormatInt(up.CarID, 10)

	if out := ok("tok-users-agents", "verdict", id, "up"); !strings.Contains(out, "Sam's verdict 👍 up") {
		t.Fatalf("owner verdict output: %s", out)
	}
	if out := ok("tok-users-bea", "verdict", id, "👎", "--note", "too big"); !strings.Contains(out, "Bea's verdict 👎 down") {
		t.Fatalf("viewer verdict output: %s", out)
	}
	if code, out := run("tok-users-bea", "verdict", id, "maybe", "--user", "Sam"); code != cli.ExitError || !strings.Contains(out, "403") {
		t.Fatalf("viewer setting the owner's verdict: %d %s", code, out)
	}
	show := ok("tok-users-agents", "show", id)
	if !strings.Contains(show, "VERDICT\n  Sam: 👍 up") || !strings.Contains(show, "Bea: 👎 down — too big") {
		t.Fatalf("show lists both verdicts, owner first:\n%s", show)
	}
	var d api.CarDetail
	if err := json.Unmarshal([]byte(ok("tok-users-agents", "show", id, "--user", "bea", "--json")), &d); err != nil || d.Verdict == nil || d.Verdict.User != "Bea" {
		t.Fatalf("show --user bea: %+v %v", d.Verdict, err)
	}
	var l api.CarList
	if err := json.Unmarshal([]byte(ok("tok-users-agents", "ls", "--verdict", "down", "--user", "Bea", "--json")), &l); err != nil || l.Total != 1 {
		t.Fatalf("ls --user Bea --verdict down: %+v %v", l, err)
	}
	if err := json.Unmarshal([]byte(ok("tok-users-agents", "ls", "--verdict", "down", "--json")), &l); err != nil || l.Total != 0 {
		t.Fatalf("ls --verdict down (owner): %+v %v", l, err)
	}
	ok("tok-users-agents", "verdict", id, "clear", "--user", "Bea")
	var after api.CarDetail
	if err := json.Unmarshal([]byte(ok("tok-users-agents", "show", id, "--json")), &after); err != nil || len(after.Verdicts) != 1 || after.Verdict.User != "Sam" {
		t.Fatalf("after clearing Bea's: %+v", after.Verdicts)
	}
}
