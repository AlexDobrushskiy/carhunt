package store

import (
	"context"
	"database/sql"
	"strconv"
	"strings"
)

// DeleteCar handles DELETE /cars/{car}?confirm=<id>: hard-deletes the car and everything attached to it.
// confirm must equal the resolved numeric id (400); a car that tombstones point at is refused (409).
// Sellers are kept (they may be shared); photo files go once no other car uses the same bytes.
func (s *Store) DeleteCar(ctx context.Context, ref, confirm string) error {
	var shas []string
	err := s.tx(ctx, func(tx *sql.Tx) error {
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		if c, err := strconv.ParseInt(strings.TrimSpace(confirm), 10, 64); err != nil || c != id {
			return badRequestf("confirm must equal the car's numeric id (%d)", id)
		}
		var children []int64
		if err := eachRow(tx, "SELECT id FROM cars WHERE merged_into = ? ORDER BY id", []any{id}, func(sc scanner) error {
			var cid int64
			if err := sc.Scan(&cid); err != nil {
				return err
			}
			children = append(children, cid)
			return nil
		}); err != nil {
			return err
		}
		if len(children) > 0 {
			return conflictf("car %d has merged cars %v pointing at it; split or keep it", id, children)
		}
		if err := eachRow(tx, "SELECT DISTINCT sha256 FROM photos WHERE car_id = ?", []any{id}, func(sc scanner) error {
			var sha string
			if err := sc.Scan(&sha); err != nil {
				return err
			}
			shas = append(shas, sha)
			return nil
		}); err != nil {
			return err
		}
		for _, q := range []string{
			"DELETE FROM photos WHERE car_id = ?",
			"DELETE FROM events WHERE car_id = ?",
			"DELETE FROM messages WHERE car_id = ?",
			"DELETE FROM notes WHERE car_id = ?",
			"DELETE FROM verdicts WHERE car_id = ?",
			"DELETE FROM options WHERE car_id = ?",
			"DELETE FROM facts WHERE car_id = ?",
			"DELETE FROM car_aliases WHERE car_id = ?",
			"DELETE FROM price_points WHERE listing_id IN (SELECT id FROM listings WHERE car_id = ?)",
			"DELETE FROM listings WHERE car_id = ?",
			"DELETE FROM duplicates WHERE ? IN (car_a, car_b)",
			"DELETE FROM cars WHERE id = ?",
		} {
			if _, err := tx.Exec(q, id); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	s.removePhotoFiles(ctx, shas)
	return nil
}
