package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/imaging"
)

// PhotoMeta is the caller-supplied part of a photo upload.
type PhotoMeta struct {
	Caption   string
	Source    string
	SourceRef string
	ListingID *int64
	Position  *int
}

func (s *Store) photoPath(sha, size string) string {
	name := sha + ".jpg"
	if size == "thumb" || size == "medium" {
		name = sha + "-" + size + ".jpg"
	}
	return filepath.Join(s.photosDir, sha[:2], name)
}

func writeAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".tmp-*")
	if err != nil {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	return os.Rename(tmp.Name(), path)
}

func (s *Store) writePhotoFile(p *imaging.Prepared) error {
	path := s.photoPath(p.SHA256, "full")
	if _, err := os.Stat(path); err == nil {
		return nil
	}
	if err := writeAtomic(path, p.JPEG); err != nil {
		return fmt.Errorf("write photo: %w", err)
	}
	return nil
}

// insertPhoto adds a photo row unless the car already has the same bytes. idx breaks position ties in batches.
func insertPhoto(tx *sql.Tx, carID int64, p *imaging.Prepared, m PhotoMeta, now float64, idx int) (*photoRow, bool, error) {
	if m.Source == "" {
		m.Source = "other"
	}
	if !slices.Contains(api.PhotoSources, m.Source) {
		return nil, false, invalidf("source must be one of %s", strings.Join(api.PhotoSources, "|"))
	}
	var existing int64
	err := tx.QueryRow("SELECT id FROM photos WHERE car_id = ? AND sha256 = ?", carID, p.SHA256).Scan(&existing)
	if err == nil {
		ph, err := loadPhoto(tx, existing)
		return ph, false, err
	} else if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	if m.ListingID != nil {
		var cid int64
		if err := tx.QueryRow("SELECT car_id FROM listings WHERE id = ?", *m.ListingID).Scan(&cid); err != nil || cid != carID {
			return nil, false, invalidf("listing %d does not belong to car %d", *m.ListingID, carID)
		}
	}
	var pos int
	if m.Position != nil {
		pos = *m.Position
	} else if err := tx.QueryRow("SELECT COALESCE(MAX(position), -1) + 1 FROM photos WHERE car_id = ?", carID).Scan(&pos); err != nil {
		return nil, false, err
	}
	r, err := tx.Exec(`INSERT INTO photos (car_id, listing_id, sha256, phash, width, height, position, cover, caption, source, source_ref, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)`,
		carID, nullInt64(m.ListingID), p.SHA256, int64(p.PHash), p.Width, p.Height, pos, nullStr(m.Caption), m.Source,
		nullStr(m.SourceRef), now+float64(idx)*1e-6)
	if err != nil {
		return nil, false, err
	}
	id, err := r.LastInsertId()
	if err != nil {
		return nil, false, err
	}
	ph, err := loadPhoto(tx, id)
	return ph, true, err
}

// AddPhoto handles POST /cars/{car}/photos. created=false when the car already had these bytes.
// Adding a photo re-runs dedupe; if that merges the car the photo of the live car is returned.
func (s *Store) AddPhoto(ctx context.Context, ref string, p *imaging.Prepared, m PhotoMeta, author string) (*api.Photo, bool, error) {
	if err := s.writePhotoFile(p); err != nil {
		return nil, false, err
	}
	var out *api.Photo
	created := false
	err := s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		ph, c, err := insertPhoto(tx, id, p, m, now, 0)
		if err != nil {
			return err
		}
		created = c
		if c {
			live, err := rededupe(tx, id, author, now)
			if err != nil {
				return err
			}
			var pid int64
			if err := tx.QueryRow("SELECT id FROM photos WHERE car_id = ? AND sha256 = ?", live, p.SHA256).Scan(&pid); err != nil {
				return err
			}
			if ph, err = loadPhoto(tx, pid); err != nil {
				return err
			}
		}
		out = &ph.Photo
		return nil
	})
	return out, created, err
}

