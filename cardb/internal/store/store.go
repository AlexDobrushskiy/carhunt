// Package store is the SQLite persistence layer: schema, queries, dedupe, merge/split.
// All public methods run in a single transaction on one connection (writes are serialized).
package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"time"

	"carhunt/cardb/internal/profile"

	_ "modernc.org/sqlite" // driver "sqlite"
)

// Kind classifies store errors so the HTTP layer can map them to status codes.
type Kind int

const (
	KindInvalid      Kind = iota // 422
	KindBadRequest               // 400
	KindNotFound                 // 404
	KindConflict                 // 409
	KindTooLarge                 // 413
	KindPrecondition             // 412 (stale car version)
)

// Error is a client-facing error. Details are extra JSON fields of the error body (412 version/car, 422 price reason).
type Error struct {
	Kind    Kind
	Msg     string
	Details map[string]any
}

func (e *Error) Error() string { return e.Msg }

func invalidf(format string, a ...any) error {
	return &Error{Kind: KindInvalid, Msg: fmt.Sprintf(format, a...)}
}
func notFoundf(format string, a ...any) error {
	return &Error{Kind: KindNotFound, Msg: fmt.Sprintf(format, a...)}
}
func conflictf(format string, a ...any) error {
	return &Error{Kind: KindConflict, Msg: fmt.Sprintf(format, a...)}
}
func badRequestf(format string, a ...any) error {
	return &Error{Kind: KindBadRequest, Msg: fmt.Sprintf(format, a...)}
}

// IsKind reports whether err is a store *Error of the given kind.
func IsKind(err error, k Kind) bool {
	var e *Error
	return errors.As(err, &e) && e.Kind == k
}

// Store owns the database and the photo directory.
type Store struct {
	db        *sql.DB
	dataDir   string
	photosDir string
	now       func() time.Time
	profile   *profile.Profile
}

// Open opens (creating if needed) $dataDir/cardb.sqlite3 and migrates the schema. Profile = profile.Default() until SetProfile.
func Open(dataDir string) (*Store, error) {
	if err := os.MkdirAll(filepath.Join(dataDir, "photos"), 0o755); err != nil {
		return nil, fmt.Errorf("create data dir: %w", err)
	}
	path := filepath.Join(dataDir, "cardb.sqlite3")
	dsn := "file:" + path + "?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)&_pragma=synchronous(NORMAL)&_pragma=temp_store(MEMORY)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetConnMaxIdleTime(0)
	s := &Store{db: db, dataDir: dataDir, photosDir: filepath.Join(dataDir, "photos"), now: time.Now, profile: profile.Default()}
	// Version triggers are rebuilt around migrations so they match the final schema (version.go).
	if err := dropVersionTriggers(db); err != nil {
		db.Close()
		return nil, err
	}
	if err := s.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	if err := s.tx(context.Background(), func(tx *sql.Tx) error { return installVersionTriggers(tx) }); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}

// Close closes the database.
func (s *Store) Close() error { return s.db.Close() }

// SetProfile sets the buyer profile (call before serving; not safe concurrently with requests).
func (s *Store) SetProfile(p *profile.Profile) {
	if p == nil {
		p = profile.Default()
	}
	s.profile = p
}

// Profile returns the active buyer profile.
func (s *Store) Profile() *profile.Profile { return s.profile }

// SetClock overrides the time source (tests).
func (s *Store) SetClock(now func() time.Time) { s.now = now }

// Ping checks the database is usable.
func (s *Store) Ping(ctx context.Context) error {
	var one int
	return s.db.QueryRowContext(ctx, "SELECT 1").Scan(&one)
}

// BackupTo writes a consistent snapshot to dest via VACUUM INTO.
func (s *Store) BackupTo(ctx context.Context, dest string) error {
	if _, err := os.Stat(dest); err == nil {
		return fmt.Errorf("backup destination %s already exists", dest)
	}
	_, err := s.db.ExecContext(ctx, "VACUUM INTO ?", dest)
	return err
}

func (s *Store) migrate() error {
	var v int
	if err := s.db.QueryRow("PRAGMA user_version").Scan(&v); err != nil {
		return fmt.Errorf("read user_version: %w", err)
	}
	for i := v; i < len(migrations); i++ {
		tx, err := s.db.Begin()
		if err != nil {
			return err
		}
		switch m := migrations[i].(type) {
		case string:
			_, err = tx.Exec(m)
		case func(*sql.Tx) error:
			err = m(tx)
		default:
			err = fmt.Errorf("bad migration type %T", m)
		}
		if err != nil {
			tx.Rollback()
			return fmt.Errorf("migration %d: %w", i+1, err)
		}
		if _, err := tx.Exec(fmt.Sprintf("PRAGMA user_version = %d", i+1)); err != nil {
			tx.Rollback()
			return err
		}
		if err := tx.Commit(); err != nil {
			return err
		}
	}
	return nil
}

// tx runs fn in a transaction; commits on nil error.
func (s *Store) tx(ctx context.Context, fn func(tx *sql.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		tx.Rollback()
		return err
	}
	return tx.Commit()
}

// --- time helpers -------------------------------------------------------

func ts(t time.Time) float64 { return float64(t.UnixMicro()) / 1e6 }

func fromTS(f float64) time.Time {
	return time.UnixMicro(int64(math.Round(f * 1e6))).UTC()
}

func fromNullTS(f sql.NullFloat64) *time.Time {
	if !f.Valid {
		return nil
	}
	t := fromTS(f.Float64)
	return &t
}

func (s *Store) nowTS() float64 { return ts(s.now()) }

func atOr(t *time.Time, def float64) float64 {
	if t == nil || t.IsZero() {
		return def
	}
	return ts(*t)
}

// --- null helpers -------------------------------------------------------

func strPtr(n sql.NullString) *string {
	if !n.Valid {
		return nil
	}
	v := n.String
	return &v
}

func intPtr(n sql.NullInt64) *int {
	if !n.Valid {
		return nil
	}
	v := int(n.Int64)
	return &v
}

func int64Ptr(n sql.NullInt64) *int64 {
	if !n.Valid {
		return nil
	}
	v := n.Int64
	return &v
}

func floatPtr(n sql.NullFloat64) *float64 {
	if !n.Valid {
		return nil
	}
	v := n.Float64
	return &v
}

func nullStr(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func nullInt64(p *int64) any {
	if p == nil {
		return nil
	}
	return *p
}

func jsonList(v []string) string {
	if v == nil {
		v = []string{}
	}
	b, _ := json.Marshal(v)
	return string(b)
}

func parseList(s string) []string {
	var out []string
	_ = json.Unmarshal([]byte(s), &out)
	if out == nil {
		out = []string{}
	}
	return out
}

func mustJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "null"
	}
	return string(b)
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
