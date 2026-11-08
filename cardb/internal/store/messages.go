package store

import (
	"context"
	"crypto/sha1"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"

	"carhunt/cardb/internal/api"
)

var (
	directions  = []string{"in", "out"}
	senderKinds = []string{"seller", "agent", "owner", "system"}
	deliveries  = []string{"sent", "failed", "received", "unknown"}
	attachKinds = []string{"image", "video", "audio", "document", "other"}
)

// MessageDedupeKey is the server-derived key when neither external_id nor dedupe_key is given.
func MessageDedupeKey(channel, direction, counterpart, text string, at time.Time) string {
	minute := at.UTC().Truncate(time.Minute).Format(time.RFC3339)
	sum := sha1.Sum([]byte(channel + "|" + direction + "|" + counterpart + "|" + text + "|" + minute))
	return "auto:" + hex.EncodeToString(sum[:])
}

// carsForCounterpart returns live cars whose seller contacts, earlier messages or listing URLs match cp.
func carsForCounterpart(tx *sql.Tx, cp string) ([]int64, error) {
	set := map[int64]bool{}
	collect := func(q string, args ...any) error {
		rows, err := tx.Query(q, args...)
		if err != nil {
			return err
		}
		var ids []int64
		for rows.Next() {
			var id int64
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return err
			}
			ids = append(ids, id)
		}
		rows.Close()
		for _, id := range ids {
			live, err := resolveCar(tx, itoa(id))
			if err != nil {
				return err
			}
			set[live] = true
		}
		return rows.Err()
	}
	if err := collect(`SELECT c.id FROM cars c JOIN seller_contacts sc ON sc.seller_id = c.seller_id
		WHERE sc.value = ? AND sc.shared = 0 AND c.merged_into IS NULL`, cp); err != nil {
		return nil, err
	}
	if err := collect("SELECT DISTINCT car_id FROM messages WHERE counterpart = ? AND "+liveMessage, cp); err != nil {
		return nil, err
	}
	if nu, err := NormalizeURL(cp); err == nil && strings.Contains(cp, "/") {
		if err := collect("SELECT car_id FROM listings WHERE url_key = ?", nu.Key); err != nil {
			return nil, err
		}
	}
	out := make([]int64, 0, len(set))
	for id := range set {
		out = append(out, id)
	}
	slices.Sort(out)
	return out, nil
}

func validateAttachments(tx *sql.Tx, carID int64, atts []api.Attachment) error {
	for _, a := range atts {
		if !slices.Contains(attachKinds, a.Kind) {
			return invalidf("attachment kind must be one of %s", strings.Join(attachKinds, "|"))
		}
		if a.PhotoID != nil && tx != nil {
			var cid int64
			if err := tx.QueryRow("SELECT car_id FROM photos WHERE id = ?", *a.PhotoID).Scan(&cid); err != nil || cid != carID {
				return invalidf("photo %d does not belong to car %d", *a.PhotoID, carID)
			}
		}
	}
	return nil
}

// PatchMessage handles PATCH /messages/{id}: sent fields replace (error "" clears); idempotency keys never change.
func (s *Store) PatchMessage(ctx context.Context, id int64, in api.MessagePatch) (*api.Message, error) {
	if in.Delivery != nil && !slices.Contains(deliveries, *in.Delivery) {
		return nil, invalidf("delivery must be one of %s", strings.Join(deliveries, "|"))
	}
	var out *api.Message
	err := s.tx(ctx, func(tx *sql.Tx) error {
		cur, err := scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", id))
		if errors.Is(err, sql.ErrNoRows) {
			return notFoundf("message %d not found", id)
		} else if err != nil {
			return err
		}
		if cur.DeletedAt != nil {
			return conflictf("message %d is deleted; restore it first", id)
		}
		text, atts := cur.Text, cur.Attachments
		var sets []string
		var args []any
		if in.Attachments != nil {
			atts = *in.Attachments
			if atts == nil {
				atts = []api.Attachment{}
			}
			if err := validateAttachments(tx, cur.CarID, atts); err != nil {
				return err
			}
			sets = append(sets, "attachments = ?")
			args = append(args, mustJSON(atts))
		}
		if in.Text != nil {
			text = *in.Text
			sets = append(sets, "text = ?")
			args = append(args, text)
		}
		if text == "" && len(atts) == 0 {
			return invalidf("a message needs text or attachments")
		}
		if in.Delivery != nil {
			sets = append(sets, "delivery = ?")
			args = append(args, *in.Delivery)
		}
		if in.Error != nil {
			sets = append(sets, "error = ?")
			args = append(args, nullStr(strings.TrimSpace(*in.Error)))
		}
		if len(sets) > 0 {
			args = append(args, id)
			if _, err := tx.Exec("UPDATE messages SET "+strings.Join(sets, ", ")+" WHERE id = ?", args...); err != nil {
				return err
			}
		}
		out, err = scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", id))
		return err
	})
	return out, err
}

