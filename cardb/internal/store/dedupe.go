package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/imaging"
)

const phashMaxDistance = 6

// commonPhotoCars: a picture seen on this many distinct cars is a dealer banner / stock / logo image,
// not evidence about one car.
const commonPhotoCars = 3

// probe is the identity-relevant view of a car (existing or about to be created).
type probe struct {
	CarID      int64
	Make       string
	Model      string
	Year       int
	Km         int64
	HasKm      bool
	RegDate    string
	Colour     string
	City       string
	VIN        string
	Plate      string
	Phones     []string
	SellerType string
	Status     string
	PHashes    []uint64
}

func probeFromSpecs(specs map[string]any) *probe {
	str := func(k string) string {
		v, _ := specs[k].(string)
		return strings.ToLower(strings.TrimSpace(v))
	}
	p := &probe{
		Make: str("make"), Model: str("model"), RegDate: str("reg_date"), Colour: str("colour"), City: str("city"),
	}
	if v, ok := specs["vin"].(string); ok {
		p.VIN = NormalizeVIN(v)
	}
	if v, ok := specs["plate"].(string); ok {
		p.Plate = NormalizePlate(v)
	}
	if km, ok := specs["km"].(int64); ok {
		p.Km, p.HasKm = km, true
	}
	rd := str("reg_date")
	if y := yearOf(&rd); y != nil {
		p.Year = *y
	}
	return p
}

// loadProbes builds probes for all live cars.
func loadProbes(tx *sql.Tx) (map[int64]*probe, map[int64]string, error) {
	cars, err := loadLiveCars(tx)
	if err != nil {
		return nil, nil, err
	}
	sellerType := map[int64]string{}
	phones := map[int64][]string{}
	rows, err := tx.Query("SELECT id, type FROM sellers")
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var id int64
		var t string
		if err := rows.Scan(&id, &t); err != nil {
			rows.Close()
			return nil, nil, err
		}
		sellerType[id] = t
	}
	rows.Close()
	rows, err = tx.Query("SELECT seller_id, value FROM seller_contacts WHERE kind IN ('phone', 'whatsapp') AND shared = 0")
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var id int64
		var v string
		if err := rows.Scan(&id, &v); err != nil {
			rows.Close()
			return nil, nil, err
		}
		phones[id] = append(phones[id], v)
	}
	rows.Close()
	hashes := map[int64][]uint64{}
	rows, err = tx.Query("SELECT car_id, phash FROM photos")
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var id, h int64
		if err := rows.Scan(&id, &h); err != nil {
			rows.Close()
			return nil, nil, err
		}
		hashes[id] = append(hashes[id], uint64(h))
	}
	rows.Close()

	out := map[int64]*probe{}
	titles := map[int64]string{}
	for _, c := range cars {
		p := probeFromSpecs(c.Specs)
		p.CarID = c.ID
		p.SellerType = "unknown"
		if c.SellerID.Valid {
			p.SellerType = sellerType[c.SellerID.Int64]
			p.Phones = phones[c.SellerID.Int64]
		}
		p.PHashes = hashes[c.ID]
		p.Status = c.Status
		out[c.ID] = p
		titles[c.ID] = c.title()
	}
	return out, titles, nil
}

// photoIndex answers "on how many distinct live cars does this picture appear?".
type photoIndex struct {
	cars   []int64
	hashes []uint64
	memo   map[uint64]map[int64]bool
}

func newPhotoIndex(all map[int64]*probe) *photoIndex {
	ix := &photoIndex{memo: map[uint64]map[int64]bool{}}
	for id, p := range all {
		for _, h := range p.PHashes {
			ix.cars = append(ix.cars, id)
			ix.hashes = append(ix.hashes, h)
		}
	}
	return ix
}

func (ix *photoIndex) carsNear(h uint64) map[int64]bool {
	if s, ok := ix.memo[h]; ok {
		return s
	}
	s := map[int64]bool{}
	for i, x := range ix.hashes {
		if imaging.Hamming(h, x) <= phashMaxDistance {
			s[ix.cars[i]] = true
		}
	}
	ix.memo[h] = s
	return s
}

