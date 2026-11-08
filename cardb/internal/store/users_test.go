package store

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"testing"

	"carhunt/cardb/internal/profile"
)

func mustProfile(t *testing.T, y string) *profile.Profile {
	t.Helper()
	p, err := profile.Parse([]byte(y))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// legacyDB writes a database at schema 6 (before users): car 1 with a single verdict and identities that name the
// owner personally ("Pat" in mixed case), plus control rows that must stay as they are.
func legacyDB(t *testing.T, dir string) {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+filepath.Join(dir, "cardb.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	tx, err := db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	for i, m := range migrations[:6] {
		switch m := m.(type) {
		case string:
			_, err = tx.Exec(m)
		case func(*sql.Tx) error:
			err = m(tx)
		}
		if err != nil {
			t.Fatalf("migration %d: %v", i+1, err)
		}
	}
	for _, q := range []string{
		"PRAGMA user_version = 6",
		"INSERT INTO cars (id, make, created_at, updated_at) VALUES (1, 'SYNTH', 1, 1)",
		"INSERT INTO verdicts (car_id, value, note, author, updated_at) VALUES (1, 'up', 'nice', 'pat', 2)",
		"INSERT INTO options (car_id, key, value, source, author, updated_at) VALUES (1, 'pano', 'yes', 'pat', 'pat', 3)",
		"INSERT INTO options (car_id, key, value, source, author, updated_at) VALUES (1, 'towbar', 'no', 'seller_said', 'pat', 3)",
		"INSERT INTO facts (car_id, key, value, source, author, updated_at) VALUES (1, 'warranty', '2028', 'Pat', 'pat', 3)",
		`INSERT INTO messages (car_id, channel, direction, at, sender_kind, sender, text, delivery, dedupe_key, author)
			VALUES (1, 'email', 'out', 4, 'PAT', 'Pat', 'hello', 'sent', 'k1', 'pat'),
			       (1, 'email', 'in', 5, 'seller', 'SYNTH Motors', 'hi', 'received', 'k2', 'import')`,
		`INSERT INTO notes (car_id, author, author_kind, text, created_at, updated_at)
			VALUES (1, 'pat', 'pat', 'n1', 6, 6), (1, 'Kim', 'agent', 'n2', 6, 6), (1, 'import-x', 'import', 'n3', 6, 6)`,
	} {
		if _, err := tx.Exec(q); err != nil {
			t.Fatalf("%s: %v", q, err)
		}
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
}

func (s *Store) col(t *testing.T, q string) []string {
	t.Helper()
	var out []string
	err := s.tx(context.Background(), func(tx *sql.Tx) error {
		return eachRow(tx, q, nil, func(sc scanner) error {
			var v string
			err := sc.Scan(&v)
			out = append(out, v)
			return err
		})
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// TestLegacyOwnerRewrite: the pre-users verdict becomes the owner's; setting the profile names it and rewrites
// identities equal to the owner's name to `owner`; renaming the owner keeps their verdicts.
func TestLegacyOwnerRewrite(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	legacyDB(t, dir)
	s, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()

	d, err := s.GetCar(ctx, "1")
	if err != nil || d.Verdict == nil || d.Verdict.User != "owner" || d.Verdict.Value != "up" || d.Verdict.Author != "pat" {
		t.Fatalf("migrated verdict before the profile: %+v %v", d.Verdict, err)
	}
	if err := s.SetProfile(mustProfile(t, "owner: {name: Pat}\ncardb: {users: [{name: Kim}]}")); err != nil {
		t.Fatal(err)
	}
	check := func(stage string) {
		t.Helper()
		for q, want := range map[string]string{
			"SELECT source FROM options ORDER BY key":           "[owner seller_said]",
			"SELECT source FROM facts":                          "[owner]",
			"SELECT sender_kind FROM messages ORDER BY at":      "[owner seller]",
			"SELECT author_kind FROM notes ORDER BY text":       "[owner viewer import]",
			"SELECT name || ':' || role FROM users ORDER BY id": "[Pat:owner Kim:viewer]",
		} {
			if got := fmt.Sprint(s.col(t, q)); got != want {
				t.Errorf("%s: %s = %s, want %s", stage, q, got, want)
			}
		}
	}
	check("first sync")
	d, _ = s.GetCar(ctx, "1")
	if d.Verdict == nil || d.Verdict.User != "Pat" || len(d.Verdicts) != 1 {
		t.Fatalf("owner verdict after profile: %+v %+v", d.Verdict, d.Verdicts)
	}
	if err := s.SetProfile(mustProfile(t, "owner: {name: Pat}\ncardb: {users: [{name: Kim}]}")); err != nil {
		t.Fatal(err)
	}
	check("second sync (idempotent)")

	// Owner renamed, viewer dropped: the owner's verdict follows; the old name is no longer a user.
	if err := s.SetProfile(mustProfile(t, "owner: {name: Robin}")); err != nil {
		t.Fatal(err)
	}
	d, _ = s.GetCar(ctx, "1")
	if d.Verdict == nil || d.Verdict.User != "Robin" {
		t.Fatalf("after owner rename: %+v", d.Verdict)
	}
	if _, err := s.UserName(ctx, "Kim"); !IsKind(err, KindInvalid) {
		t.Fatalf("dropped viewer still resolves: %v", err)
	}
	if got := fmt.Sprint(s.col(t, "SELECT source FROM facts")); got != "[owner]" {
		t.Fatalf("rename must not undo the rewrite: %s", got)
	}
}
