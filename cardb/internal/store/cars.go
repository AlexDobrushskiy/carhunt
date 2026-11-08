package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

type specCol struct {
	Name string
	Kind byte // 's' string, 'i' int, 'f' float
}

var specCols = []specCol{
	{"make", 's'}, {"model", 's'}, {"variant", 's'}, {"body", 's'}, {"reg_date", 's'}, {"km", 'i'},
	{"battery_net_kwh", 'f'}, {"battery_gross_kwh", 'f'}, {"power_kw", 'f'}, {"drive", 's'}, {"seats", 'i'},
	{"colour", 's'}, {"interior", 's'}, {"interior_tone", 's'}, {"wheels_in", 'i'}, {"vin", 's'}, {"plate", 's'},
	{"country", 's'}, {"city", 's'}, {"distance_km", 'i'},
	{"fuel", 's'}, {"engine_cc", 'i'}, {"gearbox", 's'}, {"wltp_range_km", 'i'}, {"wltp_consumption", 'f'}, {"co2_g_km", 'i'},
}

func specKind(name string) (byte, bool) {
	for _, c := range specCols {
		if c.Name == name {
			return c.Kind, true
		}
	}
	return 0, false
}

var (
	reRegDate = regexp.MustCompile(`^\d{4}(-\d{2}(-\d{2})?)?$`)
	reAlias   = regexp.MustCompile(`^\S{1,100}$`)
	reDigits  = regexp.MustCompile(`^\d+$`)
	reKey     = regexp.MustCompile(`^[A-Za-z0-9_.\-]{1,64}$`)
)

// normSpec validates and canonicalizes one spec value. v is string/int/float64 by kind; nil passes through.
func normSpec(col string, v any) (any, error) {
	if v == nil {
		return nil, nil
	}
	switch x := v.(type) {
	case string:
		x = strings.TrimSpace(x)
		if x == "" {
			return nil, nil
		}
		switch col {
		case "drive":
			x = strings.ToLower(x)
			if !slices.Contains([]string{"fwd", "rwd", "awd", "unknown"}, x) {
				return nil, invalidf("drive must be fwd|rwd|awd|unknown")
			}
		case "fuel", "gearbox":
			return normEnum(col, x)
		case "interior_tone":
			x = strings.ToLower(x)
			if !slices.Contains([]string{"dark", "grey", "brown", "light", "unknown"}, x) {
				return nil, invalidf("interior_tone must be dark|grey|brown|light|unknown")
			}
		case "reg_date":
			if !reRegDate.MatchString(x) {
				return nil, invalidf("reg_date must be YYYY, YYYY-MM or YYYY-MM-DD")
			}
		case "country":
			x = strings.ToUpper(x)
			if len(x) != 2 {
				return nil, invalidf("country must be an ISO-2 code")
			}
		case "vin":
			x = alnumUpper(x)
		case "plate":
			x = strings.ToUpper(x)
		}
		return x, nil
	case int:
		if x < 0 {
			return nil, invalidf("%s must be ≥ 0", col)
		}
		return int64(x), nil
	case int64:
		if x < 0 {
			return nil, invalidf("%s must be ≥ 0", col)
		}
		return x, nil
	case float64:
		if x < 0 || math.IsNaN(x) || math.IsInf(x, 0) {
			return nil, invalidf("%s must be ≥ 0", col)
		}
		return x, nil
	}
	return nil, invalidf("bad value for %s", col)
}

