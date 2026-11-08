package store

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
)

// Car versions. cars.version is an opaque counter that goes up (by ≥ 1) on every write that changes the car row
// or anything shown on the car (listings, price history, options, facts, photos, events, messages, notes, verdicts,
// aliases, duplicate proposals, its seller); clients compare it, never compute it. SQLite triggers do the bump in
// the writing statement, so every write path is covered, including ones added later. They are dropped before
// migrations and rebuilt from the live schema on every Open, so new tables with a car_id column and new columns
// are picked up without touching this file. Sightings that only move listings.last_seen_at / raw don't count.

const versionTriggerPrefix = "cardb_version_"

// versionIgnored lists columns whose changes alone don't bump the version.
var versionIgnored = map[string][]string{
	"cars":     {"version", "updated_at"},
	"listings": {"last_seen_at", "raw"},
	"sellers":  {"updated_at"},
}

type execQuerier interface {
	Exec(query string, args ...any) (sql.Result, error)
	Query(query string, args ...any) (*sql.Rows, error)
}

func queryStrings(db execQuerier, q string, args ...any) ([]string, error) {
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var s string
		if err := rows.Scan(&s); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func dropVersionTriggers(db execQuerier) error {
	names, err := queryStrings(db, "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE ?", versionTriggerPrefix+"%")
	if err != nil {
		return err
	}
	for _, n := range names {
		if _, err := db.Exec(`DROP TRIGGER IF EXISTS "` + n + `"`); err != nil {
			return err
		}
	}
	return nil
}

// installVersionTriggers (re)creates the version triggers for the current schema.
func installVersionTriggers(db execQuerier) error {
	if err := dropVersionTriggers(db); err != nil {
		return err
	}
	carCols, err := queryStrings(db, "SELECT name FROM pragma_table_info('cars')")
	if err != nil || !slices.Contains(carCols, "version") {
		return err // pre-migration schema: nothing to bump
	}
	tables, err := queryStrings(db, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
	if err != nil {
		return err
	}
	for _, t := range tables {
		cols, err := queryStrings(db, "SELECT name FROM pragma_table_info(?)", t)
		if err != nil {
			return err
		}
		has := func(c string) bool { return slices.Contains(cols, c) }
		// target(row) = SQL condition on cars selecting the cars a row of t belongs to (row = NEW|OLD).
		var target func(row string) string
		switch {
		case t == "cars":
		case has("car_id"):
			target = func(row string) string { return "id = " + row + ".car_id" }
		case has("car_a") && has("car_b"):
			target = func(row string) string { return fmt.Sprintf("id IN (%s.car_a, %s.car_b)", row, row) }
		case has("listing_id"):
			target = func(row string) string {
				return "id = (SELECT car_id FROM listings WHERE id = " + row + ".listing_id)"
			}
		case t == "sellers":
			target = func(row string) string { return "seller_id = " + row + ".id" }
		case has("seller_id"):
			target = func(row string) string { return "seller_id = " + row + ".seller_id" }
		default:
			continue
		}
		changed := changedExpr(cols, versionIgnored[t])
		name := versionTriggerPrefix + t
		bump := func(where string) string { return "UPDATE cars SET version = version + 1 WHERE " + where + ";" }
		var stmts []string
		if t == "cars" {
			if changed == "" {
				continue
			}
			stmts = append(stmts, fmt.Sprintf(`CREATE TRIGGER "%s_u" AFTER UPDATE ON cars WHEN %s BEGIN %s END`,
				name, changed, bump("id = NEW.id")))
		} else {
			if t != "sellers" { // a new seller has no cars yet; a deleted one has none left
				stmts = append(stmts,
					fmt.Sprintf(`CREATE TRIGGER "%s_i" AFTER INSERT ON "%s" BEGIN %s END`, name, t, bump(target("NEW"))),
					fmt.Sprintf(`CREATE TRIGGER "%s_d" AFTER DELETE ON "%s" BEGIN %s END`, name, t, bump(target("OLD"))))
			}
			if changed != "" {
				stmts = append(stmts, fmt.Sprintf(`CREATE TRIGGER "%s_u" AFTER UPDATE ON "%s" WHEN %s BEGIN %s END`,
					name, t, changed, bump("("+target("NEW")+") OR ("+target("OLD")+")")))
			}
		}
		for _, s := range stmts {
			if _, err := db.Exec(s); err != nil {
				return fmt.Errorf("version trigger on %s: %w", t, err)
			}
		}
	}
	return nil
}

// changedExpr is "OLD.a IS NOT NEW.a OR …" over cols minus ignored ("" if nothing is left).
func changedExpr(cols, ignored []string) string {
	var parts []string
	for _, c := range cols {
		if slices.Contains(ignored, c) {
			continue
		}
		parts = append(parts, fmt.Sprintf(`OLD."%s" IS NOT NEW."%s"`, c, c))
	}
	if len(parts) == 0 {
		return ""
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}

// --- optimistic locking ------------------------------------------------------------

// ParseVersion reads an If-Match value: "5", 5 or W/"5". "" and "*" mean no precondition (nil).
func ParseVersion(s string) (*int64, error) {
	s = strings.TrimSpace(s)
	if s == "" || s == "*" {
		return nil, nil
	}
	s = strings.TrimPrefix(s, "W/")
	s = strings.Trim(s, `"`)
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil || n < 0 {
		return nil, badRequestf("If-Match must be a car version like \"5\", got %q", s)
	}
	return &n, nil
}

// decodeVersion reads the body `version` (number or null).
func decodeVersion(raw json.RawMessage) (*int64, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err != nil || f < 0 || f != float64(int64(f)) {
		return nil, invalidf("version must be a non-negative integer")
	}
	n := int64(f)
	return &n, nil
}

// checkVersion fails with 412 (+ the current car) when want is set and differs from the car's version.
func checkVersion(tx *sql.Tx, car *carRow, want *int64) error {
	if want == nil || *want == car.Version {
		return nil
	}
	d, err := carDetail(tx, car.ID)
	if err != nil {
		return err
	}
	return &Error{Kind: KindPrecondition,
		Msg:     fmt.Sprintf("car %d changed: version is %d, you sent %d; re-read the car and retry", car.ID, car.Version, *want),
		Details: map[string]any{"version": car.Version, "car": d}}
}
