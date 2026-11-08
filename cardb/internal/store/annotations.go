package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func validateKey(key string) error {
	if !reKey.MatchString(key) {
		return invalidf("key %q must be 1-64 chars of [A-Za-z0-9_.-]", key)
	}
	return nil
}

func validateSource(src string) error {
	if src != "" && !slices.Contains(api.EvidenceSources, src) {
		return invalidf("source must be one of %s", strings.Join(api.EvidenceSources, "|"))
	}
	return nil
}

func defaultSource(src, author string) string {
	if src != "" {
		return src
	}
	if author == "owner" {
		return "owner"
	}
	return "agent_inference"
}

func validateOption(key string, in api.OptionInput) error {
	if err := validateKey(key); err != nil {
		return err
	}
	if !slices.Contains(api.OptionValues, in.Value) {
		return invalidf("option %s: value must be yes|no|unknown", key)
	}
	return validateSource(in.Source)
}

func validateFact(key string, in api.FactInput) error {
	if err := validateKey(key); err != nil {
		return err
	}
	if strings.TrimSpace(in.Value) == "" {
		return invalidf("fact %s: value is required", key)
	}
	return validateSource(in.Source)
}

func loadOption(tx *sql.Tx, carID int64, key string) (*api.Option, error) {
	var o api.Option
	var ref, note sql.NullString
	var at float64
	err := tx.QueryRow("SELECT key, value, source, source_ref, note, author, updated_at FROM options WHERE car_id = ? AND key = ?", carID, key).
		Scan(&o.Key, &o.Value, &o.Source, &ref, &note, &o.Author, &at)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	o.SourceRef, o.Note, o.UpdatedAt = strPtr(ref), strPtr(note), fromTS(at)
	return &o, nil
}

func optStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// setOption writes one option. fillOnly keeps an existing known value; emit writes option_change on value change.
func setOption(tx *sql.Tx, carID int64, key string, in api.OptionInput, at float64, fillOnly, emit bool) (*api.Option, error) {
	if err := validateOption(key, in); err != nil {
		return nil, err
	}
	in.Source = defaultSource(in.Source, in.Author)
	cur, err := loadOption(tx, carID, key)
	if err != nil {
		return nil, err
	}
	if cur != nil {
		if fillOnly && cur.Value != "unknown" {
			return cur, nil
		}
		if cur.Value == in.Value && cur.Source == in.Source && optStr(cur.SourceRef) == in.SourceRef && optStr(cur.Note) == in.Note {
			return cur, nil
		}
	}
	if _, err := tx.Exec(`INSERT INTO options (car_id, key, value, source, source_ref, note, author, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT (car_id, key) DO UPDATE SET value = excluded.value, source = excluded.source, source_ref = excluded.source_ref,
		note = excluded.note, author = excluded.author, updated_at = excluded.updated_at`,
		carID, key, in.Value, in.Source, nullStr(in.SourceRef), nullStr(in.Note), in.Author, at); err != nil {
		return nil, err
	}
	from := "unknown"
	if cur != nil {
		from = cur.Value
	}
	if emit && cur != nil && from != in.Value { // first fill is not a change
		summary := fmt.Sprintf("option %s: %s → %s (%s)", key, from, in.Value, in.Source)
		if _, err := addEvent(tx, ev{CarID: carID, Type: "option_change", At: at, Author: in.Author, Summary: summary,
			Data: map[string]any{"key": key, "from": from, "to": in.Value, "source": in.Source, "source_ref": nullStr(in.SourceRef)}}); err != nil {
			return nil, err
		}
	}
	return loadOption(tx, carID, key)
}

func loadFact(tx *sql.Tx, carID int64, key string) (*api.Fact, error) {
	var f api.Fact
	var ref sql.NullString
	var at float64
	err := tx.QueryRow("SELECT key, value, source, source_ref, author, updated_at FROM facts WHERE car_id = ? AND key = ?", carID, key).
		Scan(&f.Key, &f.Value, &f.Source, &ref, &f.Author, &at)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	f.SourceRef, f.UpdatedAt = strPtr(ref), fromTS(at)
	return &f, nil
}

