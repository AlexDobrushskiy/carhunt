package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
)

func itoa(n int64) string { return strconv.FormatInt(n, 10) }

func placeholders(n int) string { return strings.TrimSuffix(strings.Repeat("?, ", n), ", ") }

const listingSelect = `SELECT id, car_id, url, site, site_ref, title, status, price, price_note, seller_id,
	first_seen_at, last_seen_at, removed_at, raw, price_vat, price_flags FROM listings`

func loadListings(tx *sql.Tx, where string, args ...any) ([]api.Listing, error) {
	rows, err := tx.Query(listingSelect+" WHERE "+where+" ORDER BY first_seen_at, id", args...)
	if err != nil {
		return nil, err
	}
	out := []api.Listing{}
	idx := map[int64]int{}
	for rows.Next() {
		var l api.Listing
		var siteRef, title, priceNote, raw sql.NullString
		var price, sellerID sql.NullInt64
		var first, last float64
		var removed sql.NullFloat64
		var flags string
		if err := rows.Scan(&l.ID, &l.CarID, &l.URL, &l.Site, &siteRef, &title, &l.Status, &price, &priceNote,
			&sellerID, &first, &last, &removed, &raw, &l.PriceVat, &flags); err != nil {
			rows.Close()
			return nil, err
		}
		l.PriceFlags = parseList(flags)
		l.SiteRef, l.Title, l.PriceNote = strPtr(siteRef), strPtr(title), strPtr(priceNote)
		l.Price, l.SellerID = intPtr(price), int64Ptr(sellerID)
		l.FirstSeenAt, l.LastSeenAt, l.RemovedAt = fromTS(first), fromTS(last), fromNullTS(removed)
		if raw.Valid {
			l.Raw = json.RawMessage(raw.String)
		}
		l.PriceHistory = []api.PricePoint{}
		idx[l.ID] = len(out)
		out = append(out, l)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return out, nil
	}
	ids := make([]any, 0, len(out))
	for _, l := range out {
		ids = append(ids, l.ID)
	}
	prows, err := tx.Query("SELECT listing_id, price, at, note FROM price_points WHERE listing_id IN ("+placeholders(len(ids))+") ORDER BY at, id", ids...)
	if err != nil {
		return nil, err
	}
	defer prows.Close()
	for prows.Next() {
		var lid int64
		var p api.PricePoint
		var at float64
		var note sql.NullString
		if err := prows.Scan(&lid, &p.Price, &at, &note); err != nil {
			return nil, err
		}
		p.At, p.Note = fromTS(at), strPtr(note)
		i := idx[lid]
		out[i].PriceHistory = append(out[i].PriceHistory, p)
	}
	return out, prows.Err()
}

func loadListing(tx *sql.Tx, id int64) (*api.Listing, error) {
	ls, err := loadListings(tx, "id = ?", id)
	if err != nil {
		return nil, err
	}
	if len(ls) == 0 {
		return nil, notFoundf("listing %d not found", id)
	}
	return &ls[0], nil
}

// priceInfo is the per-listing subset used to derive a car's price.
type priceInfo struct {
	URL        string
	Live       bool
	Price      *int
	Note       *string
	FirstPrice *int
	Points     int
	LastSeen   float64
	Flags      []string
}

// derivePrice: min price over live listings, else the most recently seen listing's price.
func derivePrice(ls []priceInfo) (price *int, note *string, drop *int, primary *string) {
	best := pricedListing(ls)
	if best != nil {
		p := *best.Price
		price, note = &p, best.Note
		if best.Points >= 2 && best.FirstPrice != nil {
			d := *best.FirstPrice - p
			drop = &d
		}
		u := best.URL
		primary = &u
		return
	}
	var pick *priceInfo
	for i := range ls {
		l := &ls[i]
		if pick == nil || (l.Live && !pick.Live) || (l.Live == pick.Live && l.LastSeen > pick.LastSeen) {
			pick = l
		}
	}
	if pick != nil {
		u := pick.URL
		primary = &u
	}
	return
}

// pricedListing is the listing that gives the car's price (see derivePrice), nil if none has a price.
func pricedListing(ls []priceInfo) *priceInfo {
	var best *priceInfo
	for i := range ls {
		l := &ls[i]
		if !l.Live || l.Price == nil {
			continue
		}
		if best == nil || *l.Price < *best.Price || (*l.Price == *best.Price && l.LastSeen > best.LastSeen) {
			best = l
		}
	}
	if best == nil {
		for i := range ls {
			l := &ls[i]
			if l.Price == nil {
				continue
			}
			if best == nil || l.LastSeen > best.LastSeen {
				best = l
			}
		}
	}
	return best
}