// specsMap converts the non-nil fields of CarSpecs into normalized column values.
func specsMap(s api.CarSpecs) (map[string]any, error) {
	raw := map[string]any{}
	put := func(k string, v any) { raw[k] = v }
	if s.Make != nil {
		put("make", *s.Make)
	}
	if s.Model != nil {
		put("model", *s.Model)
	}
	if s.Variant != nil {
		put("variant", *s.Variant)
	}
	if s.Body != nil {
		put("body", *s.Body)
	}
	if s.RegDate != nil {
		put("reg_date", *s.RegDate)
	}
	if s.Km != nil {
		put("km", *s.Km)
	}
	for k, v := range powertrainValues(s.Powertrain) {
		put(k, v)
	}
	if s.PowerKw != nil {
		put("power_kw", *s.PowerKw)
	}
	if s.Drive != nil {
		put("drive", *s.Drive)
	}
	if s.Seats != nil {
		put("seats", *s.Seats)
	}
	if s.Colour != nil {
		put("colour", *s.Colour)
	}
	if s.Interior != nil {
		put("interior", *s.Interior)
	}
	if s.InteriorTone != nil {
		put("interior_tone", *s.InteriorTone)
	}
	if s.WheelsIn != nil {
		put("wheels_in", *s.WheelsIn)
	}
	if s.VIN != nil {
		put("vin", *s.VIN)
	}
	if s.Plate != nil {
		put("plate", *s.Plate)
	}
	if s.Country != nil {
		put("country", *s.Country)
	}
	if s.City != nil {
		put("city", *s.City)
	}
	if s.DistanceKm != nil {
		put("distance_km", *s.DistanceKm)
	}
	out := map[string]any{}
	for k, v := range raw {
		nv, err := normSpec(k, v)
		if err != nil {
			return nil, err
		}
		if nv != nil {
			out[k] = nv
		}
	}
	return out, nil
}

func specsStruct(m map[string]any) api.CarSpecs {
	str := func(k string) *string {
		if v, ok := m[k].(string); ok {
			return &v
		}
		return nil
	}
	in := func(k string) *int {
		if v, ok := m[k].(int64); ok {
			i := int(v)
			return &i
		}
		return nil
	}
	fl := func(k string) *float64 {
		if v, ok := m[k].(float64); ok {
			return &v
		}
		return nil
	}
	s := api.CarSpecs{
		Make: str("make"), Model: str("model"), Variant: str("variant"), Body: str("body"),
		RegDate: str("reg_date"), Km: in("km"), PowerKw: fl("power_kw"), Drive: str("drive"),
		Seats: in("seats"), Colour: str("colour"), Interior: str("interior"), InteriorTone: str("interior_tone"),
		WheelsIn: in("wheels_in"), VIN: str("vin"), Plate: str("plate"), Country: str("country"),
		City: str("city"), DistanceKm: in("distance_km"),
	}
	if pt := (&api.Powertrain{Fuel: str("fuel"), BatteryNetKwh: fl("battery_net_kwh"), BatteryGrossKwh: fl("battery_gross_kwh"),
		EngineCc: in("engine_cc"), Gearbox: str("gearbox"), WltpRangeKm: in("wltp_range_km"),
		WltpConsumption: fl("wltp_consumption"), Co2GKm: in("co2_g_km")}); !pt.Empty() {
		s.Powertrain = pt
	}
	s.Year = yearOf(s.RegDate)
	s.Market = marketOf(s.Country)
	return s
}

func yearOf(regDate *string) *int {
	if regDate == nil || len(*regDate) < 4 {
		return nil
	}
	y, err := strconv.Atoi((*regDate)[:4])
	if err != nil {
		return nil
	}
	return &y
}

func marketOf(country *string) *string {
	if country == nil {
		return nil
	}
	m := "abroad"
	if *country == "PT" {
		m = "PT"
	}
	return &m
}

// --- car rows -----------------------------------------------------------

type carRow struct {
	ID               int64
	Slug             sql.NullString
	Specs            map[string]any
	SellerID         sql.NullInt64
	Summary          sql.NullString
	Status           string
	StatusReason     sql.NullString
	StatusChangedAt  sql.NullFloat64
	NeedsOwner       bool
	NeedsOwnerReason sql.NullString
	RedFlags         []string
	OpenQuestions    []string
	MergedInto       sql.NullInt64
	CreatedAt        float64
	UpdatedAt        float64
	FamilyOverride   sql.NullString
	GoodDeal         bool
	GoodDealNote     sql.NullString
	GoodDealBy       sql.NullString
	GoodDealAt       sql.NullFloat64
	Version          int64
}

// family is the effective model family: the manual override, else derived from make/model/variant.
func (c *carRow) family() (family, familyMake *string, manual bool) {
	if c.FamilyOverride.Valid {
		if f, mk, ok := CanonicalFamily(c.FamilyOverride.String); ok {
			return &f, &mk, true
		}
	}
	if f, mk, ok := Family(c.str("make"), c.str("model"), c.str("variant")); ok {
		return &f, &mk, false
	}
	return nil, nil, false
}

