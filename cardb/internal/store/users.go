package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"slices"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
)

// Users: the owner (one row, role 'owner') + the profile's viewers. The profile is the source; syncUsers mirrors it
// into the users table so verdicts can reference a stable user id. Viewers dropped from the profile become inactive
// (their verdicts stay in the table but are no longer shown).

// reservedNames are vocabulary words a legacy-identity rewrite must never touch (sender kinds, sources, author kinds).
var reservedNames = []string{"owner", "viewer", "agent", "import", "seller", "system"}

// syncUsers mirrors p's users into the users table and rewrites legacy owner identities (see rewriteLegacyOwner).
func (s *Store) syncUsers(ctx context.Context, p *profile.Profile) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		owner := p.Owner.Name
		// A non-owner row holding the owner's name steps aside (renamed + inactive) so the owner row can take it.
		if _, err := tx.Exec(`UPDATE users SET name = name || '#' || id, active = 0, updated_at = ?
			WHERE role != 'owner' AND name = ? COLLATE NOCASE`, now, owner); err != nil {
			return err
		}
		r, err := tx.Exec("UPDATE users SET name = ?, active = 1, updated_at = ? WHERE role = 'owner'", owner, now)
		if err != nil {
			return err
		}
		if n, _ := r.RowsAffected(); n == 0 {
			if _, err := tx.Exec("INSERT INTO users (name, role, created_at, updated_at) VALUES (?, 'owner', ?, ?)", owner, now, now); err != nil {
				return err
			}
		}
		if _, err := tx.Exec("UPDATE users SET active = 0, updated_at = ? WHERE role = 'viewer' AND active = 1", now); err != nil {
			return err
		}
		for _, u := range p.Users() {
			if u.Role != "viewer" {
				continue
			}
			if _, err := tx.Exec(`INSERT INTO users (name, role, active, created_at, updated_at) VALUES (?, 'viewer', 1, ?, ?)
				ON CONFLICT (name) DO UPDATE SET name = excluded.name, role = 'viewer', active = 1, updated_at = excluded.updated_at`,
				u.Name, now, now); err != nil {
				return err
			}
		}
		return rewriteLegacyOwner(tx, owner)
	})
}

// rewriteLegacyOwner turns identities that named the owner personally into the role word `owner`: option/fact
// `source`, message `sender_kind` and note `author_kind` equal to lower(owner.name). Notes are re-classified by
// author (owner / viewer) too. Idempotent; a no-op when the owner name is itself a vocabulary word.
func rewriteLegacyOwner(tx *sql.Tx, owner string) error {
	low := strings.ToLower(strings.TrimSpace(owner))
	if low != "" && !slices.Contains(reservedNames, low) && !slices.Contains(api.EvidenceSources, low) {
		for _, q := range []string{
			"UPDATE options SET source = 'owner' WHERE lower(source) = ?",
			"UPDATE facts SET source = 'owner' WHERE lower(source) = ?",
			"UPDATE messages SET sender_kind = 'owner' WHERE lower(sender_kind) = ?",
			"UPDATE notes SET author_kind = 'owner' WHERE lower(author_kind) = ?",
		} {
			if _, err := tx.Exec(q, low); err != nil {
				return err
			}
		}
	}
	_, err := tx.Exec(`UPDATE notes SET author_kind = (SELECT CASE u.role WHEN 'owner' THEN 'owner' ELSE 'viewer' END
			FROM users u WHERE u.active = 1 AND u.name = notes.author COLLATE NOCASE)
		WHERE author_kind != 'import' AND EXISTS (SELECT 1 FROM users u WHERE u.active = 1 AND u.name = notes.author COLLATE NOCASE)`)
	return err
}

type userRow struct {
	id   int64
	name string
	role string
}

// ownerRow is the owner's users row.
func ownerRow(tx *sql.Tx) (userRow, error) {
	var u userRow
	err := tx.QueryRow("SELECT id, name, role FROM users WHERE role = 'owner'").Scan(&u.id, &u.name, &u.role)
	return u, err
}

// userByName finds an active user (case-insensitive); "" = the owner. Unknown → 422.
func userByName(tx *sql.Tx, name string) (userRow, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return ownerRow(tx)
	}
	var u userRow
	err := tx.QueryRow("SELECT id, name, role FROM users WHERE active = 1 AND name = ? COLLATE NOCASE", name).Scan(&u.id, &u.name, &u.role)
	if errors.Is(err, sql.ErrNoRows) {
		return u, invalidf("unknown user %q (GET /profile lists users)", name)
	}
	return u, err
}

// UserName canonicalises a user name ("" = the owner); unknown → 422 (KindInvalid).
func (s *Store) UserName(ctx context.Context, name string) (string, error) {
	var out string
	err := s.tx(ctx, func(tx *sql.Tx) error {
		u, err := userByName(tx, name)
		out = u.name
		return err
	})
	return out, err
}