func setFact(tx *sql.Tx, carID int64, key string, in api.FactInput, at float64, fillOnly, emit bool) (*api.Fact, error) {
	if err := validateFact(key, in); err != nil {
		return nil, err
	}
	in.Value = strings.TrimSpace(in.Value)
	in.Source = defaultSource(in.Source, in.Author)
	cur, err := loadFact(tx, carID, key)
	if err != nil {
		return nil, err
	}
	if cur != nil {
		if fillOnly {
			return cur, nil
		}
		if cur.Value == in.Value && cur.Source == in.Source && optStr(cur.SourceRef) == in.SourceRef {
			return cur, nil
		}
	}
	if _, err := tx.Exec(`INSERT INTO facts (car_id, key, value, source, source_ref, author, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT (car_id, key) DO UPDATE SET value = excluded.value, source = excluded.source, source_ref = excluded.source_ref,
		author = excluded.author, updated_at = excluded.updated_at`,
		carID, key, in.Value, in.Source, nullStr(in.SourceRef), in.Author, at); err != nil {
		return nil, err
	}
	var from any
	if cur != nil {
		from = cur.Value
	}
	if emit && cur != nil && cur.Value != in.Value { // first fill is not a change
		summary := fmt.Sprintf("fact %s: %s → %s (%s)", key, fmtVal(from), in.Value, in.Source)
		if _, err := addEvent(tx, ev{CarID: carID, Type: "fact_change", At: at, Author: in.Author, Summary: summary,
			Data: map[string]any{"key": key, "from": from, "to": in.Value, "source": in.Source}}); err != nil {
			return nil, err
		}
	}
	return loadFact(tx, carID, key)
}

// SetOption handles PUT /cars/{car}/options/{key}.
func (s *Store) SetOption(ctx context.Context, ref, key string, in api.OptionInput) (*api.Option, error) {
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (*api.Option, error) {
		return setOption(tx, id, key, in, atOr(in.At, s.nowTS()), false, true)
	})
}

// DeleteOption handles DELETE /cars/{car}/options/{key}.
func (s *Store) DeleteOption(ctx context.Context, ref, key, author string) error {
	_, err := carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (bool, error) {
		cur, err := loadOption(tx, id, key)
		if err != nil || cur == nil {
			return false, err
		}
		if _, err := tx.Exec("DELETE FROM options WHERE car_id = ? AND key = ?", id, key); err != nil {
			return false, err
		}
		if cur.Value != "unknown" {
			_, err = addEvent(tx, ev{CarID: id, Type: "option_change", At: s.nowTS(), Author: author,
				Summary: fmt.Sprintf("option %s: %s → unknown (removed)", key, cur.Value),
				Data:    map[string]any{"key": key, "from": cur.Value, "to": "unknown"}})
		}
		return true, err
	})
	return err
}

// SetFact handles PUT /cars/{car}/facts/{key}.
func (s *Store) SetFact(ctx context.Context, ref, key string, in api.FactInput) (*api.Fact, error) {
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (*api.Fact, error) {
		return setFact(tx, id, key, in, atOr(in.At, s.nowTS()), false, true)
	})
}

// DeleteFact handles DELETE /cars/{car}/facts/{key}.
func (s *Store) DeleteFact(ctx context.Context, ref, key, author string) error {
	_, err := carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (bool, error) {
		cur, err := loadFact(tx, id, key)
		if err != nil || cur == nil {
			return false, err
		}
		if _, err := tx.Exec("DELETE FROM facts WHERE car_id = ? AND key = ?", id, key); err != nil {
			return false, err
		}
		_, err = addEvent(tx, ev{CarID: id, Type: "fact_change", At: s.nowTS(), Author: author,
			Summary: fmt.Sprintf("fact %s removed (was %s)", key, cur.Value),
			Data:    map[string]any{"key": key, "from": cur.Value, "to": nil}})
		return true, err
	})
	return err
}

func touch(tx *sql.Tx, carID int64, at float64) error {
	_, err := tx.Exec("UPDATE cars SET updated_at = MAX(updated_at, ?) WHERE id = ?", at, carID)
	return err
}

// --- verdicts ----------------------------------------------------------------

var verdictEmoji = map[string]string{"up": "👍", "maybe": "🤔", "down": "👎"}