func (c *carRow) title() string {
	var parts []string
	for _, k := range []string{"make", "model", "variant"} {
		if v, ok := c.Specs[k].(string); ok && v != "" {
			parts = append(parts, v)
		}
	}
	if len(parts) == 0 {
		return fmt.Sprintf("Car #%d", c.ID)
	}
	return strings.Join(parts, " ")
}

func (c *carRow) str(k string) string {
	v, _ := c.Specs[k].(string)
	return v
}

var carSelect = func() string {
	cols := []string{"id", "slug"}
	for _, c := range specCols {
		cols = append(cols, c.Name)
	}
	cols = append(cols, "seller_id", "summary", "status", "status_reason", "status_changed_at", "needs_owner",
		"needs_owner_reason", "red_flags", "open_questions", "merged_into", "created_at", "updated_at",
		"model_family_override", "good_deal", "good_deal_note", "good_deal_by", "good_deal_at", "version")
	return "SELECT " + strings.Join(cols, ", ") + " FROM cars"
}()

type scanner interface{ Scan(dest ...any) error }

func scanCar(sc scanner) (*carRow, error) {
	c := &carRow{Specs: map[string]any{}}
	dest := []any{&c.ID, &c.Slug}
	vals := make([]any, len(specCols))
	for i, col := range specCols {
		switch col.Kind {
		case 's':
			vals[i] = new(sql.NullString)
		case 'i':
			vals[i] = new(sql.NullInt64)
		case 'f':
			vals[i] = new(sql.NullFloat64)
		}
		dest = append(dest, vals[i])
	}
	var redFlags, openQ string
	var needs, goodDeal int
	dest = append(dest, &c.SellerID, &c.Summary, &c.Status, &c.StatusReason, &c.StatusChangedAt, &needs,
		&c.NeedsOwnerReason, &redFlags, &openQ, &c.MergedInto, &c.CreatedAt, &c.UpdatedAt,
		&c.FamilyOverride, &goodDeal, &c.GoodDealNote, &c.GoodDealBy, &c.GoodDealAt, &c.Version)
	if err := sc.Scan(dest...); err != nil {
		return nil, err
	}
	for i, col := range specCols {
		switch v := vals[i].(type) {
		case *sql.NullString:
			if v.Valid {
				c.Specs[col.Name] = v.String
			}
		case *sql.NullInt64:
			if v.Valid {
				c.Specs[col.Name] = v.Int64
			}
		case *sql.NullFloat64:
			if v.Valid {
				c.Specs[col.Name] = v.Float64
			}
		}
	}
	c.NeedsOwner = needs != 0
	c.GoodDeal = goodDeal != 0
	c.RedFlags = parseList(redFlags)
	c.OpenQuestions = parseList(openQ)
	return c, nil
}