// authorKind classifies a write's author: owner (owner's name), viewer (an active viewer), import, else agent.
func authorKind(tx *sql.Tx, author string) string {
	if strings.HasPrefix(author, "import") {
		return "import"
	}
	var role string
	if err := tx.QueryRow("SELECT role FROM users WHERE active = 1 AND name = ? COLLATE NOCASE", strings.TrimSpace(author)).Scan(&role); err == nil {
		return role
	}
	return "agent"
}

// isOwner reports whether author is the owner's name (case-insensitive).
func isOwner(tx *sql.Tx, author string) bool {
	return authorKind(tx, author) == "owner"
}

const verdictSelect = `SELECT v.car_id, u.name, v.value, v.note, v.author, v.updated_at
	FROM verdicts v JOIN users u ON u.id = v.user_id WHERE u.active = 1`

// carVerdicts holds one car's verdicts by user name.
type carVerdicts map[string]*api.Verdict

func scanVerdict(sc scanner) (int64, *api.Verdict, error) {
	var carID int64
	var v api.Verdict
	var note sql.NullString
	var at float64
	if err := sc.Scan(&carID, &v.User, &v.Value, &note, &v.Author, &at); err != nil {
		return 0, nil, err
	}
	v.Note, v.UpdatedAt = strPtr(note), fromTS(at)
	return carID, &v, nil
}

// loadAllVerdicts returns car id → user name → verdict for active users.
func loadAllVerdicts(tx *sql.Tx) (map[int64]carVerdicts, error) {
	out := map[int64]carVerdicts{}
	err := eachRow(tx, verdictSelect, nil, func(sc scanner) error {
		carID, v, err := scanVerdict(sc)
		if err != nil {
			return err
		}
		if out[carID] == nil {
			out[carID] = carVerdicts{}
		}
		out[carID][v.User] = v
		return nil
	})
	return out, err
}

// loadVerdicts returns one car's verdicts by user name (never nil).
func loadVerdicts(tx *sql.Tx, carID int64) (carVerdicts, error) {
	out := carVerdicts{}
	err := eachRow(tx, verdictSelect+" AND v.car_id = ?", []any{carID}, func(sc scanner) error {
		_, v, err := scanVerdict(sc)
		if err == nil {
			out[v.User] = v
		}
		return err
	})
	return out, err
}

// loadVerdict returns user's verdict on a car ("" = the owner), nil when there is none.
func loadVerdict(tx *sql.Tx, carID int64, user string) (*api.Verdict, error) {
	u, err := userByName(tx, user)
	if err != nil {
		return nil, err
	}
	v := &api.Verdict{User: u.name}
	var note sql.NullString
	var at float64
	err = tx.QueryRow("SELECT value, note, author, updated_at FROM verdicts WHERE car_id = ? AND user_id = ?", carID, u.id).
		Scan(&v.Value, &note, &v.Author, &at)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	v.Note, v.UpdatedAt = strPtr(note), fromTS(at)
	return v, nil
}

// pick returns user's verdict (case-insensitive name), nil when absent.
func (cv carVerdicts) pick(user string) *api.Verdict {
	for name, v := range cv {
		if strings.EqualFold(name, user) {
			return v
		}
	}
	return nil
}

// orEmpty gives a non-nil map for JSON (`verdicts: {}`).
func (cv carVerdicts) orEmpty() map[string]*api.Verdict {
	if cv == nil {
		return map[string]*api.Verdict{}
	}
	return cv
}

// verdictUser resolves a filter's user ("" = owner) to the canonical name; unknown → 400.
func verdictUser(tx *sql.Tx, user string) (string, error) {
	u, err := userByName(tx, user)
	if IsKind(err, KindInvalid) {
		return "", badRequestf("%s", err.Error())
	}
	return u.name, err
}

func userLabel(u userRow) string {
	if u.role == "owner" {
		return ""
	}
	return fmt.Sprintf("%s: ", u.name)
}

// setDetailVerdicts fills d.Verdicts and d.Verdict (user's; "" = the owner).
func setDetailVerdicts(tx *sql.Tx, d *api.CarDetail, user string) error {
	vs, err := loadVerdicts(tx, d.ID)
	if err != nil {
		return err
	}
	u, err := userByName(tx, user)
	if err != nil {
		return err
	}
	d.Verdicts, d.Verdict = vs.orEmpty(), vs.pick(u.name)
	return nil
}

// GetCarFor is GetCar with `verdict` = user's verdict ("" = the owner; unknown → 400).
func (s *Store) GetCarFor(ctx context.Context, ref, user string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		name, err := verdictUser(tx, user)
		if err != nil {
			return err
		}
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		if out, err = s.carDetail(tx, id); err != nil {
			return err
		}
		out.Verdict = carVerdicts(out.Verdicts).pick(name)
		return nil
	})
	return out, err
}