// photoEvidence counts p's pictures that also appear on c: distinctive ones, and common ones (also on
// other cars: banners, stock images) that say nothing about identity.
func photoEvidence(p, c *probe, ix *photoIndex) (distinct, common int) {
	for _, x := range p.PHashes {
		for _, y := range c.PHashes {
			if imaging.Hamming(x, y) > phashMaxDistance {
				continue
			}
			on := map[int64]bool{c.CarID: true}
			if p.CarID != 0 {
				on[p.CarID] = true
			}
			n := len(on)
			if p.CarID == 0 {
				n++ // the new listing's car
			}
			for _, h := range []uint64{x, y} {
				for id := range ix.carsNear(h) {
					if !on[id] {
						on[id] = true
						n++
					}
				}
			}
			if n >= commonPhotoCars {
				common++
			} else {
				distinct++
			}
			break
		}
	}
	return distinct, common
}

type match struct {
	CarID   int64
	Certain string // vin|plate|photos|phone_model, "" = likely only
	Score   float64
	Reasons []string
}

// modelFamily is the model's first word ("id.5 pro performance" → "id.5", "q4 sportback e-tron" → "q4").
func modelFamily(model string) string {
	if f := strings.Fields(model); len(f) > 0 {
		return f[0]
	}
	return ""
}

// identityConflict: both cars say what they are and it differs (make or model family). Only a VIN or plate overrides it.
func identityConflict(p, c *probe) string {
	if p.Make != "" && c.Make != "" && p.Make != c.Make {
		return "make " + p.Make + " vs " + c.Make
	}
	if fp, fc := modelFamily(p.Model), modelFamily(c.Model); fp != "" && fc != "" && fp != fc {
		return "model " + p.Model + " vs " + c.Model
	}
	return ""
}

// specConflicts: known specs that argue against the same car. They block automatic links, not proposals.
func specConflicts(p, c *probe) []string {
	var out []string
	if p.Year != 0 && c.Year != 0 && p.Year != c.Year {
		out = append(out, fmt.Sprintf("year %d vs %d", p.Year, c.Year))
	}
	if p.HasKm && c.HasKm {
		diff := math.Abs(float64(p.Km - c.Km))
		if diff > math.Max(5000, 0.15*math.Max(float64(p.Km), float64(c.Km))) {
			out = append(out, fmt.Sprintf("km %s vs %s", fmtThousands(p.Km), fmtThousands(c.Km)))
		}
	}
	if p.Plate != "" && c.Plate != "" && p.Plate != c.Plate {
		out = append(out, "plate "+p.Plate+" vs "+c.Plate)
	}
	if len(p.Phones) > 0 && len(c.Phones) > 0 {
		shared := false
		for _, a := range p.Phones {
			shared = shared || slices.Contains(c.Phones, a)
		}
		if !shared {
			out = append(out, "different seller phones")
		}
	}
	return out
}

