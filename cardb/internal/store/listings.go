package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"slices"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/imaging"
)

// UpsertPhoto is a photo fetched from photo_urls, ready to attach.
type UpsertPhoto struct {
	Prepared *imaging.Prepared
	URL      string
}

type listingRow struct {
	ID        int64
	CarID     int64
	Site      string
	Status    string
	Price     sql.NullInt64
	SellerID  sql.NullInt64
	RemovedAt sql.NullFloat64
}

func findListing(tx *sql.Tx, nu NormURL) (*listingRow, error) {
	q := "SELECT id, car_id, site, status, price, seller_id, removed_at FROM listings WHERE url_key = ?"
	args := []any{nu.Key}
	if nu.SiteRef != "" {
		q += " OR (site = ? AND site_ref = ?)"
		args = append(args, nu.Site, nu.SiteRef)
	}
	var l listingRow
	err := tx.QueryRow(q+" ORDER BY id LIMIT 1", args...).Scan(&l.ID, &l.CarID, &l.Site, &l.Status, &l.Price, &l.SellerID, &l.RemovedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return &l, err
}

func loadListingRow(tx *sql.Tx, id int64) (*listingRow, error) {
	var l listingRow
	err := tx.QueryRow("SELECT id, car_id, site, status, price, seller_id, removed_at FROM listings WHERE id = ?", id).
		Scan(&l.ID, &l.CarID, &l.Site, &l.Status, &l.Price, &l.SellerID, &l.RemovedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, notFoundf("listing %d not found", id)
	}
	return &l, err
}

func isGone(status string) bool { return status == "removed" || status == "sold" }

// setListingStatus changes a listing's status, writing listing_removed / listing_relisted events.
func setListingStatus(tx *sql.Tx, l *listingRow, status string, at float64, author string) error {
	if status == "" || status == l.Status {
		return nil
	}
	if !slices.Contains(api.ListingStatuses, status) {
		return invalidf("listing status must be one of %s", strings.Join(api.ListingStatuses, "|"))
	}
	from := l.Status
	var removedAt any
	switch {
	case isGone(status) && l.RemovedAt.Valid:
		removedAt = l.RemovedAt.Float64
	case isGone(status):
		removedAt = at
	}
	if _, err := tx.Exec("UPDATE listings SET status = ?, removed_at = ? WHERE id = ?", status, removedAt, l.ID); err != nil {
		return err
	}
	l.Status = status
	lid := l.ID
	data := map[string]any{"listing_id": l.ID, "from": from, "to": status}
	switch {
	case isGone(status):
		_, err := addEvent(tx, ev{CarID: l.CarID, ListingID: &lid, Type: "listing_removed", At: at, Author: author,
			Summary: fmt.Sprintf("listing %s (%s)", status, l.Site), Data: data})
		return err
	case isGone(from) && status == "live":
		_, err := addEvent(tx, ev{CarID: l.CarID, ListingID: &lid, Type: "listing_relisted", At: at, Author: author,
			Summary: fmt.Sprintf("listing relisted (%s)", l.Site), Data: data})
		return err
	}
	return nil
}

// observePrice records a price seen at time at. Returns true if it wrote a price_change event.
func observePrice(tx *sql.Tx, l *listingRow, price int, note string, at float64, author string) (bool, error) {
	if price < 0 {
		return false, invalidf("price must be ≥ 0")
	}
	type pt struct {
		price int
		at    float64
	}
	rows, err := tx.Query("SELECT price, at FROM price_points WHERE listing_id = ? ORDER BY at, id", l.ID)
	if err != nil {
		return false, err
	}
	var pts []pt
	for rows.Next() {
		var p pt
		if err := rows.Scan(&p.price, &p.at); err != nil {
			rows.Close()
			return false, err
		}
		pts = append(pts, p)
	}
	rows.Close()
	for _, p := range pts {
		if p.price == price && math.Abs(p.at-at) < 0.001 {
			return false, nil // exact replay
		}
	}
	insert := func() error {
		_, err := tx.Exec("INSERT INTO price_points (listing_id, price, at, note) VALUES (?, ?, ?, ?)", l.ID, price, at, nullStr(note))
		return err
	}
	event := func(from int) error {
		lid := l.ID
		_, err := addEvent(tx, ev{CarID: l.CarID, ListingID: &lid, Type: "price_change", At: at, Author: author,
			Summary: fmt.Sprintf("price %s → %s € (%s)", fmtThousands(int64(from)), fmtThousands(int64(price)), l.Site),
			Data:    map[string]any{"from": from, "to": price, "listing_id": l.ID}})
		return err
	}
	if len(pts) == 0 {
		if err := insert(); err != nil {
			return false, err
		}
		_, err := tx.Exec("UPDATE listings SET price = ? WHERE id = ?", price, l.ID)
		l.Price = sql.NullInt64{Int64: int64(price), Valid: true}
		return false, err
	}
	last := pts[len(pts)-1]
	if at >= last.at {
		if price == last.price {
			if !l.Price.Valid || l.Price.Int64 != int64(price) {
				_, err := tx.Exec("UPDATE listings SET price = ? WHERE id = ?", price, l.ID)
				return false, err
			}
			return false, nil
		}
		if err := insert(); err != nil {
			return false, err
		}
		if _, err := tx.Exec("UPDATE listings SET price = ? WHERE id = ?", price, l.ID); err != nil {
			return false, err
		}
		l.Price = sql.NullInt64{Int64: int64(price), Valid: true}
		return true, event(last.price)
	}
	// Backfill of an older observation: keep the current price, slot the point into history.
	var prev *pt
	for i := range pts {
		if pts[i].at <= at {
			prev = &pts[i]
		}
	}
	if prev != nil && prev.price == price {
		return false, nil
	}
	if err := insert(); err != nil {
		return false, err
	}
	if prev != nil {
		return true, event(prev.price)
	}
	return false, nil
}

// carFields applies the car-level parts of an upsert to an existing car (fill-if-empty unless overwrite).
// Returns whether identity fields (VIN/plate/seller contacts) changed.
func (s *Store) carFields(tx *sql.Tx, car *carRow, in *api.ListingUpsert, specs map[string]any, created bool, author string, at float64, lid *int64) (bool, error) {
	identity := false
	if !created {
		changes, err := writeSpecs(tx, car, specs, in.Overwrite, at)
		if err != nil {
			return false, err
		}
		// Filling an empty field is not a change; only replaced values make a spec_change event.
		replaced := map[string]specChange{}
		for k, ch := range changes {
			if ch.From != nil {
				replaced[k] = ch
			}
		}
		if err := specChangeEvent(tx, car.ID, replaced, author, at, lid); err != nil {
			return false, err
		}
		_, v := changes["vin"]
		_, p := changes["plate"]
		identity = v || p
	}
	if in.Seller != nil && !created {
		sid, changed, err := s.ensureSeller(tx, car.SellerID.Int64, in.Seller, in.Overwrite, false, at)
		if err != nil {
			return false, err
		}
		if sid != 0 && sid != car.SellerID.Int64 {
			if _, err := tx.Exec("UPDATE cars SET seller_id = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", sid, at, car.ID); err != nil {
				return false, err
			}
			car.SellerID = sql.NullInt64{Int64: sid, Valid: true}
			changed = true
		}
		identity = identity || changed
	}
	if !created {
		if in.Slug != "" {
			if !car.Slug.Valid || in.Overwrite {
				if err := setSlug(tx, car.ID, in.Slug); err != nil {
					return false, err
				}
			} else if err := addAlias(tx, car.ID, in.Slug); err != nil {
				return false, err
			}
		}
		for _, a := range in.Aliases {
			if err := addAlias(tx, car.ID, a); err != nil {
				return false, err
			}
		}
		if s := strings.TrimSpace(in.Summary); s != "" && (!car.Summary.Valid || in.Overwrite) && car.Summary.String != s {
			if _, err := tx.Exec("UPDATE cars SET summary = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", s, at, car.ID); err != nil {
				return false, err
			}
		}
		if in.Status != "" && in.Overwrite {
			if _, err := setStatus(tx, car, in.Status, "", author, at); err != nil {
				return false, err
			}
		}
	}
	for _, k := range sortedKeys(in.Options) {
		o := in.Options[k]
		if o.Author == "" {
			o.Author = author
		}
		if _, err := setOption(tx, car.ID, k, o, atOr(o.At, at), !in.Overwrite, !created); err != nil {
			return false, err
		}
	}
	for _, k := range sortedKeys(in.Facts) {
		f := in.Facts[k]
		if f.Author == "" {
			f.Author = author
		}
		if _, err := setFact(tx, car.ID, k, f, atOr(f.At, at), !in.Overwrite, !created); err != nil {
			return false, err
		}
	}
	return identity, nil
}

func validateUpsert(in *api.ListingUpsert) error {
	if in.ListingStatus != "" && !slices.Contains(api.ListingStatuses, in.ListingStatus) {
		return invalidf("listing_status must be one of %s", strings.Join(api.ListingStatuses, "|"))
	}
	if in.Status != "" {
		if err := validStatus(in.Status); err != nil {
			return err
		}
	}
	if in.Price != nil && *in.Price < 0 {
		return invalidf("price must be ≥ 0")
	}
	vat, err := normPriceVat(in.PriceVat)
	if err != nil {
		return err
	}
	in.PriceVat = vat
	for k, o := range in.Options {
		if err := validateOption(k, o); err != nil {
			return err
		}
	}
	for k, f := range in.Facts {
		if err := validateFact(k, f); err != nil {
			return err
		}
	}
	if len(in.Raw) > 0 && !json.Valid(in.Raw) {
		return invalidf("raw must be valid JSON")
	}
	return nil
}

func sellerProbe(in *api.SellerInput, home string) (phones []string, sellerType string) {
	sellerType = "unknown"
	if in == nil {
		return nil, sellerType
	}
	if in.Type != nil && *in.Type != "" {
		sellerType = *in.Type
	}
	for _, c := range in.Contacts {
		if c.Kind == "phone" || c.Kind == "whatsapp" {
			if v := NormalizePhone(c.Value, home); v != "" {
				phones = append(phones, v)
			}
		}
	}
	return phones, sellerType
}

// UpsertListing handles POST /listings/upsert. Photos are pre-fetched by the caller.
func (s *Store) UpsertListing(ctx context.Context, in api.ListingUpsert, photos []UpsertPhoto, author string) (*api.UpsertResult, error) {
	if err := validateUpsert(&in); err != nil {
		return nil, err
	}
	nu, err := NormalizeURL(in.URL)
	if err != nil {
		return nil, err
	}
	if nu.SiteRef == "" && in.Site != "" && nu.Site == hostOf(nu.Key) {
		nu.Site = strings.TrimSpace(in.Site)
	}
	specs, err := specsMap(in.CarSpecs)
	if err != nil {
		return nil, err
	}
	if _, ok := specs["country"]; !ok && nu.Country != "" {
		specs["country"] = nu.Country
	}
	for _, p := range photos {
		if err := s.writePhotoFile(p.Prepared); err != nil {
			return nil, err
		}
	}

	res := &api.UpsertResult{DuplicateCandidates: []api.DuplicateCandidate{}, PhotoErrors: []string{}}
	err = s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		at := atOr(in.SeenAt, now)
		l, err := findListing(tx, nu)
		if err != nil {
			return err
		}
		priceOK, err := s.checkUpsertPrice(tx, l, &in, specs) // before any write
		if err != nil {
			return err
		}
		var carID int64
		identity := false
		if l != nil {
			if carID, err = resolveCar(tx, itoa(l.CarID)); err != nil {
				return err
			}
			l.CarID = carID
			res.ListingID = l.ID
			sets := []string{"last_seen_at = MAX(last_seen_at, ?)"}
			args := []any{at}
			if t := strings.TrimSpace(in.Title); t != "" {
				sets = append(sets, "title = ?")
				args = append(args, t)
			}
			if in.PriceNote != "" {
				sets = append(sets, "price_note = ?")
				args = append(args, in.PriceNote)
			}
			if len(in.Raw) > 0 {
				sets = append(sets, "raw = ?")
				args = append(args, string(in.Raw))
			}
			if in.PriceVat != "" {
				sets = append(sets, "price_vat = ?")
				args = append(args, in.PriceVat)
			}
			args = append(args, l.ID)
			if _, err := tx.Exec("UPDATE listings SET "+strings.Join(sets, ", ")+" WHERE id = ?", args...); err != nil {
				return err
			}
			if in.Price != nil {
				if res.PriceChanged, err = observePrice(tx, l, *in.Price, in.PriceNote, at, author); err != nil {
					return err
				}
			}
			if err := applyPriceVerdict(tx, priceOK, carID, l.ID, author, at); err != nil {
				return err
			}
			status := in.ListingStatus
			if status == "" && isGone(l.Status) && (!l.RemovedAt.Valid || at > l.RemovedAt.Float64) {
				status = "live" // seen after it was removed: relisted; older sightings (replays) change nothing
			}
			wasGone := isGone(l.Status)
			if err := setListingStatus(tx, l, status, at, author); err != nil {
				return err
			}
			res.Relisted = wasGone && l.Status == "live"
			car, err := loadCar(tx, carID)
			if err != nil {
				return err
			}
			lid := l.ID
			if identity, err = s.carFields(tx, car, &in, specs, false, author, at, &lid); err != nil {
				return err
			}
			if !l.SellerID.Valid && car.SellerID.Valid {
				if _, err := tx.Exec("UPDATE listings SET seller_id = ? WHERE id = ?", car.SellerID.Int64, l.ID); err != nil {
					return err
				}
			}
		} else {
			res.ListingCreated = true
			var linkedBy string
			if in.Car != "" {
				if carID, err = resolveCar(tx, in.Car); err != nil {
					return err
				}
				linkedBy = "car_param"
			} else {
				p := probeFromSpecs(specs)
				p.Phones, p.SellerType = sellerProbe(in.Seller, s.profile.Owner.Home.Country)
				for _, ph := range photos {
					p.PHashes = append(p.PHashes, ph.Prepared.PHash)
				}
				all, _, err := loadProbes(tx)
				if err != nil {
					return err
				}
				ms, err := findMatches(tx, p, all)
				if err != nil {
					return err
				}
				if len(ms) > 0 && ms[0].Certain != "" {
					carID, linkedBy = ms[0].CarID, ms[0].Certain
				}
			}
			priceStr := ""
			if in.Price != nil {
				priceStr = " " + fmtThousands(int64(*in.Price)) + " €"
			}
			var car *carRow
			if carID == 0 {
				var sellerID int64
				if in.Seller != nil {
					if sellerID, _, err = s.ensureSeller(tx, 0, in.Seller, false, false, at); err != nil {
						return err
					}
				}
				carID, err = insertCar(tx, newCar{Specs: specs, Slug: in.Slug, Aliases: in.Aliases, Summary: strings.TrimSpace(in.Summary),
					Status: in.Status, SellerID: sellerID}, at)
				if err != nil {
					return err
				}
				res.CarCreated = true
				if car, err = loadCar(tx, carID); err != nil {
					return err
				}
				if _, err := addEvent(tx, ev{CarID: carID, Type: "created", At: at, Author: author,
					Summary: fmt.Sprintf("created %s from %s listing%s", car.title(), nu.Site, priceStr)}); err != nil {
					return err
				}
			} else {
				res.LinkedBy = &linkedBy
				if car, err = loadCar(tx, carID); err != nil {
					return err
				}
			}
			status := in.ListingStatus
			if status == "" {
				status = "live"
			}
			var removedAt any
			if isGone(status) {
				removedAt = at
			}
			var raw any
			if len(in.Raw) > 0 {
				raw = string(in.Raw)
			}
			var sellerArg any
			if car.SellerID.Valid {
				sellerArg = car.SellerID.Int64
			}
			vat := in.PriceVat
			if vat == "" {
				vat = "unknown"
			}
			r, err := tx.Exec(`INSERT INTO listings (car_id, url, url_key, site, site_ref, title, status, price, price_note, seller_id,
				first_seen_at, last_seen_at, removed_at, raw, price_vat) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)`,
				carID, nu.URL, nu.Key, nu.Site, nullStr(nu.SiteRef), nullStr(strings.TrimSpace(in.Title)), status,
				nullStr(in.PriceNote), sellerArg, at, at, removedAt, raw, vat)
			if err != nil {
				return err
			}
			if res.ListingID, err = r.LastInsertId(); err != nil {
				return err
			}
			l = &listingRow{ID: res.ListingID, CarID: carID, Site: nu.Site, Status: status}
			if in.Price != nil {
				if _, err := observePrice(tx, l, *in.Price, in.PriceNote, at, author); err != nil {
					return err
				}
			}
			if err := applyPriceVerdict(tx, priceOK, carID, l.ID, author, at); err != nil {
				return err
			}
			lid := res.ListingID
			if !res.CarCreated {
				summary := fmt.Sprintf("listing added: %s%s", nu.Site, priceStr)
				if linkedBy != "car_param" {
					summary += " (linked by " + linkedBy + ")"
				}
				if _, err := addEvent(tx, ev{CarID: carID, ListingID: &lid, Type: "listing_added", At: at, Author: author,
					Summary: summary, Data: map[string]any{"listing_id": lid, "url": nu.URL, "linked_by": linkedBy}}); err != nil {
					return err
				}
			}
			if identity, err = s.carFields(tx, car, &in, specs, res.CarCreated, author, at, &lid); err != nil {
				return err
			}
			if car.SellerID.Valid && sellerArg == nil {
				if _, err := tx.Exec("UPDATE listings SET seller_id = ? WHERE id = ?", car.SellerID.Int64, lid); err != nil {
					return err
				}
			}
			identity = true // new listing: always look for duplicates
		}

		lid := res.ListingID
		added := 0
		for i, p := range photos {
			ref := p.URL
			_, created, err := insertPhoto(tx, carID, p.Prepared, PhotoMeta{Source: "ad", SourceRef: ref, ListingID: &lid}, now, i)
			if err != nil {
				return err
			}
			if created {
				added++
			}
		}
		if identity || added > 0 {
			if carID, err = rededupe(tx, carID, author, now); err != nil {
				return err
			}
		}
		res.CarID = carID
		res.DuplicateCandidates, err = loadDuplicates(tx, "status = 'proposed' AND (car_a = ? OR car_b = ?)", carID, carID, carID)
		return err
	})
	if err != nil {
		return nil, err
	}
	return res, nil
}

