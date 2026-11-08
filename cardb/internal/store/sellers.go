package store

import (
	"context"
	"database/sql"
	"errors"
	"slices"
	"strings"
	"unicode"

	"carhunt/cardb/internal/api"
)

var contactKinds = []string{"phone", "whatsapp", "email", "site_chat", "web"}

func normContacts(in []api.Contact) ([]api.Contact, error) {
	var out []api.Contact
	for _, c := range in {
		kind := strings.ToLower(strings.TrimSpace(c.Kind))
		if !slices.Contains(contactKinds, kind) {
			return nil, invalidf("contact kind must be one of %s", strings.Join(contactKinds, "|"))
		}
		v := NormalizeContact(kind, c.Value)
		if v == "" {
			continue
		}
		out = append(out, api.Contact{Kind: kind, Value: v, Note: c.Note})
	}
	return out, nil
}

func sellerInputEmpty(in *api.SellerInput, contacts []api.Contact) bool {
	nonEmpty := func(p *string) bool { return p != nil && strings.TrimSpace(*p) != "" }
	return !nonEmpty(in.Name) && !nonEmpty(in.Company) && !nonEmpty(in.City) && !nonEmpty(in.Note) &&
		(in.Type == nil || *in.Type == "" || *in.Type == "unknown") && len(contacts) == 0
}

// sharedNote marks a contact that also appears on other sellers' ads.
const sharedNote = "shared number: also on other sellers' ads (portal call-centre / switchboard), not this seller's own line"

var accentFold = strings.NewReplacer("á", "a", "à", "a", "â", "a", "ä", "a", "ã", "a", "å", "a", "é", "e", "è", "e", "ê", "e", "ë", "e",
	"í", "i", "ì", "i", "î", "i", "ï", "i", "ó", "o", "ò", "o", "ô", "o", "ö", "o", "õ", "o", "ú", "u", "ù", "u", "û", "u", "ü", "u",
	"ñ", "n", "ç", "c", "š", "s", "ž", "z", "ß", "ss")