// compare scores p (a new listing's car when p.CarID == 0, else an existing car) against car c.
// Photos alone link a new listing only when they are distinctive, cover most of the smaller photo set,
// the make and model agree, no known spec contradicts and c is not closed/dropped/bought.
// Two existing cars are never merged on photos: that only becomes a proposal.
func compare(p, c *probe, ix *photoIndex) match {
	m := match{CarID: c.CarID}
	if p.VIN != "" && c.VIN != "" && p.VIN != c.VIN {
		return m // different VINs: never the same car
	}
	sameVIN := p.VIN != "" && p.VIN == c.VIN
	samePlate := p.Plate != "" && p.Plate == c.Plate
	if !sameVIN && !samePlate && identityConflict(p, c) != "" {
		return m // an iX1 is not an ID.5, whatever the photos say
	}
	sameModel := p.Model != "" && p.Model == c.Model && (p.Make == "" || c.Make == "" || p.Make == c.Make)
	sameFamily := p.Make != "" && p.Make == c.Make && modelFamily(p.Model) != "" && modelFamily(p.Model) == modelFamily(c.Model)
	var sharedPhone string
	for _, a := range p.Phones {
		if slices.Contains(c.Phones, a) {
			sharedPhone = a
			break
		}
	}
	photos, _ := photoEvidence(p, c, ix)
	conflicts := specConflicts(p, c)
	isTrade := func(t string) bool { return t == "dealer" || t == "reseller" }
	private := (p.SellerType == "private" || c.SellerType == "private") && !isTrade(p.SellerType) && !isTrade(c.SellerType)
	strongPhotos := photos >= 2 && 2*photos >= min(len(p.PHashes), len(c.PHashes))
	photoLink := p.CarID == 0 && strongPhotos && sameFamily && len(conflicts) == 0 && !slices.Contains(closedStatuses, c.Status)

	switch {
	case sameVIN:
		m.Certain = "vin"
		m.Reasons = append(m.Reasons, "same VIN "+p.VIN)
	case samePlate:
		m.Certain = "plate"
		m.Reasons = append(m.Reasons, "same plate "+p.Plate)
	case photoLink:
		m.Certain = "photos"
		m.Reasons = append(m.Reasons, fmt.Sprintf("%d matching photos", photos))
	case sharedPhone != "" && sameModel && private:
		m.Certain = "phone_model"
		m.Reasons = append(m.Reasons, "same private-seller phone "+sharedPhone+" and model")
	}

	miss := 1.0
	add := func(w float64, reasons ...string) {
		miss *= 1 - w
		m.Reasons = append(m.Reasons, reasons...)
	}
	switch {
	case photos == 1:
		add(0.5, "1 matching photo")
	case photos >= 2 && m.Certain != "photos":
		w := 0.9
		if !strongPhotos || len(conflicts) > 0 {
			w = 0.6
		}
		add(w, fmt.Sprintf("%d matching photos", photos))
	}
	if sharedPhone != "" && sameModel && m.Certain != "phone_model" {
		add(0.45, "same seller phone "+sharedPhone)
	}
	if sameModel && p.Year != 0 && p.Year == c.Year && p.HasKm && c.HasKm {
		diff := math.Abs(float64(p.Km - c.Km))
		near := diff <= 3000 || diff <= 0.05*math.Max(float64(p.Km), float64(c.Km))
		if near && ((p.City != "" && p.City == c.City) || (p.Colour != "" && p.Colour == c.Colour)) {
			r := []string{fmt.Sprintf("same model and year %d", p.Year), fmt.Sprintf("km %s vs %s", fmtThousands(p.Km), fmtThousands(c.Km))}
			if p.City != "" && p.City == c.City {
				r = append(r, "same city "+p.City)
			}
			if p.Colour != "" && p.Colour == c.Colour {
				r = append(r, "same colour "+p.Colour)
			}
			add(0.45, r...)
		}
	}
	if sameModel && len(p.RegDate) >= 7 && p.RegDate == c.RegDate && p.Colour != "" && p.Colour == c.Colour {
		add(0.45, fmt.Sprintf("same reg date %s and colour %s", p.RegDate, p.Colour))
	}
	m.Score = math.Round((1-miss)*100) / 100
	if m.Certain != "" {
		m.Score = 1
	} else if m.Score > 0 && len(conflicts) > 0 {
		m.Reasons = append(m.Reasons, "but "+strings.Join(conflicts, ", "))
	}
	return m
}

var certainRank = map[string]int{"vin": 4, "plate": 3, "photos": 2, "phone_model": 1}

func pairKey(a, b int64) (int64, int64) {
	if a < b {
		return a, b
	}
	return b, a
}

func pairStatus(tx *sql.Tx, a, b int64) (string, int64, error) {
	a, b = pairKey(a, b)
	var st string
	var id int64
	err := tx.QueryRow("SELECT status, id FROM duplicates WHERE car_a = ? AND car_b = ?", a, b).Scan(&st, &id)
	if errors.Is(err, sql.ErrNoRows) {
		return "", 0, nil
	}
	return st, id, err
}