// PatchPhoto handles PATCH /photos/{id}.
func (s *Store) PatchPhoto(ctx context.Context, id int64, in api.PhotoPatch) (*api.Photo, error) {
	var out *api.Photo
	err := s.tx(ctx, func(tx *sql.Tx) error {
		ph, err := loadPhoto(tx, id)
		if err != nil {
			return err
		}
		if in.Caption != nil {
			if _, err := tx.Exec("UPDATE photos SET caption = ? WHERE id = ?", nullStr(strings.TrimSpace(*in.Caption)), id); err != nil {
				return err
			}
		}
		if in.Position != nil {
			if _, err := tx.Exec("UPDATE photos SET position = ? WHERE id = ?", *in.Position, id); err != nil {
				return err
			}
		}
		if in.Cover != nil {
			if *in.Cover {
				if _, err := tx.Exec("UPDATE photos SET cover = 0 WHERE car_id = ?", ph.CarID); err != nil {
					return err
				}
			}
			if _, err := tx.Exec("UPDATE photos SET cover = ? WHERE id = ?", boolInt(*in.Cover), id); err != nil {
				return err
			}
		}
		if ph, err = loadPhoto(tx, id); err != nil {
			return err
		}
		out = &ph.Photo
		return nil
	})
	return out, err
}

// DeletePhoto handles DELETE /photos/{id}; files are removed once no row references them.
func (s *Store) DeletePhoto(ctx context.Context, id int64) error {
	var sha string
	orphan := false
	err := s.tx(ctx, func(tx *sql.Tx) error {
		ph, err := loadPhoto(tx, id)
		if err != nil {
			return err
		}
		sha = ph.SHA
		if _, err := tx.Exec("DELETE FROM photos WHERE id = ?", id); err != nil {
			return err
		}
		var n int
		if err := tx.QueryRow("SELECT COUNT(*) FROM photos WHERE sha256 = ?", sha).Scan(&n); err != nil {
			return err
		}
		orphan = n == 0
		return nil
	})
	if err == nil && orphan {
		for _, size := range []string{"full", "thumb", "medium"} {
			os.Remove(s.photoPath(sha, size))
		}
	}
	return err
}

// PhotoFile returns the JPEG path for a photo size (thumb|medium|full), rendering derived sizes lazily.
func (s *Store) PhotoFile(ctx context.Context, id int64, size string) (path, sha string, err error) {
	if size == "" {
		size = "full"
	}
	if !slices.Contains([]string{"thumb", "medium", "full"}, size) {
		return "", "", badRequestf("size must be thumb|medium|full")
	}
	err = s.tx(ctx, func(tx *sql.Tx) error {
		ph, err := loadPhoto(tx, id)
		if err != nil {
			return err
		}
		sha = ph.SHA
		return nil
	})
	if err != nil {
		return "", "", err
	}
	full := s.photoPath(sha, "full")
	if size == "full" {
		return full, sha, nil
	}
	path = s.photoPath(sha, size)
	if _, err := os.Stat(path); err == nil {
		return path, sha, nil
	}
	data, err := os.ReadFile(full)
	if err != nil {
		return "", "", fmt.Errorf("read photo %d: %w", id, err)
	}
	width := imaging.ThumbWidth
	if size == "medium" {
		width = imaging.MediumWidth
	}
	out, err := imaging.Resize(data, width)
	if err != nil {
		return "", "", err
	}
	if err := writeAtomic(path, out); err != nil {
		return "", "", err
	}
	return path, sha, nil
}

// removePhotoFiles deletes the stored and derived files of shas no photo row references any more.
func (s *Store) removePhotoFiles(ctx context.Context, shas []string) {
	for _, sha := range shas {
		var n int
		if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM photos WHERE sha256 = ?", sha).Scan(&n); err != nil || n > 0 {
			continue
		}
		for _, size := range []string{"full", "thumb", "medium"} {
			os.Remove(s.photoPath(sha, size))
		}
	}
}