func priceInfos(ls []api.Listing) []priceInfo {
	out := make([]priceInfo, 0, len(ls))
	for _, l := range ls {
		pi := priceInfo{URL: l.URL, Live: l.Status == "live", Price: l.Price, Note: l.PriceNote,
			Points: len(l.PriceHistory), LastSeen: ts(l.LastSeenAt), Flags: l.PriceFlags}
		if len(l.PriceHistory) > 0 {
			fp := l.PriceHistory[0].Price
			pi.FirstPrice = &fp
		}
		out = append(out, pi)
	}
	return out
}

const photoSelect = `SELECT id, car_id, listing_id, sha256, phash, width, height, position, cover, caption, source,
	source_ref, created_at FROM photos`

type photoRow struct {
	api.Photo
	SHA string
}

func scanPhoto(sc scanner) (*photoRow, error) {
	var p photoRow
	var listingID sql.NullInt64
	var phash int64
	var cover int
	var caption, sourceRef sql.NullString
	var created float64
	if err := sc.Scan(&p.ID, &p.CarID, &listingID, &p.SHA, &phash, &p.Width, &p.Height, &p.Position, &cover,
		&caption, &p.Source, &sourceRef, &created); err != nil {
		return nil, err
	}
	p.ListingID = int64Ptr(listingID)
	p.PHash = fmt.Sprintf("%016x", uint64(phash))
	p.Cover = cover != 0
	p.Caption, p.SourceRef = strPtr(caption), strPtr(sourceRef)
	p.CreatedAt = fromTS(created)
	p.URL = "/api/v1/photos/" + itoa(p.ID)
	return &p, nil
}