// findMatches compares p against every live car except p.CarID, skipping rejected pairs.
// Results: matches with a score, best certain first, then by score. A photo link that is not
// unique (two cars match equally well on photos) is downgraded to a proposal.
func findMatches(tx *sql.Tx, p *probe, all map[int64]*probe) ([]match, error) {
	ix := newPhotoIndex(all)
	var out []match
	for id, c := range all {
		if id == p.CarID {
			continue
		}
		m := compare(p, c, ix)
		if m.Score <= 0 {
			continue
		}
		if p.CarID != 0 {
			st, _, err := pairStatus(tx, p.CarID, id)
			if err != nil {
				return nil, err
			}
			if st == "rejected" || st == "merged" {
				continue
			}
		}
		out = append(out, m)
	}
	sort.Slice(out, func(i, j int) bool {
		ri, rj := certainRank[out[i].Certain], certainRank[out[j].Certain]
		if ri != rj {
			return ri > rj
		}
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].CarID < out[j].CarID
	})
	if len(out) > 1 && out[0].Certain == "photos" && out[1].Certain == "photos" {
		for i := range out {
			if out[i].Certain == "photos" {
				out[i].Certain, out[i].Score = "", 0.9
			}
		}
	}
	return out, nil
}

// storeProposal inserts or refreshes an open proposal; new ones write duplicate_proposed events.
func storeProposal(tx *sql.Tx, carID int64, m match, titles map[int64]string, author string, now float64) error {
	st, id, err := pairStatus(tx, carID, m.CarID)
	if err != nil {
		return err
	}
	switch st {
	case "rejected", "merged":
		return nil
	case "proposed":
		_, err := tx.Exec("UPDATE duplicates SET score = ?, reasons = ?, updated_at = ? WHERE id = ?", m.Score, jsonList(m.Reasons), now, id)
		return err
	}
	a, b := pairKey(carID, m.CarID)
	res, err := tx.Exec("INSERT INTO duplicates (car_a, car_b, score, reasons, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'proposed', ?, ?)",
		a, b, m.Score, jsonList(m.Reasons), now, now)
	if err != nil {
		return err
	}
	dupID, err := res.LastInsertId()
	if err != nil {
		return err
	}
	for _, pair := range [][2]int64{{carID, m.CarID}, {m.CarID, carID}} {
		summary := fmt.Sprintf("possible duplicate of car #%d (%s): %s", pair[1], titles[pair[1]], strings.Join(m.Reasons, ", "))
		if _, err := addEvent(tx, ev{CarID: pair[0], Type: "duplicate_proposed", At: now, Author: author, Summary: summary,
			Data: map[string]any{"duplicate_id": dupID, "other_car_id": pair[1], "score": m.Score, "reasons": m.Reasons}}); err != nil {
			return err
		}
	}
	return nil
}

// proposeDuplicates stores likely matches of carID as proposals (certain ones too when certainToo).
func proposeDuplicates(tx *sql.Tx, carID int64, certainToo bool, author string, now float64) ([]match, error) {
	all, titles, err := loadProbes(tx)
	if err != nil {
		return nil, err
	}
	p, ok := all[carID]
	if !ok {
		return nil, nil
	}
	ms, err := findMatches(tx, p, all)
	if err != nil {
		return nil, err
	}
	for _, m := range ms {
		if m.Certain != "" && !certainToo {
			continue
		}
		if err := storeProposal(tx, carID, m, titles, author, now); err != nil {
			return nil, err
		}
	}
	return ms, nil
}

// autoMerge: identity proofs strong enough to merge two existing cars without asking.
var autoMerge = map[string]bool{"vin": true, "plate": true, "phone_model": true}