// SetVerdict handles PUT /cars/{car}/verdict.
func (s *Store) SetVerdict(ctx context.Context, ref string, in api.VerdictInput, author string) (*api.Verdict, error) {
	if !slices.Contains(api.VerdictValues, in.Value) {
		return nil, invalidf("verdict value must be up|maybe|down")
	}
	note := strings.TrimSpace(in.Note)
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (*api.Verdict, error) {
		cur, err := loadVerdict(tx, id)
		if err != nil {
			return nil, err
		}
		if cur != nil && cur.Value == in.Value && optStr(cur.Note) == note {
			return cur, nil
		}
		now := atOr(in.At, s.nowTS())
		if _, err := tx.Exec(`INSERT INTO verdicts (car_id, value, note, author, updated_at) VALUES (?, ?, ?, ?, ?)
			ON CONFLICT (car_id) DO UPDATE SET value = excluded.value, note = excluded.note, author = excluded.author, updated_at = excluded.updated_at`,
			id, in.Value, nullStr(note), author, now); err != nil {
			return nil, err
		}
		var from any
		if cur != nil {
			from = cur.Value
		}
		summary := fmt.Sprintf("verdict %s %s", verdictEmoji[in.Value], in.Value)
		if note != "" {
			summary += ": " + note
		}
		if _, err := addEvent(tx, ev{CarID: id, Type: "verdict", At: now, Author: author, Summary: summary,
			Data: map[string]any{"from": from, "to": in.Value, "note": nullStr(note)}}); err != nil {
			return nil, err
		}
		if err := touch(tx, id, now); err != nil {
			return nil, err
		}
		return loadVerdict(tx, id)
	})
}

// ClearVerdict handles DELETE /cars/{car}/verdict.
func (s *Store) ClearVerdict(ctx context.Context, ref, author string) error {
	_, err := carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (bool, error) {
		cur, err := loadVerdict(tx, id)
		if err != nil || cur == nil {
			return false, err
		}
		now := s.nowTS()
		if _, err := tx.Exec("DELETE FROM verdicts WHERE car_id = ?", id); err != nil {
			return false, err
		}
		_, err = addEvent(tx, ev{CarID: id, Type: "verdict", At: now, Author: author, Summary: "verdict cleared (was " + cur.Value + ")",
			Data: map[string]any{"from": cur.Value, "to": nil}})
		if err == nil {
			err = touch(tx, id, now)
		}
		return true, err
	})
	return err
}

// --- notes ---------------------------------------------------------------------

func authorKind(author string) string {
	switch {
	case author == "owner":
		return "owner"
	case strings.HasPrefix(author, "import"):
		return "import"
	}
	return "agent"
}

func loadNote(tx *sql.Tx, id int64) (*api.Note, error) {
	n, err := scanNote(tx.QueryRow(noteSelect+" WHERE id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, notFoundf("note %d not found", id)
	}
	return n, err
}

func noteExcerpt(text string) string {
	text = strings.Join(strings.Fields(text), " ")
	r := []rune(text)
	if len(r) > 120 {
		return string(r[:119]) + "…"
	}
	return text
}

// AddNote handles POST /cars/{car}/notes; also writes a `note` event so the activity feed shows it.
func (s *Store) AddNote(ctx context.Context, ref string, in api.NoteInput, author string) (*api.Note, error) {
	text := strings.TrimSpace(in.Text)
	if text == "" {
		return nil, invalidf("text is required")
	}
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (*api.Note, error) {
		now := atOr(in.At, s.nowTS())
		r, err := tx.Exec("INSERT INTO notes (car_id, author, author_kind, text, pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
			id, author, authorKind(author), text, boolInt(in.Pinned), now, now)
		if err != nil {
			return nil, err
		}
		nid, err := r.LastInsertId()
		if err != nil {
			return nil, err
		}
		if _, err := addEvent(tx, ev{CarID: id, Type: "note", At: now, Author: author, Summary: "note: " + noteExcerpt(text),
			Data: map[string]any{"note_id": nid}}); err != nil {
			return nil, err
		}
		return loadNote(tx, nid)
	})
}

// PatchNote handles PATCH /notes/{id}.
func (s *Store) PatchNote(ctx context.Context, id int64, in api.NotePatch) (*api.Note, error) {
	var out *api.Note
	err := s.tx(ctx, func(tx *sql.Tx) error {
		if _, err := loadNote(tx, id); err != nil {
			return err
		}
		sets := []string{}
		args := []any{}
		if in.Text != nil {
			t := strings.TrimSpace(*in.Text)
			if t == "" {
				return invalidf("text must not be empty")
			}
			sets = append(sets, "text = ?")
			args = append(args, t)
		}
		if in.Pinned != nil {
			sets = append(sets, "pinned = ?")
			args = append(args, boolInt(*in.Pinned))
		}
		if len(sets) > 0 {
			args = append(args, s.nowTS(), id)
			if _, err := tx.Exec("UPDATE notes SET "+strings.Join(sets, ", ")+", updated_at = ? WHERE id = ?", args...); err != nil {
				return err
			}
		}
		var err error
		out, err = loadNote(tx, id)
		return err
	})
	return out, err
}