func hostOf(key string) string {
	if i := strings.IndexAny(key, "/?"); i >= 0 {
		return key[:i]
	}
	return key
}

// PatchListing handles PATCH /listings/{id}.
func (s *Store) PatchListing(ctx context.Context, id int64, in api.ListingPatch, author string) (*api.Listing, error) {
	var out *api.Listing
	err := s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		l, err := loadListingRow(tx, id)
		if err != nil {
			return err
		}
		if l.CarID, err = resolveCar(tx, itoa(l.CarID)); err != nil {
			return err
		}
		vat, err := normPriceVat(in.PriceVat)
		if err != nil {
			return err
		}
		gate := priceGate{Price: in.Price, Note: in.PriceNote, Vat: vat, Force: in.Force}
		if err := gateFromListing(tx, s.rk.fam, &gate, l, l.CarID); err != nil {
			return err
		}
		priceOK, err := s.checkPrice(tx, gate)
		if err != nil {
			return err
		}
		if vat != "" {
			if _, err := tx.Exec("UPDATE listings SET price_vat = ? WHERE id = ?", vat, id); err != nil {
				return err
			}
		}
		if in.PriceNote != "" {
			if _, err := tx.Exec("UPDATE listings SET price_note = ? WHERE id = ?", in.PriceNote, id); err != nil {
				return err
			}
		}
		if in.Price != nil {
			if _, err := observePrice(tx, l, *in.Price, in.PriceNote, now, author); err != nil {
				return err
			}
		}
		if err := applyPriceVerdict(tx, priceOK, l.CarID, l.ID, author, now); err != nil {
			return err
		}
		if err := setListingStatus(tx, l, in.Status, now, author); err != nil {
			return err
		}
		out, err = loadListing(tx, id)
		return err
	})
	return out, err
}