// rededupe auto-merges certain matches of carID (older car wins) and stores likely ones.
// Returns the live car id.
func rededupe(tx *sql.Tx, carID int64, author string, now float64) (int64, error) {
	for range 10 {
		all, titles, err := loadProbes(tx)
		if err != nil {
			return 0, err
		}
		p, ok := all[carID]
		if !ok {
			return resolveCar(tx, itoa(carID))
		}
		ms, err := findMatches(tx, p, all)
		if err != nil {
			return 0, err
		}
		if len(ms) > 0 && autoMerge[ms[0].Certain] {
			m := ms[0]
			target, source := pairKey(carID, m.CarID)
			reason := strings.Join(m.Reasons, ", ")
			if err := mergeInto(tx, target, source, author, "auto: "+reason, now); err != nil {
				return 0, err
			}
			carID = target
			continue
		}
		for _, m := range ms {
			if err := storeProposal(tx, carID, m, titles, author, now); err != nil {
				return 0, err
			}
		}
		return carID, nil
	}
	return carID, nil
}

// --- merge -------------------------------------------------------------------

var closedStatuses = []string{"closed", "dropped", "bought"}

func mergeInto(tx *sql.Tx, target, source int64, author, reason string, now float64) error {
	if target == source {
		return invalidf("cannot merge car %d into itself", target)
	}
	tc, err := loadCar(tx, target)
	if err != nil {
		return err
	}
	sc, err := loadCar(tx, source)
	if err != nil {
		return err
	}
	if sc.MergedInto.Valid || tc.MergedInto.Valid {
		return invalidf("car already merged")
	}
	for _, q := range []string{
		"UPDATE listings SET car_id = ? WHERE car_id = ?",
		"UPDATE messages SET car_id = ? WHERE car_id = ?",
		"UPDATE notes SET car_id = ? WHERE car_id = ?",
		"UPDATE events SET car_id = ? WHERE car_id = ?",
		"UPDATE car_aliases SET car_id = ? WHERE car_id = ?",
		"UPDATE cars SET merged_into = ? WHERE merged_into = ?",
	} {
		if _, err := tx.Exec(q, target, source); err != nil {
			return err
		}
	}

	// Photos: dedupe by sha, append after the target's photos.
	var maxPos int
	var hasCover int
	if err := tx.QueryRow("SELECT COALESCE(MAX(position), -1), COALESCE(MAX(cover), 0) FROM photos WHERE car_id = ?", target).Scan(&maxPos, &hasCover); err != nil {
		return err
	}
	type ph struct {
		id    int64
		sha   string
		cover int
	}
	rows, err := tx.Query("SELECT id, sha256, cover FROM photos WHERE car_id = ? ORDER BY position, id", source)
	if err != nil {
		return err
	}
	var srcPhotos []ph
	for rows.Next() {
		var p ph
		if err := rows.Scan(&p.id, &p.sha, &p.cover); err != nil {
			rows.Close()
			return err
		}
		srcPhotos = append(srcPhotos, p)
	}
	rows.Close()
	for _, p := range srcPhotos {
		var exists int
		err := tx.QueryRow("SELECT 1 FROM photos WHERE car_id = ? AND sha256 = ?", target, p.sha).Scan(&exists)
		if err == nil {
			if _, err := tx.Exec("DELETE FROM photos WHERE id = ?", p.id); err != nil {
				return err
			}
			continue
		} else if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		maxPos++
		cover := p.cover
		if hasCover != 0 {
			cover = 0
		}
		if _, err := tx.Exec("UPDATE photos SET car_id = ?, position = ?, cover = ? WHERE id = ?", target, maxPos, cover, p.id); err != nil {
			return err
		}
	}

	for _, t := range []string{"options", "facts"} {
		if _, err := tx.Exec("UPDATE OR IGNORE "+t+" SET car_id = ? WHERE car_id = ?", target, source); err != nil {
			return err
		}
		if _, err := tx.Exec("DELETE FROM "+t+" WHERE car_id = ?", source); err != nil {
			return err
		}
	}
	if _, err := tx.Exec("UPDATE OR IGNORE verdicts SET car_id = ? WHERE car_id = ?", target, source); err != nil {
		return err
	}
	if _, err := tx.Exec("DELETE FROM verdicts WHERE car_id = ?", source); err != nil {
		return err
	}

	// Spec columns: fill the target's gaps.
	fill := map[string]any{}
	for k, v := range sc.Specs {
		if _, ok := tc.Specs[k]; !ok {
			fill[k] = v
		}
	}
	if _, err := writeSpecs(tx, tc, fill, false, now); err != nil {
		return err
	}

	status := tc.Status
	if !slices.Contains(closedStatuses, tc.Status) && !slices.Contains(closedStatuses, sc.Status) && statusRank(sc.Status) > statusRank(tc.Status) {
		status = sc.Status
	}
	union := func(a, b []string) []string {
		out := append([]string{}, a...)
		for _, x := range b {
			if !slices.Contains(out, x) {
				out = append(out, x)
			}
		}
		return out
	}
	sellerID := tc.SellerID
	if !sellerID.Valid {
		sellerID = sc.SellerID
	}
	var sellerArg any
	if sellerID.Valid {
		sellerArg = sellerID.Int64
	}
	slug := tc.Slug
	if !slug.Valid && sc.Slug.Valid {
		slug = sc.Slug
	}
	if _, err := tx.Exec("UPDATE cars SET slug = NULL, merged_into = ?, updated_at = ? WHERE id = ?", target, now, source); err != nil {
		return err
	}
	statusChangedAt := tc.StatusChangedAt
	if status != tc.Status {
		statusChangedAt = sql.NullFloat64{Float64: now, Valid: true}
	}
	if _, err := tx.Exec(`UPDATE cars SET slug = ?, seller_id = ?, summary = COALESCE(summary, ?), status = ?, status_changed_at = ?,
		needs_owner = ?, needs_owner_reason = COALESCE(needs_owner_reason, ?), red_flags = ?, open_questions = ?, updated_at = ? WHERE id = ?`,
		strPtrArg(slug), sellerArg, strPtrArg(sc.Summary), status, nullFloatArg(statusChangedAt),
		boolInt(tc.NeedsOwner || sc.NeedsOwner), strPtrArg(sc.NeedsOwnerReason),
		jsonList(union(tc.RedFlags, sc.RedFlags)), jsonList(union(tc.OpenQuestions, sc.OpenQuestions)), now, target); err != nil {
		return err
	}
	// Model family override: the target's wins. Good deal: the target's flag wins; an unflagged target takes the source's.
	if _, err := tx.Exec("UPDATE cars SET model_family_override = COALESCE(model_family_override, ?) WHERE id = ?",
		strPtrArg(sc.FamilyOverride), target); err != nil {
		return err
	}
	if !tc.GoodDeal && sc.GoodDeal {
		if _, err := tx.Exec("UPDATE cars SET good_deal = 1, good_deal_note = ?, good_deal_by = ?, good_deal_at = ? WHERE id = ?",
			strPtrArg(sc.GoodDealNote), strPtrArg(sc.GoodDealBy), nullFloatArg(sc.GoodDealAt), target); err != nil {
			return err
		}
	}

	// Duplicate proposals: the merged pair → merged; source's other pairs move to the target.
	a, b := pairKey(target, source)
	if st, _, err := pairStatus(tx, a, b); err != nil {
		return err
	} else if st == "" {
		if _, err := tx.Exec("INSERT INTO duplicates (car_a, car_b, score, reasons, status, created_at, updated_at) VALUES (?, ?, 1, ?, 'merged', ?, ?)",
			a, b, jsonList([]string{reason}), now, now); err != nil {
			return err
		}
	} else if _, err := tx.Exec("UPDATE duplicates SET status = 'merged', updated_at = ? WHERE car_a = ? AND car_b = ?", now, a, b); err != nil {
		return err
	}
	type dup struct {
		id, other int64
	}
	rows, err = tx.Query("SELECT id, CASE WHEN car_a = ? THEN car_b ELSE car_a END FROM duplicates WHERE (car_a = ? OR car_b = ?) AND NOT (car_a = ? AND car_b = ?)",
		source, source, source, a, b)
	if err != nil {
		return err
	}
	var dups []dup
	for rows.Next() {
		var d dup
		if err := rows.Scan(&d.id, &d.other); err != nil {
			rows.Close()
			return err
		}
		dups = append(dups, d)
	}
	rows.Close()
	for _, d := range dups {
		na, nb := pairKey(target, d.other)
		if d.other == target {
			continue
		}
		if st, _, err := pairStatus(tx, na, nb); err != nil {
			return err
		} else if st != "" {
			if _, err := tx.Exec("DELETE FROM duplicates WHERE id = ?", d.id); err != nil {
				return err
			}
			continue
		}
		if _, err := tx.Exec("UPDATE duplicates SET car_a = ?, car_b = ?, updated_at = ? WHERE id = ?", na, nb, now, d.id); err != nil {
			return err
		}
	}

	summary := fmt.Sprintf("merged car #%d (%s) into this car", source, sc.title())
	if reason != "" {
		summary += ": " + reason
	}
	_, err = addEvent(tx, ev{CarID: target, Type: "merge", At: now, Author: author, Summary: summary,
		Data: map[string]any{"from": source, "from_title": sc.title(), "reason": reason}})
	return err
}