func loadPhotos(tx *sql.Tx, carID int64) ([]api.Photo, error) {
	rows, err := tx.Query(photoSelect+" WHERE car_id = ? ORDER BY position, id", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Photo{}
	for rows.Next() {
		p, err := scanPhoto(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p.Photo)
	}
	return out, rows.Err()
}

func loadPhoto(tx *sql.Tx, id int64) (*photoRow, error) {
	p, err := scanPhoto(tx.QueryRow(photoSelect+" WHERE id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, notFoundf("photo %d not found", id)
	}
	return p, err
}

const eventSelect = "SELECT id, car_id, listing_id, type, at, author, summary, data FROM events"

func scanEvent(sc scanner) (*api.Event, error) {
	var e api.Event
	var listingID sql.NullInt64
	var at float64
	var data sql.NullString
	if err := sc.Scan(&e.ID, &e.CarID, &listingID, &e.Type, &at, &e.Author, &e.Summary, &data); err != nil {
		return nil, err
	}
	e.ListingID, e.At = int64Ptr(listingID), fromTS(at)
	if data.Valid {
		e.Data = json.RawMessage(data.String)
	}
	return &e, nil
}

func loadEvents(tx *sql.Tx, carID int64) ([]api.Event, error) {
	rows, err := tx.Query(eventSelect+" WHERE car_id = ? ORDER BY at DESC, id DESC", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Event{}
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *e)
	}
	return out, rows.Err()
}

const messageSelect = `SELECT id, car_id, channel, direction, at, sender_kind, sender, counterpart, text, attachments,
	delivery, error, external_id, dedupe_key, deleted_at, deleted_by, deleted_reason FROM messages`

// liveMessage filters out soft-deleted rows; every read except key lookups uses it.
const liveMessage = "deleted_at IS NULL"

func scanMessage(sc scanner) (*api.Message, error) {
	var m api.Message
	var at float64
	var counterpart, errStr, extID, dedupeKey, delBy, delReason sql.NullString
	var delAt sql.NullFloat64
	var att string
	if err := sc.Scan(&m.ID, &m.CarID, &m.Channel, &m.Direction, &at, &m.SenderKind, &m.Sender, &counterpart,
		&m.Text, &att, &m.Delivery, &errStr, &extID, &dedupeKey, &delAt, &delBy, &delReason); err != nil {
		return nil, err
	}
	m.At = fromTS(at)
	if delAt.Valid {
		t := fromTS(delAt.Float64)
		m.DeletedAt = &t
	}
	m.DeletedBy, m.DeletedReason = strPtr(delBy), strPtr(delReason)
	m.Counterpart, m.Error, m.ExternalID, m.DedupeKey = strPtr(counterpart), strPtr(errStr), strPtr(extID), strPtr(dedupeKey)
	_ = json.Unmarshal([]byte(att), &m.Attachments)
	if m.Attachments == nil {
		m.Attachments = []api.Attachment{}
	}
	return &m, nil
}

func loadMessages(tx *sql.Tx, carID int64) ([]api.Message, error) {
	rows, err := tx.Query(messageSelect+" WHERE car_id = ? AND "+liveMessage+" ORDER BY at, id", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Message{}
	for rows.Next() {
		m, err := scanMessage(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *m)
	}
	return out, rows.Err()
}

const noteSelect = "SELECT id, car_id, author, author_kind, text, pinned, created_at, updated_at FROM notes"

func scanNote(sc scanner) (*api.Note, error) {
	var n api.Note
	var pinned int
	var c, u float64
	if err := sc.Scan(&n.ID, &n.CarID, &n.Author, &n.AuthorKind, &n.Text, &pinned, &c, &u); err != nil {
		return nil, err
	}
	n.Pinned, n.CreatedAt, n.UpdatedAt = pinned != 0, fromTS(c), fromTS(u)
	return &n, nil
}

func loadNotes(tx *sql.Tx, carID int64, pinnedFirst bool) ([]api.Note, error) {
	order := "created_at DESC, id DESC"
	if pinnedFirst {
		order = "pinned DESC, " + order
	}
	rows, err := tx.Query(noteSelect+" WHERE car_id = ? ORDER BY "+order, carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Note{}
	for rows.Next() {
		n, err := scanNote(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *n)
	}
	return out, rows.Err()
}

func loadVerdict(tx *sql.Tx, carID int64) (*api.Verdict, error) {
	var v api.Verdict
	var note sql.NullString
	var at float64
	err := tx.QueryRow("SELECT value, note, author, updated_at FROM verdicts WHERE car_id = ?", carID).Scan(&v.Value, &note, &v.Author, &at)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	v.Note, v.UpdatedAt = strPtr(note), fromTS(at)
	return &v, nil
}

func loadOptions(tx *sql.Tx, carID int64) ([]api.Option, error) {
	rows, err := tx.Query("SELECT key, value, source, source_ref, note, author, updated_at FROM options WHERE car_id = ? ORDER BY key", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Option{}
	for rows.Next() {
		var o api.Option
		var ref, note sql.NullString
		var at float64
		if err := rows.Scan(&o.Key, &o.Value, &o.Source, &ref, &note, &o.Author, &at); err != nil {
			return nil, err
		}
		o.SourceRef, o.Note, o.UpdatedAt = strPtr(ref), strPtr(note), fromTS(at)
		out = append(out, o)
	}
	return out, rows.Err()
}

func loadFacts(tx *sql.Tx, carID int64) ([]api.Fact, error) {
	rows, err := tx.Query("SELECT key, value, source, source_ref, author, updated_at FROM facts WHERE car_id = ? ORDER BY key", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []api.Fact{}
	for rows.Next() {
		var f api.Fact
		var ref sql.NullString
		var at float64
		if err := rows.Scan(&f.Key, &f.Value, &f.Source, &ref, &f.Author, &at); err != nil {
			return nil, err
		}
		f.SourceRef, f.UpdatedAt = strPtr(ref), fromTS(at)
		out = append(out, f)
	}
	return out, rows.Err()
}

// loadDuplicates lists proposals; perspective (car id, 0 = none) fills other_car_id/other_title.
func loadDuplicates(tx *sql.Tx, where string, perspective int64, args ...any) ([]api.DuplicateCandidate, error) {
	rows, err := tx.Query("SELECT id, car_a, car_b, score, reasons, status, created_at FROM duplicates WHERE "+where+" ORDER BY score DESC, id", args...)
	if err != nil {
		return nil, err
	}
	out := []api.DuplicateCandidate{}
	for rows.Next() {
		var d api.DuplicateCandidate
		var reasons string
		var at float64
		if err := rows.Scan(&d.ID, &d.CarA, &d.CarB, &d.Score, &reasons, &d.Status, &at); err != nil {
			rows.Close()
			return nil, err
		}
		d.Reasons, d.CreatedAt = parseList(reasons), fromTS(at)
		out = append(out, d)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for i := range out {
		d := &out[i]
		if perspective != 0 {
			d.OtherCarID = d.CarA
			if d.CarA == perspective {
				d.OtherCarID = d.CarB
			}
			if c, err := loadCar(tx, d.OtherCarID); err == nil {
				d.OtherTitle = c.title()
			}
		}
	}
	return out, nil
}

func carDetail(tx *sql.Tx, id int64) (*api.CarDetail, error) {
	car, err := loadCar(tx, id)
	if err != nil {
		return nil, err
	}
	d := &api.CarDetail{
		CarSpecs:         specsStruct(car.Specs),
		ID:               car.ID,
		Slug:             strPtr(car.Slug),
		Title:            car.title(),
		Summary:          strPtr(car.Summary),
		Status:           car.Status,
		StatusReason:     strPtr(car.StatusReason),
		StatusChangedAt:  fromNullTS(car.StatusChangedAt),
		NeedsOwner:       car.NeedsOwner,
		NeedsOwnerReason: strPtr(car.NeedsOwnerReason),
		RedFlags:         car.RedFlags,
		OpenQuestions:    car.OpenQuestions,
		CreatedAt:        fromTS(car.CreatedAt),
		UpdatedAt:        fromTS(car.UpdatedAt),
		Version:          car.Version,
	}
	if d.Aliases, err = carAliases(tx, id); err != nil {
		return nil, err
	}
	if car.SellerID.Valid {
		if d.Seller, err = loadSeller(tx, car.SellerID.Int64); err != nil {
			return nil, err
		}
	}
	if d.Listings, err = loadListings(tx, "car_id = ?", id); err != nil {
		return nil, err
	}
	d.Price, d.PriceNote, _, _ = derivePrice(priceInfos(d.Listings))
	if d.Options, err = loadOptions(tx, id); err != nil {
		return nil, err
	}
	if d.Facts, err = loadFacts(tx, id); err != nil {
		return nil, err
	}
	for _, f := range d.Facts {
		if f.Key == "deal_rank" {
			v := f.Value
			d.DealRank = &v
		}
	}
	d.ModelFamily, _, d.ModelFamilyManual = car.family()
	d.GoodDeal, d.GoodDealNote, d.GoodDealBy, d.GoodDealAt = car.GoodDeal, strPtr(car.GoodDealNote), strPtr(car.GoodDealBy), fromNullTS(car.GoodDealAt)
	if d.Photos, err = loadPhotos(tx, id); err != nil {
		return nil, err
	}
	if d.Events, err = loadEvents(tx, id); err != nil {
		return nil, err
	}
	if d.Messages, err = loadMessages(tx, id); err != nil {
		return nil, err
	}
	if d.Notes, err = loadNotes(tx, id, true); err != nil {
		return nil, err
	}
	if d.Verdict, err = loadVerdict(tx, id); err != nil {
		return nil, err
	}
	if d.Duplicates, err = loadDuplicates(tx, "status = 'proposed' AND (car_a = ? OR car_b = ?)", id, id, id); err != nil {
		return nil, err
	}
	d.MergedFrom = []int64{}
	rows, err := tx.Query("SELECT id FROM cars WHERE merged_into = ? ORDER BY id", id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var mid int64
		if err := rows.Scan(&mid); err != nil {
			return nil, err
		}
		d.MergedFrom = append(d.MergedFrom, mid)
	}
	return d, rows.Err()
}

// GetCar handles GET /cars/{car}.
func (s *Store) GetCar(ctx context.Context, ref string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		out, err = carDetail(tx, id)
		return err
	})
	return out, err
}

// carScoped resolves ref and runs a loader for that car.
func carScoped[T any](s *Store, ctx context.Context, ref string, fn func(tx *sql.Tx, id int64) (T, error)) (T, error) {
	var out T
	err := s.tx(ctx, func(tx *sql.Tx) error {
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		out, err = fn(tx, id)
		return err
	})
	return out, err
}

// ListEvents handles GET /cars/{car}/events.
func (s *Store) ListEvents(ctx context.Context, ref string) ([]api.Event, error) {
	return carScoped(s, ctx, ref, loadEvents)
}

// ListMessages handles GET /cars/{car}/messages.
func (s *Store) ListMessages(ctx context.Context, ref string) ([]api.Message, error) {
	return carScoped(s, ctx, ref, loadMessages)
}

// ListNotes handles GET /cars/{car}/notes (newest first).
func (s *Store) ListNotes(ctx context.Context, ref string) ([]api.Note, error) {
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) ([]api.Note, error) { return loadNotes(tx, id, false) })
}

// ListPhotos handles GET /cars/{car}/photos.
func (s *Store) ListPhotos(ctx context.Context, ref string) ([]api.Photo, error) {
	return carScoped(s, ctx, ref, loadPhotos)
}