// DeleteNote handles DELETE /notes/{id}.
func (s *Store) DeleteNote(ctx context.Context, id int64) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		r, err := tx.Exec("DELETE FROM notes WHERE id = ?", id)
		if err != nil {
			return err
		}
		if n, _ := r.RowsAffected(); n == 0 {
			return notFoundf("note %d not found", id)
		}
		return nil
	})
}

// --- events ----------------------------------------------------------------------

// AddEvent handles POST /cars/{car}/events. Returns created=false when dedupe_key already existed.
func (s *Store) AddEvent(ctx context.Context, ref string, in api.EventInput, author string) (*api.Event, bool, error) {
	if strings.TrimSpace(in.Type) == "" || strings.TrimSpace(in.Summary) == "" {
		return nil, false, invalidf("type and summary are required")
	}
	if len(in.Data) > 0 && !json.Valid(in.Data) {
		return nil, false, invalidf("data must be valid JSON")
	}
	var out *api.Event
	created := false
	err := s.tx(ctx, func(tx *sql.Tx) error {
		if in.DedupeKey != "" {
			e, err := scanEvent(tx.QueryRow(eventSelect+" WHERE dedupe_key = ?", in.DedupeKey))
			if err == nil {
				out = e
				return nil
			} else if !errors.Is(err, sql.ErrNoRows) {
				return err
			}
		}
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		if in.ListingID != nil {
			var cid int64
			if err := tx.QueryRow("SELECT car_id FROM listings WHERE id = ?", *in.ListingID).Scan(&cid); err != nil || cid != id {
				return invalidf("listing %d does not belong to car %d", *in.ListingID, id)
			}
		}
		eid, err := addEvent(tx, ev{CarID: id, ListingID: in.ListingID, Type: strings.TrimSpace(in.Type), At: atOr(in.At, s.nowTS()),
			Author: author, Summary: strings.TrimSpace(in.Summary), Data: in.Data, DedupeKey: in.DedupeKey})
		if err != nil {
			return err
		}
		created = true
		out, err = scanEvent(tx.QueryRow(eventSelect+" WHERE id = ?", eid))
		return err
	})
	return out, created, err
}

// --- activity ----------------------------------------------------------------------

// Activity handles GET /activity: events + messages after since, newest first.
func (s *Store) Activity(ctx context.Context, since *time.Time, limit int) ([]api.ActivityItem, error) {
	if limit <= 0 {
		limit = 100
	}
	if limit > 1000 {
		limit = 1000
	}
	sinceTS := -1.0
	if since != nil {
		sinceTS = ts(*since)
	}
	var out []api.ActivityItem
	err := s.tx(ctx, func(tx *sql.Tx) error {
		titles := map[int64]string{}
		title := func(id int64) string {
			if t, ok := titles[id]; ok {
				return t
			}
			c, err := loadCar(tx, id)
			if err != nil {
				return ""
			}
			titles[id] = c.title()
			return titles[id]
		}
		rows, err := tx.Query(eventSelect+" WHERE at > ? ORDER BY at DESC, id DESC LIMIT ?", sinceTS, limit)
		if err != nil {
			return err
		}
		var items []api.ActivityItem
		for rows.Next() {
			e, err := scanEvent(rows)
			if err != nil {
				rows.Close()
				return err
			}
			items = append(items, api.ActivityItem{Kind: "event", CarID: e.CarID, At: e.At, Event: e})
		}
		rows.Close()
		rows, err = tx.Query(messageSelect+" WHERE at > ? AND "+liveMessage+" ORDER BY at DESC, id DESC LIMIT ?", sinceTS, limit)
		if err != nil {
			return err
		}
		for rows.Next() {
			m, err := scanMessage(rows)
			if err != nil {
				rows.Close()
				return err
			}
			items = append(items, api.ActivityItem{Kind: "message", CarID: m.CarID, At: m.At, Message: m})
		}
		rows.Close()
		sort.SliceStable(items, func(i, j int) bool { return items[i].At.After(items[j].At) })
		if len(items) > limit {
			items = items[:limit]
		}
		for i := range items {
			items[i].CarTitle = title(items[i].CarID)
		}
		out = items
		return nil
	})
	if out == nil {
		out = []api.ActivityItem{}
	}
	return out, err
}
