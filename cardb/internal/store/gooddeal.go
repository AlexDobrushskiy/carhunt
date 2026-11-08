package store

import (
	"cmp"
	"context"
	"database/sql"
	"regexp"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

const maxGoodDealNote = 300

func loadGoodDeal(tx *sql.Tx, carID int64) (*api.GoodDeal, error) {
	c, err := loadCar(tx, carID)
	if err != nil {
		return nil, err
	}
	return c.goodDeal(), nil
}

func (c *carRow) goodDeal() *api.GoodDeal {
	return &api.GoodDeal{GoodDeal: c.GoodDeal, Note: strPtr(c.GoodDealNote), By: strPtr(c.GoodDealBy), At: fromNullTS(c.GoodDealAt)}
}

// SetGoodDeal handles PUT /cars/{car}/good-deal. note nil keeps the current note while the flag stays on;
// turning the flag off clears the note. Nothing changes (no event, no touch) when flag and note are unchanged.
func (s *Store) SetGoodDeal(ctx context.Context, ref string, on bool, note *string, author string, atTime *time.Time) (*api.GoodDeal, error) {
	if note != nil {
		n := strings.Join(strings.Fields(*note), " ")
		if len([]rune(n)) > maxGoodDealNote {
			return nil, invalidf("note must be at most %d characters", maxGoodDealNote)
		}
		note = &n
	}
	at := atOr(atTime, s.nowTS())
	return carScoped(s, ctx, ref, func(tx *sql.Tx, id int64) (*api.GoodDeal, error) {
		car, err := loadCar(tx, id)
		if err != nil {
			return nil, err
		}
		newNote := ""
		switch {
		case !on:
		case note != nil:
			newNote = *note
		case car.GoodDeal:
			newNote = car.GoodDealNote.String
		}
		if on == car.GoodDeal && newNote == car.GoodDealNote.String {
			return car.goodDeal(), nil
		}
		if _, err := tx.Exec("UPDATE cars SET good_deal = ?, good_deal_note = ?, good_deal_by = ?, good_deal_at = ? WHERE id = ?",
			boolInt(on), nullStr(newNote), author, at, id); err != nil {
			return nil, err
		}
		summary := "good deal cleared"
		if on {
			summary = "good deal ★"
			if newNote != "" {
				summary += ": " + newNote
			}
		}
		if _, err := addEvent(tx, ev{CarID: id, Type: "good_deal", At: at, Author: author, Summary: summary,
			Data: map[string]any{"from": car.GoodDeal, "to": on, "note": nullStr(newNote)}}); err != nil {
			return nil, err
		}
		if err := touch(tx, id, at); err != nil {
			return nil, err
		}
		return loadGoodDeal(tx, id)
	})
}

var reDealRank = regexp.MustCompile(`(?i)^\s*T(\d+)\s*-\s*(\d+)\s*$`)

// dealRankKey orders deal_rank values: class 0 = parsed T<tier>-<n>, 1 = unparseable, 2 = missing.
type dealRankKey struct {
	class   int
	tier, n int
	raw     string
}

func parseDealRank(v *string) dealRankKey {
	if v == nil || strings.TrimSpace(*v) == "" {
		return dealRankKey{class: 2}
	}
	if m := reDealRank.FindStringSubmatch(*v); m != nil {
		t, err1 := strconv.Atoi(m[1])
		n, err2 := strconv.Atoi(m[2])
		if err1 == nil && err2 == nil {
			return dealRankKey{tier: t, n: n}
		}
	}
	return dealRankKey{class: 1, raw: strings.ToLower(strings.TrimSpace(*v))}
}

// compare returns -1/0/1 in the given direction; classes keep their order (parsed, unparseable, missing) either way.
func (a dealRankKey) compare(b dealRankKey, desc bool) int {
	if a.class != b.class {
		if a.class < b.class {
			return -1
		}
		return 1
	}
	c := 0
	switch {
	case a.class == 0 && a.tier != b.tier:
		c = cmp.Compare(a.tier, b.tier)
	case a.class == 0:
		c = cmp.Compare(a.n, b.n)
	case a.class == 1:
		c = strings.Compare(a.raw, b.raw)
	}
	if desc {
		c = -c
	}
	return c
}