// attachExternalID reconciles a row logged live (by dedupe_key, no external id) with the provider's id
// found later: it sets external_id unless that channel already uses it, and fills empty/unknown sender fields.
func attachExternalID(tx *sql.Tx, m *api.Message, in api.MessageInput) error {
	var taken int
	err := tx.QueryRow("SELECT 1 FROM messages WHERE channel = ? AND external_id = ?", m.Channel, in.ExternalID).Scan(&taken)
	if err == nil {
		return nil // another row holds it: leave this one as is
	} else if !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	sets := []string{"external_id = ?"}
	args := []any{in.ExternalID}
	blank := func(v string) bool { return v == "" || v == "unknown" }
	if s := strings.TrimSpace(in.Sender); s != "" && blank(m.Sender) {
		sets = append(sets, "sender = ?")
		args = append(args, s)
	}
	if in.SenderKind != "" && blank(m.SenderKind) {
		sets = append(sets, "sender_kind = ?")
		args = append(args, in.SenderKind)
	}
	args = append(args, m.ID)
	if _, err := tx.Exec("UPDATE messages SET "+strings.Join(sets, ", ")+" WHERE id = ?", args...); err != nil {
		return err
	}
	updated, err := scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", m.ID))
	if err == nil {
		*m = *updated
	}
	return err
}