// GetListing handles GET /listings/{id}.
func (s *Store) GetListing(ctx context.Context, id int64) (*api.Listing, error) {
	var out *api.Listing
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		out, err = loadListing(tx, id)
		return err
	})
	return out, err
}

// FindListings handles GET /listings.
func (s *Store) FindListings(ctx context.Context, rawURL, site, status string) ([]api.Listing, error) {
	where := []string{"1 = 1"}
	var args []any
	if rawURL != "" {
		nu, err := NormalizeURL(rawURL)
		if err != nil {
			return nil, badRequestf("%s", err.Error())
		}
		if nu.SiteRef != "" {
			where = append(where, "(url_key = ? OR (site = ? AND site_ref = ?))")
			args = append(args, nu.Key, nu.Site, nu.SiteRef)
		} else {
			where = append(where, "url_key = ?")
			args = append(args, nu.Key)
		}
	}
	if site != "" {
		where = append(where, "site = ? COLLATE NOCASE")
		args = append(args, site)
	}
	if status != "" {
		if !slices.Contains(api.ListingStatuses, status) {
			return nil, badRequestf("status must be one of %s", strings.Join(api.ListingStatuses, "|"))
		}
		where = append(where, "status = ?")
		args = append(args, status)
	}
	var out []api.Listing
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		out, err = loadListings(tx, strings.Join(where, " AND "), args...)
		return err
	})
	return out, err
}