func strPtrArg(n sql.NullString) any {
	if !n.Valid {
		return nil
	}
	return n.String
}

func nullFloatArg(n sql.NullFloat64) any {
	if !n.Valid {
		return nil
	}
	return n.Float64
}

// Merge handles POST /cars/{car}/merge. Sources already merged into the target are skipped.
func (s *Store) Merge(ctx context.Context, ref string, from []string, author string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		if len(from) == 0 {
			return invalidf("from must list at least one car")
		}
		now := s.nowTS()
		target, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		for _, f := range from {
			src, err := resolveCar(tx, f)
			if err != nil {
				return err
			}
			if src == target {
				continue
			}
			if err := mergeInto(tx, target, src, author, "manual", now); err != nil {
				return err
			}
		}
		out, err = carDetail(tx, target)
		return err
	})
	return out, err
}

// Split handles POST /cars/{car}/split; returns the new car.
func (s *Store) Split(ctx context.Context, ref string, in api.SplitInput, author string) (*api.CarDetail, error) {
	var out *api.CarDetail
	err := s.tx(ctx, func(tx *sql.Tx) error {
		now := s.nowTS()
		if len(in.ListingIDs) == 0 {
			return invalidf("listing_ids is required")
		}
		id, err := resolveCar(tx, ref)
		if err != nil {
			return err
		}
		car, err := loadCar(tx, id)
		if err != nil {
			return err
		}
		sellerIDs := map[int64]bool{}
		args := []any{}
		for _, lid := range in.ListingIDs {
			var cid int64
			var sid sql.NullInt64
			err := tx.QueryRow("SELECT car_id, seller_id FROM listings WHERE id = ?", lid).Scan(&cid, &sid)
			if errors.Is(err, sql.ErrNoRows) || (err == nil && cid != id) {
				return invalidf("listing %d does not belong to car %d", lid, id)
			} else if err != nil {
				return err
			}
			if sid.Valid {
				sellerIDs[sid.Int64] = true
			} else if car.SellerID.Valid {
				sellerIDs[car.SellerID.Int64] = true
			}
			args = append(args, lid)
		}
		specs := map[string]any{}
		for k, v := range car.Specs {
			if k != "vin" && k != "plate" { // identifiers belong to exactly one of the two cars
				specs[k] = v
			}
		}
		n := newCar{Specs: specs}
		if car.SellerID.Valid {
			n.SellerID = car.SellerID.Int64
		}
		newID, err := insertCar(tx, n, now)
		if err != nil {
			return err
		}
		if _, err := tx.Exec("UPDATE cars SET model_family_override = ? WHERE id = ?", strPtrArg(car.FamilyOverride), newID); err != nil {
			return err
		}
		in1 := placeholders(len(args))
		if _, err := tx.Exec("UPDATE listings SET car_id = ? WHERE id IN ("+in1+")", append([]any{newID}, args...)...); err != nil {
			return err
		}
		if in.MovePhotos == nil || *in.MovePhotos {
			if _, err := tx.Exec("UPDATE photos SET car_id = ?, cover = 0 WHERE car_id = ? AND listing_id IN ("+in1+")", append([]any{newID, id}, args...)...); err != nil {
				return err
			}
		}
		if in.MoveMessages {
			var vals []any
			for sid := range sellerIDs {
				vs, err := sellerContactValues(tx, sid)
				if err != nil {
					return err
				}
				for _, v := range vs {
					vals = append(vals, v)
				}
			}
			if len(vals) > 0 {
				q := "UPDATE messages SET car_id = ? WHERE car_id = ? AND counterpart IN (" + placeholders(len(vals)) + ")"
				if _, err := tx.Exec(q, append([]any{newID, id}, vals...)...); err != nil {
					return err
				}
			}
		}
		a, b := pairKey(id, newID)
		if _, err := tx.Exec("INSERT INTO duplicates (car_a, car_b, score, reasons, status, created_at, updated_at) VALUES (?, ?, 0, ?, 'rejected', ?, ?)",
			a, b, jsonList([]string{"split"}), now, now); err != nil {
			return err
		}
		ids := fmt.Sprint(in.ListingIDs)
		if _, err := addEvent(tx, ev{CarID: id, Type: "split", At: now, Author: author,
			Summary: fmt.Sprintf("split listings %s out to car #%d", ids, newID),
			Data:    map[string]any{"to": newID, "listing_ids": in.ListingIDs}}); err != nil {
			return err
		}
		if _, err := addEvent(tx, ev{CarID: newID, Type: "split", At: now, Author: author,
			Summary: fmt.Sprintf("split from car #%d (%s), listings %s", id, car.title(), ids),
			Data:    map[string]any{"from": id, "listing_ids": in.ListingIDs}}); err != nil {
			return err
		}
		out, err = carDetail(tx, newID)
		return err
	})
	return out, err
}