func loadCar(tx *sql.Tx, id int64) (*carRow, error) {
	c, err := scanCar(tx.QueryRow(carSelect+" WHERE id = ?", id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, notFoundf("car %d not found", id)
	}
	return c, err
}

func loadLiveCars(tx *sql.Tx) ([]*carRow, error) {
	rows, err := tx.Query(carSelect + " WHERE merged_into IS NULL ORDER BY id")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []*carRow
	for rows.Next() {
		c, err := scanCar(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// resolveCar maps an id or alias to the live car id (following merges).
func resolveCar(tx *sql.Tx, ref string) (int64, error) {
	ref = strings.TrimSpace(ref)
	if ref == "" {
		return 0, invalidf("car is required")
	}
	var id int64
	if reDigits.MatchString(ref) {
		n, err := strconv.ParseInt(ref, 10, 64)
		if err != nil {
			return 0, notFoundf("car %q not found", ref)
		}
		id = n
	} else {
		err := tx.QueryRow("SELECT car_id FROM car_aliases WHERE alias = ?", ref).Scan(&id)
		if errors.Is(err, sql.ErrNoRows) {
			return 0, notFoundf("car %q not found", ref)
		} else if err != nil {
			return 0, err
		}
	}
	for range 64 {
		var merged sql.NullInt64
		err := tx.QueryRow("SELECT merged_into FROM cars WHERE id = ?", id).Scan(&merged)
		if errors.Is(err, sql.ErrNoRows) {
			return 0, notFoundf("car %q not found", ref)
		} else if err != nil {
			return 0, err
		}
		if !merged.Valid {
			return id, nil
		}
		id = merged.Int64
	}
	return 0, fmt.Errorf("merge chain too long for car %q", ref)
}

// ResolveCar is resolveCar in its own transaction.
func (s *Store) ResolveCar(ctx context.Context, ref string) (int64, error) {
	var id int64
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		id, err = resolveCar(tx, ref)
		return err
	})
	return id, err
}

// --- events ---------------------------------------------------------------

type ev struct {
	CarID     int64
	ListingID *int64
	Type      string
	At        float64
	Author    string
	Summary   string
	Data      any
	DedupeKey string
}

func addEvent(tx *sql.Tx, e ev) (int64, error) {
	var data any
	if e.Data != nil {
		if raw, ok := e.Data.(json.RawMessage); ok {
			if len(raw) > 0 && string(raw) != "null" {
				data = string(raw)
			}
		} else {
			data = mustJSON(e.Data)
		}
	}
	res, err := tx.Exec(`INSERT INTO events (car_id, listing_id, type, at, author, summary, data, dedupe_key)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		e.CarID, nullInt64(e.ListingID), e.Type, e.At, e.Author, e.Summary, data, nullStr(e.DedupeKey))
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

// --- aliases --------------------------------------------------------------

func validateAlias(a string) (string, error) {
	a = strings.TrimSpace(a)
	if !reAlias.MatchString(a) {
		return "", invalidf("alias must be 1-100 non-space characters")
	}
	if reDigits.MatchString(a) {
		return "", invalidf("alias %q must not be all digits (ids are numeric)", a)
	}
	return a, nil
}

// addAlias inserts alias → car; 409 if another car holds it.
func addAlias(tx *sql.Tx, carID int64, alias string) error {
	alias, err := validateAlias(alias)
	if err != nil {
		return err
	}
	var owner int64
	err = tx.QueryRow("SELECT car_id FROM car_aliases WHERE alias = ?", alias).Scan(&owner)
	switch {
	case errors.Is(err, sql.ErrNoRows):
		_, err = tx.Exec("INSERT INTO car_aliases (alias, car_id) VALUES (?, ?)", alias, carID)
		return err
	case err != nil:
		return err
	}
	if owner == carID {
		return nil
	}
	// A tombstone's alias resolves to the live car; treat that as the same car.
	if live, err := resolveCar(tx, strconv.FormatInt(owner, 10)); err == nil && live == carID {
		return nil
	}
	return conflictf("alias %q already belongs to car %d", alias, owner)
}

func setSlug(tx *sql.Tx, carID int64, slug string) error {
	slug, err := validateAlias(slug)
	if err != nil {
		return err
	}
	if err := addAlias(tx, carID, slug); err != nil {
		return err
	}
	var other int64
	err = tx.QueryRow("SELECT id FROM cars WHERE slug = ? AND id != ?", slug, carID).Scan(&other)
	if err == nil {
		return conflictf("slug %q already belongs to car %d", slug, other)
	}
	_, err = tx.Exec("UPDATE cars SET slug = ? WHERE id = ?", slug, carID)
	return err
}

// AddAlias adds an alias to a car.
func (s *Store) AddAlias(ctx context.Context, ref, alias string) (int64, error) {
	var id int64
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		if id, err = resolveCar(tx, ref); err != nil {
			return err
		}
		return addAlias(tx, id, alias)
	})
	return id, err
}

func carAliases(tx *sql.Tx, carID int64) ([]string, error) {
	rows, err := tx.Query("SELECT alias FROM car_aliases WHERE car_id = ? ORDER BY alias COLLATE NOCASE", carID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var a string
		if err := rows.Scan(&a); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// --- create ----------------------------------------------------------------

func validStatus(s string) error {
	if !slices.Contains(api.Statuses, s) {
		return invalidf("status must be one of %s", strings.Join(api.Statuses, "|"))
	}
	return nil
}

func statusRank(s string) int { return slices.Index(api.Statuses, s) }

type newCar struct {
	Specs            map[string]any
	Slug             string
	Aliases          []string
	Summary          string
	Status           string
	StatusReason     string
	NeedsOwner       bool
	NeedsOwnerReason string
	SellerID         int64
	RedFlags         []string
	OpenQuestions    []string
}

func insertCar(tx *sql.Tx, n newCar, at float64) (int64, error) {
	if n.Status == "" {
		n.Status = "new"
	}
	if err := validStatus(n.Status); err != nil {
		return 0, err
	}
	cols := []string{"seller_id", "summary", "status", "status_reason", "status_changed_at", "needs_owner",
		"needs_owner_reason", "red_flags", "open_questions", "created_at", "updated_at"}
	var sellerID any
	if n.SellerID != 0 {
		sellerID = n.SellerID
	}
	args := []any{sellerID, nullStr(n.Summary), n.Status, nullStr(n.StatusReason), at, boolInt(n.NeedsOwner),
		nullStr(n.NeedsOwnerReason), jsonList(n.RedFlags), jsonList(n.OpenQuestions), at, at}
	for _, c := range specCols {
		if v, ok := n.Specs[c.Name]; ok && v != nil {
			cols = append(cols, c.Name)
			args = append(args, v)
		}
	}
	q := "INSERT INTO cars (" + strings.Join(cols, ", ") + ") VALUES (" + strings.TrimSuffix(strings.Repeat("?, ", len(cols)), ", ") + ")"
	res, err := tx.Exec(q, args...)
	if err != nil {
		return 0, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return 0, err
	}
	if n.Slug != "" {
		if err := setSlug(tx, id, n.Slug); err != nil {
			return 0, err
		}
	}
	for _, a := range n.Aliases {
		if err := addAlias(tx, id, a); err != nil {
			return 0, err
		}
	}
	return id, nil
}

// CreateCar handles POST /cars.
func (s *Store) CreateCar(ctx context.Context, in api.CarInput, author string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		specs, err := specsMap(in.CarSpecs)
		if err != nil {
			return err
		}
		var sellerID int64
		if in.Seller != nil {
			if sellerID, _, err = ensureSeller(tx, 0, in.Seller, true, false, now); err != nil {
				return err
			}
		}
		n := newCar{Specs: specs, Aliases: in.Aliases, SellerID: sellerID, RedFlags: in.RedFlags, OpenQuestions: in.OpenQuestions}
		if in.Slug != nil {
			n.Slug = *in.Slug
		}
		if in.Summary != nil {
			n.Summary = *in.Summary
		}
		if in.Status != nil {
			n.Status = *in.Status
		}
		if in.StatusReason != nil {
			n.StatusReason = *in.StatusReason
		}
		if in.NeedsOwner != nil {
			n.NeedsOwner = *in.NeedsOwner
		}
		if in.NeedsOwnerReason != nil {
			n.NeedsOwnerReason = *in.NeedsOwnerReason
		}
		id, err := insertCar(tx, n, now)
		if err != nil {
			return err
		}
		car, err := loadCar(tx, id)
		if err != nil {
			return err
		}
		if _, err := addEvent(tx, ev{CarID: id, Type: "created", At: now, Author: author, Summary: "created " + car.title()}); err != nil {
			return err
		}
		// Explicitly created cars never auto-merge; every match (certain included) becomes a proposal.
		if _, err := proposeDuplicates(tx, id, true, author, now); err != nil {
			return err
		}
		out, err = carDetail(tx, id)
		return err
	})
	return out, err
}

// --- patch -----------------------------------------------------------------

var patchIgnored = map[string]bool{
	"author": true, "at": true, "id": true, "title": true, "year": true, "market": true, "created_at": true, "updated_at": true,
	"status_changed_at": true, "price": true, "price_note": true, "listings": true, "options": true, "facts": true,
	"photos": true, "events": true, "messages": true, "notes": true, "verdict": true, "duplicates": true, "merged_from": true,
	"model_family_manual": true, "good_deal_by": true, "good_deal_at": true, "deal_rank": true,
}

func decodeSpecRaw(col string, kind byte, raw json.RawMessage) (any, error) {
	if string(raw) == "null" {
		return nil, nil
	}
	switch kind {
	case 's':
		var v string
		if err := json.Unmarshal(raw, &v); err != nil {
			return nil, invalidf("%s must be a string or null", col)
		}
		return normSpec(col, v)
	case 'i':
		var f float64
		if err := json.Unmarshal(raw, &f); err != nil || f != math.Trunc(f) {
			return nil, invalidf("%s must be an integer or null", col)
		}
		return normSpec(col, int64(f))
	default:
		var f float64
		if err := json.Unmarshal(raw, &f); err != nil {
			return nil, invalidf("%s must be a number or null", col)
		}
		return normSpec(col, f)
	}
}

func decodeOptString(key string, raw json.RawMessage) (*string, error) {
	if string(raw) == "null" {
		return nil, nil
	}
	var v string
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, invalidf("%s must be a string or null", key)
	}
	v = strings.TrimSpace(v)
	if v == "" {
		return nil, nil
	}
	return &v, nil
}

func decodeStrList(key string, raw json.RawMessage) ([]string, error) {
	if string(raw) == "null" {
		return []string{}, nil
	}
	var v []string
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, invalidf("%s must be an array of strings or null", key)
	}
	return v, nil
}

type specChange struct {
	From any `json:"from"`
	To   any `json:"to"`
}

// writeSpecs updates spec columns; returns the changed fields.
func writeSpecs(tx *sql.Tx, car *carRow, vals map[string]any, overwrite bool, now float64) (map[string]specChange, error) {
	changes := map[string]specChange{}
	var sets []string
	var args []any
	for _, c := range specCols {
		nv, ok := vals[c.Name]
		if !ok {
			continue
		}
		old, had := car.Specs[c.Name]
		if had && !overwrite {
			continue
		}
		if !overwrite && nv == nil {
			continue
		}
		if had && nv != nil && old == nv {
			continue
		}
		if !had && nv == nil {
			continue
		}
		changes[c.Name] = specChange{From: old, To: nv}
		sets = append(sets, c.Name+" = ?")
		args = append(args, nv)
		if nv == nil {
			delete(car.Specs, c.Name)
		} else {
			car.Specs[c.Name] = nv
		}
	}
	if len(sets) == 0 {
		return changes, nil
	}
	args = append(args, now, car.ID)
	_, err := tx.Exec("UPDATE cars SET "+strings.Join(sets, ", ")+", updated_at = MAX(updated_at, ?) WHERE id = ?", args...)
	return changes, err
}

func specChangeEvent(tx *sql.Tx, carID int64, changes map[string]specChange, author string, at float64, listingID *int64) error {
	if len(changes) == 0 {
		return nil
	}
	keys := make([]string, 0, len(changes))
	for k := range changes {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%s %s → %s", k, fmtVal(changes[k].From), fmtVal(changes[k].To)))
	}
	_, err := addEvent(tx, ev{CarID: carID, ListingID: listingID, Type: "spec_change", At: at, Author: author,
		Summary: "spec: " + strings.Join(parts, "; "), Data: map[string]any{"changes": changes}})
	return err
}

func setStatus(tx *sql.Tx, car *carRow, status, reason, author string, at float64) (bool, error) {
	if err := validStatus(status); err != nil {
		return false, err
	}
	if car.Status == status {
		if reason != "" && reason != car.StatusReason.String {
			_, err := tx.Exec("UPDATE cars SET status_reason = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", reason, at, car.ID)
			return false, err
		}
		return false, nil
	}
	from := car.Status
	if _, err := tx.Exec("UPDATE cars SET status = ?, status_reason = ?, status_changed_at = ?, updated_at = MAX(updated_at, ?) WHERE id = ?",
		status, nullStr(reason), at, at, car.ID); err != nil {
		return false, err
	}
	car.Status = status
	summary := fmt.Sprintf("status %s → %s", from, status)
	if reason != "" {
		summary += " (" + reason + ")"
	}
	_, err := addEvent(tx, ev{CarID: car.ID, Type: "status_change", At: at, Author: author, Summary: summary,
		Data: map[string]any{"from": from, "to": status, "reason": nullStr(reason)}})
	return true, err
}

// SetStatus handles POST /cars/{car}/status.
func (s *Store) SetStatus(ctx context.Context, ref string, in api.StatusInput, author string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		car, err := loadCar(tx, id)
		if err != nil {
			return err
		}
		if err := checkVersion(tx, car, in.Version); err != nil {
			return err
		}
		if _, err := setStatus(tx, car, in.Status, strings.TrimSpace(in.Reason), author, atOr(in.At, s.nowTS())); err != nil {
			return err
		}
		out, err = carDetail(tx, id)
		return err
	})
	return out, err
}

// PatchCar handles PATCH /cars/{car}; explicit nulls clear fields.
func (s *Store) PatchCar(ctx context.Context, ref string, patch map[string]json.RawMessage, author string) (*api.CarDetail, error) {
	var out *api.CarDetail
	now := s.nowTS()
	if raw, ok := patch["at"]; ok && string(raw) != "null" {
		var t time.Time
		if err := json.Unmarshal(raw, &t); err != nil {
			return nil, invalidf("at must be an RFC 3339 timestamp")
		}
		now = ts(t)
	}
	wantVersion, err := decodeVersion(patch["version"])
	if err != nil {
		return nil, err
	}
	err = s.tx(ctx, func(tx *sql.Tx) error {
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		car, err := loadCar(tx, id)
		if err != nil {
			return err
		}
		if err := checkVersion(tx, car, wantVersion); err != nil {
			return err
		}
		specVals := map[string]any{}
		var sets []string
		var args []any
		identityChanged := false
		var status *string
		var reason string
		reasonSent := false
		var familyChange *specChange

		keys := make([]string, 0, len(patch))
		for k := range patch {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			raw := patch[k]
			if kind, ok := specKind(k); ok && !powertrainOnly[k] {
				v, err := decodeSpecRaw(k, kind, raw)
				if err != nil {
					return err
				}
				specVals[k] = v
				continue
			}
			switch k {
			case "summary", "needs_owner_reason":
				v, err := decodeOptString(k, raw)
				if err != nil {
					return err
				}
				sets = append(sets, k+" = ?")
				if v == nil {
					args = append(args, nil)
				} else {
					args = append(args, *v)
				}
			case "needs_owner":
				var b bool
				if string(raw) != "null" {
					if err := json.Unmarshal(raw, &b); err != nil {
						return invalidf("needs_owner must be a boolean")
					}
				}
				sets = append(sets, "needs_owner = ?")
				args = append(args, boolInt(b))
			case "red_flags", "open_questions":
				v, err := decodeStrList(k, raw)
				if err != nil {
					return err
				}
				sets = append(sets, k+" = ?")
				args = append(args, jsonList(v))
			case "status":
				v, err := decodeOptString(k, raw)
				if err != nil || v == nil {
					return invalidf("status must be one of %s", strings.Join(api.Statuses, "|"))
				}
				status = v
			case "status_reason":
				v, err := decodeOptString(k, raw)
				if err != nil {
					return err
				}
				reasonSent = true
				if v != nil {
					reason = *v
				}
			case "slug":
				v, err := decodeOptString(k, raw)
				if err != nil {
					return err
				}
				if v == nil {
					if _, err := tx.Exec("UPDATE cars SET slug = NULL WHERE id = ?", id); err != nil {
						return err
					}
				} else if err := setSlug(tx, id, *v); err != nil {
					return err
				}
			case "aliases":
				v, err := decodeStrList(k, raw)
				if err != nil {
					return err
				}
				for _, a := range v {
					if err := addAlias(tx, id, a); err != nil {
						return err
					}
				}
			case "seller":
				if string(raw) == "null" {
					sets = append(sets, "seller_id = ?")
					args = append(args, nil)
					continue
				}
				var in api.SellerInput
				if err := json.Unmarshal(raw, &in); err != nil {
					return invalidf("seller must be an object or null")
				}
				cur := car.SellerID.Int64
				sid, contactsChanged, err := ensureSeller(tx, cur, &in, true, true, now)
				if err != nil {
					return err
				}
				if contactsChanged {
					identityChanged = true
				}
				if sid != cur {
					sets = append(sets, "seller_id = ?")
					args = append(args, nullInt64(&sid))
					identityChanged = true
				}
			case "model_family":
				v, err := decodeOptString(k, raw)
				if err != nil {
					return err
				}
				var next any
				if v != nil {
					name, _, ok := CanonicalFamily(*v)
					if !ok {
						return invalidf("unknown model family %q; GET /model-families", *v)
					}
					next = name
				}
				var prev any
				if car.FamilyOverride.Valid {
					prev = car.FamilyOverride.String
				}
				if prev != next {
					sets = append(sets, "model_family_override = ?")
					args = append(args, next)
					auto := func(x any) any {
						if x == nil {
							return "auto"
						}
						return x
					}
					familyChange = &specChange{From: auto(prev), To: auto(next)}
				}
			case "powertrain":
				pt, err := decodePowertrainPatch(raw)
				if err != nil {
					return err
				}
				for c, v := range pt {
					specVals[c] = v
				}
			case "version", "red_flags_add", "red_flags_remove", "open_questions_add", "open_questions_remove":
				continue // version: checked above; list ops: applied after the loop
			case "good_deal", "good_deal_note":
				return invalidf("%s is set with PUT /cars/{car}/good-deal", k)
			case "seller_id":
				if string(raw) == "null" {
					sets = append(sets, "seller_id = ?")
					args = append(args, nil)
					continue
				}
				var sid int64
				if err := json.Unmarshal(raw, &sid); err != nil {
					return invalidf("seller_id must be an integer or null")
				}
				var one int
				if err := tx.QueryRow("SELECT 1 FROM sellers WHERE id = ?", sid).Scan(&one); err != nil {
					return invalidf("seller %d not found", sid)
				}
				sets = append(sets, "seller_id = ?")
				args = append(args, sid)
				identityChanged = true
			default:
				if patchIgnored[k] {
					continue
				}
				return invalidf("unknown field %q", k)
			}
		}

		opSets, opArgs, err := listOpSets(car, patch)
		if err != nil {
			return err
		}
		sets, args = append(sets, opSets...), append(args, opArgs...)
		if len(sets) > 0 || len(patch) > 0 {
			args = append(args, now, id)
			if _, err := tx.Exec("UPDATE cars SET "+strings.Join(append(sets, "updated_at = ?"), ", ")+" WHERE id = ?", args...); err != nil {
				return err
			}
		}
		changes, err := writeSpecs(tx, car, specVals, true, now)
		if err != nil {
			return err
		}
		if familyChange != nil {
			changes["model_family"] = *familyChange
		}
		if err := specChangeEvent(tx, id, changes, author, now, nil); err != nil {
			return err
		}
		if _, ok := changes["vin"]; ok {
			identityChanged = true
		}
		if _, ok := changes["plate"]; ok {
			identityChanged = true
		}
		if status != nil {
			if _, err := setStatus(tx, car, *status, reason, author, now); err != nil {
				return err
			}
		} else if reasonSent {
			if _, err := tx.Exec("UPDATE cars SET status_reason = ?, updated_at = MAX(updated_at, ?) WHERE id = ?", nullStr(reason), now, id); err != nil {
				return err
			}
		}
		live := id
		if identityChanged {
			if live, err = rededupe(tx, id, author, now); err != nil {
				return err
			}
		}
		out, err = carDetail(tx, live)
		return err
	})
	return out, err
}

// --- formatting --------------------------------------------------------------

func fmtThousands(n int64) string {
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.FormatInt(n, 10)
	var b strings.Builder
	for i, r := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(' ')
		}
		b.WriteRune(r)
	}
	if neg {
		return "-" + b.String()
	}
	return b.String()
}

func fmtVal(v any) string {
	switch x := v.(type) {
	case nil:
		return "—"
	case int64:
		return fmtThousands(x)
	case int:
		return fmtThousands(int64(x))
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	case string:
		return x
	}
	return fmt.Sprint(v)
}