// sellerKey is a seller's comparable name: company, else person name; lowercased, accents and punctuation dropped.
func sellerKey(company, name *string) string {
	v := ""
	for _, p := range []*string{company, name} {
		if p != nil && strings.TrimSpace(*p) != "" {
			v = *p
			break
		}
	}
	v = accentFold.Replace(strings.ToLower(v))
	var b strings.Builder
	for _, r := range v {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
		} else {
			b.WriteRune(' ')
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

// namesConflict: both sellers are named and neither name contains the other ("SYNTH MOTORS CENTRO" vs
// "SYNTH CARS SUR" conflict; "GRUPO SYNTH AUTOMOVILES" vs "GRUPO SYNTH AUTOMOVILES NORTE" don't).
func namesConflict(a, b string) bool {
	return a != "" && b != "" && !strings.Contains(a, b) && !strings.Contains(b, a)
}

func sellerKeyOf(tx *sql.Tx, id int64) (string, error) {
	var company, name sql.NullString
	if err := tx.QueryRow("SELECT company, name FROM sellers WHERE id = ?", id).Scan(&company, &name); err != nil {
		return "", err
	}
	return sellerKey(strPtr(company), strPtr(name)), nil
}

// ensureSeller finds or creates the seller for in and merges fields and contacts into it.
// cur is the car's current seller (0 = none). strict makes a contact owned by another seller a 409.
// A contact identifies a seller only while it is that seller's own (not shared) and the names don't conflict;
// a contact that turns up with a differently named seller becomes shared on both.
func ensureSeller(tx *sql.Tx, cur int64, in *api.SellerInput, overwrite, strict bool, now float64) (int64, bool, error) {
	if in == nil {
		return cur, false, nil
	}
	if in.Type != nil && *in.Type != "" && !slices.Contains(api.SellerTypes, *in.Type) {
		return 0, false, invalidf("seller type must be one of %s", strings.Join(api.SellerTypes, "|"))
	}
	contacts, err := normContacts(in.Contacts)
	if err != nil {
		return 0, false, err
	}
	inKey := sellerKey(in.Company, in.Name)
	sid := cur
	if sid == 0 {
		for _, c := range contacts {
			var owner int64
			err := tx.QueryRow("SELECT seller_id FROM seller_contacts WHERE kind = ? AND value = ? AND shared = 0", c.Kind, c.Value).Scan(&owner)
			if errors.Is(err, sql.ErrNoRows) {
				continue
			} else if err != nil {
				return 0, false, err
			}
			k, err := sellerKeyOf(tx, owner)
			if err != nil {
				return 0, false, err
			}
			if !namesConflict(k, inKey) {
				sid = owner
				break
			}
		}
	}
	if sid == 0 {
		if sellerInputEmpty(in, contacts) {
			return 0, false, nil
		}
		res, err := tx.Exec("INSERT INTO sellers (created_at, updated_at) VALUES (?, ?)", now, now)
		if err != nil {
			return 0, false, err
		}
		if sid, err = res.LastInsertId(); err != nil {
			return 0, false, err
		}
	}

	type fld struct {
		col string
		v   *string
	}
	var sets []string
	var args []any
	for _, f := range []fld{{"name", in.Name}, {"company", in.Company}, {"city", in.City}, {"note", in.Note}, {"type", in.Type}} {
		if f.v == nil {
			continue
		}
		v := strings.TrimSpace(*f.v)
		if v == "" {
			continue
		}
		if overwrite {
			sets = append(sets, f.col+" = ?")
		} else if f.col == "type" {
			sets = append(sets, "type = CASE WHEN type = 'unknown' THEN ? ELSE type END")
		} else {
			sets = append(sets, f.col+" = COALESCE("+f.col+", ?)")
		}
		args = append(args, v)
	}
	if len(sets) > 0 {
		args = append(args, now, sid)
		if _, err := tx.Exec("UPDATE sellers SET "+strings.Join(sets, ", ")+", updated_at = ? WHERE id = ?", args...); err != nil {
			return 0, false, err
		}
	}
	myKey, err := sellerKeyOf(tx, sid)
	if err != nil {
		return 0, false, err
	}

	changed := false
	insert := func(c api.Contact, shared bool) error {
		var note any
		if c.Note != nil {
			note = *c.Note
		} else if shared {
			note = sharedNote
		}
		_, err := tx.Exec("INSERT INTO seller_contacts (seller_id, kind, value, note, shared) VALUES (?, ?, ?, ?, ?)", sid, c.Kind, c.Value, note, boolInt(shared))
		return err
	}
	for _, c := range contacts {
		type row struct {
			seller int64
			shared bool
		}
		var rows []row
		rs, err := tx.Query("SELECT seller_id, shared FROM seller_contacts WHERE kind = ? AND value = ?", c.Kind, c.Value)
		if err != nil {
			return 0, false, err
		}
		for rs.Next() {
			var r row
			if err := rs.Scan(&r.seller, &r.shared); err != nil {
				rs.Close()
				return 0, false, err
			}
			rows = append(rows, r)
		}
		rs.Close()
		switch {
		case len(rows) == 0:
			if err := insert(c, false); err != nil {
				return 0, false, err
			}
			changed = true
		case slices.ContainsFunc(rows, func(r row) bool { return r.seller == sid }):
		case rows[0].shared:
			if err := insert(c, true); err != nil {
				return 0, false, err
			}
		default: // owned by another seller
			if strict {
				return 0, false, conflictf("contact %s %s already belongs to seller %d", c.Kind, c.Value, rows[0].seller)
			}
			k, err := sellerKeyOf(tx, rows[0].seller)
			if err != nil {
				return 0, false, err
			}
			if !namesConflict(k, myKey) {
				continue // same seller under another record; leave the number where it is
			}
			if _, err := tx.Exec("UPDATE seller_contacts SET shared = 1, note = COALESCE(note, ?) WHERE kind = ? AND value = ?", sharedNote, c.Kind, c.Value); err != nil {
				return 0, false, err
			}
			if err := insert(c, true); err != nil {
				return 0, false, err
			}
		}
	}
	return sid, changed, nil
}

func loadSeller(tx *sql.Tx, id int64) (*api.Seller, error) {
	var s api.Seller
	var name, company, city, note sql.NullString
	err := tx.QueryRow("SELECT id, name, type, company, city, note FROM sellers WHERE id = ?", id).
		Scan(&s.ID, &name, &s.Type, &company, &city, &note)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, notFoundf("seller %d not found", id)
	} else if err != nil {
		return nil, err
	}
	s.Name, s.Company, s.City, s.Note = strPtr(name), strPtr(company), strPtr(city), strPtr(note)
	s.Contacts = []api.Contact{}
	rows, err := tx.Query("SELECT kind, value, note, shared FROM seller_contacts WHERE seller_id = ? ORDER BY shared, id", id)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var c api.Contact
		var n sql.NullString
		if err := rows.Scan(&c.Kind, &c.Value, &n, &c.Shared); err != nil {
			rows.Close()
			return nil, err
		}
		c.Note = strPtr(n)
		s.Contacts = append(s.Contacts, c)
	}
	rows.Close()
	s.CarIDs = []int64{}
	rows, err = tx.Query("SELECT id FROM cars WHERE seller_id = ? AND merged_into IS NULL ORDER BY id", id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid int64
		if err := rows.Scan(&cid); err != nil {
			return nil, err
		}
		s.CarIDs = append(s.CarIDs, cid)
	}
	return &s, rows.Err()
}

// sellerContactValues returns the normalized own (not shared) contact values of a seller.
func sellerContactValues(tx *sql.Tx, sellerID int64) ([]string, error) {
	rows, err := tx.Query("SELECT value FROM seller_contacts WHERE seller_id = ? AND shared = 0", sellerID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var v string
		if err := rows.Scan(&v); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

// GetSeller handles GET /sellers/{id}.
func (s *Store) GetSeller(ctx context.Context, id int64) (*api.Seller, error) {
	var out *api.Seller
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		out, err = loadSeller(tx, id)
		return err
	})
	return out, err
}

// PatchSeller handles PATCH /sellers/{id}: sent fields replace, contacts are added.
func (s *Store) PatchSeller(ctx context.Context, id int64, in api.SellerInput, author string) (*api.Seller, error) {
	var out *api.Seller
	err := s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		if _, err := loadSeller(tx, id); err != nil {
			return err
		}
		_, changed, err := ensureSeller(tx, id, &in, true, true, now)
		if err != nil {
			return err
		}
		if changed {
			rows, err := tx.Query("SELECT id FROM cars WHERE seller_id = ? AND merged_into IS NULL", id)
			if err != nil {
				return err
			}
			var ids []int64
			for rows.Next() {
				var cid int64
				if err := rows.Scan(&cid); err != nil {
					rows.Close()
					return err
				}
				ids = append(ids, cid)
			}
			rows.Close()
			for _, cid := range ids {
				if live, err := resolveCar(tx, itoa(cid)); err == nil && live == cid {
					if _, err := rededupe(tx, cid, author, now); err != nil {
						return err
					}
				}
			}
		}
		out, err = loadSeller(tx, id)
		return err
	})
	return out, err
}