// ListDuplicates handles GET /duplicates.
func (s *Store) ListDuplicates(ctx context.Context, status, carRef string) ([]api.DuplicateCandidate, error) {
	if status == "" {
		status = "proposed"
	}
	if !slices.Contains([]string{"proposed", "rejected", "merged"}, status) {
		return nil, badRequestf("status must be proposed|rejected|merged")
	}
	var out []api.DuplicateCandidate
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var err error
		if carRef == "" {
			out, err = loadDuplicates(tx, "status = ?", 0, status)
			return err
		}
		id, err := resolveCar(tx, carRef)
		if err != nil {
			return err
		}
		out, err = loadDuplicates(tx, "status = ? AND (car_a = ? OR car_b = ?)", id, status, id, id)
		return err
	})
	return out, err
}

// RejectDuplicate handles POST /duplicates/{id}/reject.
func (s *Store) RejectDuplicate(ctx context.Context, id int64) (*api.DuplicateCandidate, error) {
	var out *api.DuplicateCandidate
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var st string
		err := tx.QueryRow("SELECT status FROM duplicates WHERE id = ?", id).Scan(&st)
		if errors.Is(err, sql.ErrNoRows) {
			return notFoundf("duplicate proposal %d not found", id)
		} else if err != nil {
			return err
		}
		if st == "merged" {
			return conflictf("duplicate proposal %d was already merged", id)
		}
		if _, err := tx.Exec("UPDATE duplicates SET status = 'rejected', updated_at = ? WHERE id = ?", s.nowTS(), id); err != nil {
			return err
		}
		ds, err := loadDuplicates(tx, "id = ?", 0, id)
		if err != nil {
			return err
		}
		out = &ds[0]
		return nil
	})
	return out, err
}