// AddMessage handles POST /messages. created=false when it already existed.
func (s *Store) AddMessage(ctx context.Context, in api.MessageInput, author string) (*api.Message, bool, error) {
	in.Channel = strings.TrimSpace(in.Channel)
	if in.Channel == "" {
		return nil, false, invalidf("channel is required")
	}
	if !slices.Contains(directions, in.Direction) {
		return nil, false, invalidf("direction must be in|out")
	}
	if in.Text == "" && len(in.Attachments) == 0 {
		return nil, false, invalidf("text is required")
	}
	if in.SenderKind != "" && !slices.Contains(senderKinds, in.SenderKind) {
		return nil, false, invalidf("sender_kind must be one of %s", strings.Join(senderKinds, "|"))
	}
	if in.Delivery != "" && !slices.Contains(deliveries, in.Delivery) {
		return nil, false, invalidf("delivery must be one of %s", strings.Join(deliveries, "|"))
	}
	if err := validateAttachments(nil, 0, in.Attachments); err != nil {
		return nil, false, err
	}
	cp := NormalizeCounterpart(in.Counterpart)
	at := s.now()
	if in.At != nil && !in.At.IsZero() {
		at = *in.At
	}
	key := strings.TrimSpace(in.DedupeKey)
	if key == "" && in.ExternalID == "" {
		key = MessageDedupeKey(in.Channel, in.Direction, cp, in.Text, at)
	}
	if key == "" {
		key = "ext:" + in.Channel + ":" + in.ExternalID
	}

	var out *api.Message
	created := false
	err := s.tx(ctx, func(tx *sql.Tx) error {
		existing := func(q string, args ...any) (bool, error) {
			m, err := scanMessage(tx.QueryRow(messageSelect+" WHERE "+q, args...))
			if errors.Is(err, sql.ErrNoRows) {
				return false, nil
			} else if err != nil {
				return false, err
			}
			out = m
			return true, nil
		}
		if in.ExternalID != "" {
			if ok, err := existing("channel = ? AND external_id = ?", in.Channel, in.ExternalID); ok || err != nil {
				if ok {
					out.MatchedBy = "external_id"
				}
				return err
			}
		}
		if ok, err := existing("dedupe_key = ?", key); ok || err != nil {
			if err != nil {
				return err
			}
			out.MatchedBy = "dedupe_key"
			if in.ExternalID == "" || out.ExternalID != nil {
				return nil
			}
			return attachExternalID(tx, out, in)
		}

		var carID int64
		var err error
		switch {
		case in.Car != "":
			if carID, err = resolveCar(tx, in.Car); err != nil {
				return err
			}
		case in.ListingURL != "":
			nu, err := NormalizeURL(in.ListingURL)
			if err != nil {
				return err
			}
			l, err := findListing(tx, nu)
			if err != nil {
				return err
			}
			if l != nil {
				if carID, err = resolveCar(tx, itoa(l.CarID)); err != nil {
					return err
				}
			}
		}
		if carID == 0 {
			if cp == "" {
				return invalidf("cannot resolve car: give car, a known listing_url or counterpart")
			}
			ids, err := carsForCounterpart(tx, cp)
			if err != nil {
				return err
			}
			switch len(ids) {
			case 0:
				return invalidf("cannot resolve car: counterpart %s is not known for any car", cp)
			case 1:
				carID = ids[0]
			default:
				return invalidf("counterpart %s matches several cars %v; pass car or listing_url", cp, ids)
			}
		}
		car, err := loadCar(tx, carID)
		if err != nil {
			return err
		}
		if err := validateAttachments(tx, carID, in.Attachments); err != nil {
			return err
		}
		if !in.AllowDuplicate {
			probe := &api.Message{CarID: carID, Channel: in.Channel, Direction: in.Direction, At: at, Text: in.Text,
				Attachments: in.Attachments, DedupeKey: &key, Delivery: in.Delivery}
			if probe.Delivery == "" && in.Error != "" {
				probe.Delivery = "failed"
			}
			if cp != "" {
				probe.Counterpart = &cp
			}
			if in.ExternalID != "" {
				probe.ExternalID = &in.ExternalID
			}
			m, err := findNearDuplicate(tx, probe)
			if err != nil || m != nil {
				if m == nil {
					return err
				}
				out = m
				if in.ExternalID != "" && m.ExternalID == nil {
					if err := attachExternalID(tx, out, in); err != nil {
						return err
					}
				}
				out.MatchedBy = "near_duplicate"
				return nil
			}
		}

		senderKind := in.SenderKind
		if senderKind == "" {
			switch {
			case in.Direction == "in":
				senderKind = "seller"
			case author == "owner":
				senderKind = "owner"
			default:
				senderKind = "agent"
			}
		}
		sender := strings.TrimSpace(in.Sender)
		if sender == "" {
			if in.Direction == "in" {
				sender = cp
			} else {
				sender = author
			}
		}
		delivery := in.Delivery
		if delivery == "" {
			switch {
			case in.Direction == "in":
				delivery = "received"
			case in.Error != "":
				delivery = "failed"
			default:
				delivery = "sent"
			}
		}
		atts := in.Attachments
		if atts == nil {
			atts = []api.Attachment{}
		}
		var sellerArg any
		if car.SellerID.Valid {
			sellerArg = car.SellerID.Int64
		}
		r, err := tx.Exec(`INSERT INTO messages (car_id, seller_id, channel, direction, at, sender_kind, sender, counterpart, text,
			attachments, delivery, error, external_id, dedupe_key, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			carID, sellerArg, in.Channel, in.Direction, ts(at), senderKind, sender, nullStr(cp), in.Text, mustJSON(atts),
			delivery, nullStr(in.Error), nullStr(in.ExternalID), key, author)
		if err != nil {
			return err
		}
		mid, err := r.LastInsertId()
		if err != nil {
			return err
		}
		created = true
		out, err = scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", mid))
		return err
	})
	return out, created, err
}

// --- near duplicates & deletion ----------------------------------------------------

// nearDupWindow is how far apart two loggings of one message may be (sends.log t vs provider time,
// minute-precision transcripts and histories).
const nearDupWindow = 5 * time.Minute

func normMessageText(s string) string { return strings.Join(strings.Fields(s), " ") }

// counterpartCore compares counterparts loosely: the first token ("x@y.example.com (group inbox)" = "x@y.example.com"),
// URLs by their normalized key.
func counterpartCore(p *string) string {
	if p == nil {
		return ""
	}
	f := strings.Fields(*p)
	if len(f) == 0 {
		return ""
	}
	if nu, err := NormalizeURL(f[0]); err == nil && strings.Contains(f[0], "/") {
		return nu.Key
	}
	return strings.ToLower(NormalizeCounterpart(f[0]))
}

// keyFamily is the logger a caller-given dedupe key came from ("sends:…" → "sends", "call-2" → "call-").
// Server-derived keys (auto:/ext:) carry no logger identity and return ok=false.
func keyFamily(key *string) (string, bool) {
	if key == nil || strings.HasPrefix(*key, "auto:") || strings.HasPrefix(*key, "ext:") {
		return "", false
	}
	i := strings.IndexFunc(*key, func(r rune) bool { return !(r == '-' || r == '_' || unicode.IsLetter(r)) })
	if i < 0 {
		i = len(*key)
	}
	return (*key)[:i], true
}

func attachmentKinds(atts []api.Attachment) string {
	ks := make([]string, len(atts))
	for i, a := range atts {
		ks[i] = a.Kind
	}
	return strings.Join(ks, ",")
}

// nearDuplicate reports whether a and b look like one message logged twice under different keys:
// same car, channel, direction, normalized text and attachment kinds, agreeing counterparts, within
// nearDupWindow — unless something marks them as two events: two different provider ids, one failed
// attempt and one not, or two different keys from the same logger (that logger saw two sends).
func nearDuplicate(a, b *api.Message) bool {
	if a.CarID != b.CarID || a.Channel != b.Channel || a.Direction != b.Direction {
		return false
	}
	if d := a.At.Sub(b.At); d > nearDupWindow || d < -nearDupWindow {
		return false
	}
	if a.ExternalID != nil && b.ExternalID != nil && *a.ExternalID != *b.ExternalID {
		return false
	}
	if (a.Delivery == "failed") != (b.Delivery == "failed") {
		return false
	}
	if ca, cb := counterpartCore(a.Counterpart), counterpartCore(b.Counterpart); ca != "" && cb != "" && ca != cb {
		return false
	}
	if fa, ok := keyFamily(a.DedupeKey); ok {
		if fb, ok := keyFamily(b.DedupeKey); ok && fa == fb && *a.DedupeKey != *b.DedupeKey {
			return false
		}
	}
	return normMessageText(a.Text) == normMessageText(b.Text) && attachmentKinds(a.Attachments) == attachmentKinds(b.Attachments)
}

// findNearDuplicate returns the closest live row that probe duplicates, or nil.
func findNearDuplicate(tx *sql.Tx, probe *api.Message) (*api.Message, error) {
	at, w := ts(probe.At), nearDupWindow.Seconds()
	var found *api.Message
	err := eachRow(tx, messageSelect+" WHERE car_id = ? AND channel = ? AND direction = ? AND at BETWEEN ? AND ? AND "+liveMessage+
		" ORDER BY ABS(at - ?), id", []any{probe.CarID, probe.Channel, probe.Direction, at - w, at + w, at}, func(sc scanner) error {
		m, err := scanMessage(sc)
		if err != nil {
			return err
		}
		if found == nil && nearDuplicate(probe, m) {
			found = m
		}
		return nil
	})
	return found, err
}

// MessageDuplicates handles GET /messages/duplicates: live pairs that nearDuplicate matches.
// Keep = the row with a provider id, else the older row.
func (s *Store) MessageDuplicates(ctx context.Context) ([]api.MessageDuplicate, error) {
	out := []api.MessageDuplicate{}
	err := s.tx(ctx, func(tx *sql.Tx) error {
		var all []*api.Message
		if err := eachRow(tx, messageSelect+" WHERE "+liveMessage+" ORDER BY car_id, channel, direction, at, id", nil, func(sc scanner) error {
			m, err := scanMessage(sc)
			if err == nil {
				all = append(all, m)
			}
			return err
		}); err != nil {
			return err
		}
		for i, a := range all {
			for _, b := range all[i+1:] {
				if b.CarID != a.CarID || b.Channel != a.Channel || b.Direction != a.Direction || b.At.Sub(a.At) > nearDupWindow {
					break
				}
				if !nearDuplicate(a, b) {
					continue
				}
				keep, drop := a, b
				if (drop.ExternalID != nil && keep.ExternalID == nil) || (keep.ExternalID == nil) == (drop.ExternalID == nil) && drop.ID < keep.ID {
					keep, drop = drop, keep
				}
				out = append(out, api.MessageDuplicate{CarID: a.CarID, Keep: *keep, Drop: *drop, Seconds: b.At.Sub(a.At).Seconds()})
			}
		}
		return nil
	})
	return out, err
}

func messageSummary(m *api.Message) string {
	arrow := "→"
	if m.Direction == "in" {
		arrow = "←"
	}
	return fmt.Sprintf("message #%d (%s %s, %s): %s", m.ID, m.Channel, arrow, m.At.UTC().Format("2006-01-02 15:04"), noteExcerpt(m.Text))
}

// DeleteMessage handles DELETE /messages/{id}: a soft delete. The row disappears from every read but keeps
// its keys, so loggers re-posting it get it back (still deleted) instead of a new row. Writes a
// message_deleted event. Deleting a deleted row is a no-op.
func (s *Store) DeleteMessage(ctx context.Context, id int64, reason, author string) (*api.Message, error) {
	return s.setMessageDeleted(ctx, id, true, strings.TrimSpace(reason), author)
}

// RestoreMessage handles POST /messages/{id}/restore (undo of DeleteMessage; writes message_restored).
func (s *Store) RestoreMessage(ctx context.Context, id int64, author string) (*api.Message, error) {
	return s.setMessageDeleted(ctx, id, false, "", author)
}

func (s *Store) setMessageDeleted(ctx context.Context, id int64, del bool, reason, author string) (*api.Message, error) {
	var out *api.Message
	err := s.tx(ctx, func(tx *sql.Tx) error {
		m, err := scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", id))
		if errors.Is(err, sql.ErrNoRows) {
			return notFoundf("message %d not found", id)
		} else if err != nil {
			return err
		}
		out = m
		if (m.DeletedAt != nil) == del {
			return nil
		}
		now := ts(s.now())
		typ, summary := "message_restored", "Restored "+messageSummary(m)
		data := map[string]any{"message_id": m.ID, "channel": m.Channel, "direction": m.Direction, "at": m.At, "dedupe_key": m.DedupeKey}
		if del {
			_, err = tx.Exec("UPDATE messages SET deleted_at = ?, deleted_by = ?, deleted_reason = ? WHERE id = ?", now, author, nullStr(reason), id)
			typ, summary = "message_deleted", "Removed "+messageSummary(m)
			if reason != "" {
				summary += " — " + reason
				data["reason"] = reason
			}
		} else {
			_, err = tx.Exec("UPDATE messages SET deleted_at = NULL, deleted_by = NULL, deleted_reason = NULL WHERE id = ?", id)
		}
		if err != nil {
			return err
		}
		if _, err := addEvent(tx, ev{CarID: m.CarID, Type: typ, At: now, Author: author, Summary: summary, Data: data}); err != nil {
			return err
		}
		if err := touch(tx, m.CarID, now); err != nil {
			return err
		}
		out, err = scanMessage(tx.QueryRow(messageSelect+" WHERE id = ?", id))
		return err
	})
	return out, err
}
