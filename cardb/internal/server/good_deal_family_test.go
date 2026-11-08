package server

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"testing"
	"time"

	"carhunt/cardb/internal/api"
)

func TestGoodDeal(t *testing.T) {
	c := newServer(t)
	car := c.upsert(map[string]any{"url": "https://example.invalid/gd", "make": "VW", "model": "ID.4 Pro"}).CarID
	other := c.upsert(map[string]any{"url": "https://example.invalid/gd2", "make": "Kia", "model": "EV6"}).CarID
	path := fmt.Sprintf("/api/v1/cars/%d/good-deal", car)
	finder := c.as("deal-finder")
	put := func(cl *client, body any) api.GoodDeal {
		t.Helper()
		var gd api.GoodDeal
		cl.call("PUT", path, body, 200, &gd)
		return gd
	}
	dealEvents := func() []api.Event { return eventsOfType(c.events(car), "good_deal") }

	if d := c.car(car); d.GoodDeal || d.GoodDealNote != nil || d.GoodDealBy != nil || d.GoodDealAt != nil {
		t.Fatalf("fresh car flagged: %+v", d)
	}
	at := time.Date(2026, 11, 4, 9, 30, 0, 0, time.UTC)
	gd := put(finder, map[string]any{"good_deal": true, "note": "  T1 cheapest\n  with   pano ", "at": at})
	if !gd.GoodDeal || deref(gd.Note) != "T1 cheapest with pano" || deref(gd.By) != "deal-finder" || gd.At == nil || !gd.At.Equal(at) {
		t.Fatalf("on: %+v", gd)
	}
	evs := dealEvents()
	if len(evs) != 1 || evs[0].Summary != "good deal ★: T1 cheapest with pano" || evs[0].Author != "deal-finder" || !evs[0].At.Equal(at) {
		t.Fatalf("on event: %+v", evs)
	}
	var data map[string]any
	if err := json.Unmarshal(evs[0].Data, &data); err != nil || data["from"] != false || data["to"] != true || data["note"] != "T1 cheapest with pano" {
		t.Fatalf("on event data: %s", evs[0].Data)
	}
	d := c.car(car)
	if !d.GoodDeal || deref(d.GoodDealNote) != "T1 cheapest with pano" || deref(d.GoodDealBy) != "deal-finder" || !d.GoodDealAt.Equal(at) {
		t.Fatalf("detail: %+v", d)
	}
	updated := d.UpdatedAt

	// Same flag + note, and on without a note: no-op (no event, no touch, by/at unchanged).
	put(c.as("someone"), map[string]any{"good_deal": true, "note": "T1 cheapest with pano"})
	gd = put(c.as("someone"), map[string]any{"good_deal": true})
	if deref(gd.Note) != "T1 cheapest with pano" || deref(gd.By) != "deal-finder" || len(dealEvents()) != 1 || !c.car(car).UpdatedAt.Equal(updated) {
		t.Fatalf("no-op changed something: %+v, %d events", gd, len(dealEvents()))
	}

	// On + "" clears the note; null too.
	gd = put(c, map[string]any{"good_deal": true, "note": ""})
	if !gd.GoodDeal || gd.Note != nil || deref(gd.By) != "agents" || len(dealEvents()) != 2 || dealEvents()[0].Summary != "good deal ★" {
		t.Fatalf("clear note: %+v", gd)
	}
	put(c, map[string]any{"good_deal": true, "note": "back"})
	if gd = put(c, map[string]any{"good_deal": true, "note": nil}); gd.Note != nil {
		t.Fatalf("null note: %+v", gd)
	}

	// Off clears the note even when one is sent; a second off is a no-op.
	put(c, map[string]any{"good_deal": true, "note": "again"})
	n := len(dealEvents())
	gd = put(c.as("robin"), map[string]any{"good_deal": false, "note": "ignored"})
	if gd.GoodDeal || gd.Note != nil || deref(gd.By) != "robin" || len(dealEvents()) != n+1 || dealEvents()[0].Summary != "good deal cleared" {
		t.Fatalf("off: %+v %+v", gd, dealEvents()[0])
	}
	put(c, map[string]any{"good_deal": false})
	if len(dealEvents()) != n+1 {
		t.Fatal("second off wrote an event")
	}
	if d := c.car(car); d.GoodDeal || d.GoodDealNote != nil || deref(d.GoodDealBy) != "robin" {
		t.Fatalf("detail after off: %+v", d)
	}

	// Filter.
	put(c, map[string]any{"good_deal": true})
	sameIDs(t, "good_deal=true", ids(c.list("good_deal=true")), car)
	sameIDs(t, "good_deal=false", ids(c.list("good_deal=false")), other)
	sameIDs(t, "no filter", ids(c.list("")), car, other)
	if l := c.list("good_deal=true"); !l.Cars[0].GoodDeal || l.Cars[0].GoodDealBy == nil || l.Cars[0].GoodDealAt == nil {
		t.Fatalf("summary fields: %+v", l.Cars[0])
	}

	// Errors.
	c.call("PUT", path, map[string]any{"note": "x"}, 422, nil)
	c.call("PUT", path, map[string]any{"good_deal": "yes"}, 400, nil)
	c.call("PUT", path, map[string]any{"good_deal": true, "note": 5}, 422, nil)
	c.call("PUT", path, map[string]any{"good_deal": true, "note": strings.Repeat("x", 301)}, 422, nil)
	c.call("PUT", path, map[string]any{"good_deal": true, "note": strings.Repeat("é", 300)}, 200, nil)
	c.call("PUT", "/api/v1/cars/99999/good-deal", map[string]any{"good_deal": true}, 404, nil)
	c.call("GET", "/api/v1/cars?good_deal=maybe", nil, 400, nil)
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", car), map[string]any{"good_deal": false}, 422, nil)
	// Read-only fields from a CarDetail are ignored by PATCH.
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", car), map[string]any{"deal_rank": "T1-1", "good_deal_by": "x", "model_family_manual": true, "km": 10}, 200, nil)
}

func TestDealRankSort(t *testing.T) {
	c := newServer(t)
	add := func(tag, rank string) int64 {
		id := c.upsert(map[string]any{"url": "https://example.invalid/" + tag, "make": "Kia", "model": "EV6"}).CarID
		if rank != "" {
			c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/facts/deal_rank", id), map[string]any{"value": rank}, 200, nil)
		}
		return id
	}
	t12 := add("a", "T1-2")
	missing1 := add("b", "")
	t110 := add("c", "t1-10")
	odd := add("d", "watch")
	t21 := add("e", "T2-1")
	missing2 := add("f", "")
	odd2 := add("g", "T3")
	order := func(q string) []int64 {
		t.Helper()
		return ids(c.list("sort=deal_rank" + q))
	}
	// Ties (missing) keep the list's usual tie-break: newer id first.
	if got, want := order(""), []int64{t12, t110, t21, odd2, odd, missing2, missing1}; !slices.Equal(got, want) {
		t.Fatalf("asc: %v, want %v", got, want)
	}
	if got, want := order("&order=desc"), []int64{t21, t110, t12, odd, odd2, missing2, missing1}; !slices.Equal(got, want) {
		t.Fatalf("desc: %v, want %v", got, want)
	}
	if l := c.list("sort=deal_rank&limit=1"); l.Cars[0].DealRank == nil || *l.Cars[0].DealRank != "T1-2" {
		t.Fatalf("summary deal_rank: %+v", l.Cars[0].DealRank)
	}
	if d := c.car(t110); d.DealRank == nil || *d.DealRank != "t1-10" {
		t.Fatalf("detail deal_rank: %v", d.DealRank)
	}
	if d := c.car(missing1); d.DealRank != nil {
		t.Fatal("deal_rank without the fact")
	}
}

func TestModelFamily(t *testing.T) {
	c := newServer(t)
	add := func(tag, mk, model, variant string) int64 {
		return c.upsert(map[string]any{"url": "https://example.invalid/" + tag, "make": mk, "model": model, "variant": variant}).CarID
	}
	id4 := add("a", "Volkswagen", "ID.4 Pro Performance", "")
	q4spb := add("b", "Audi", "Q4 e-tron", "Sportback 45 advanced LED")
	q4 := add("c", "Audi", "Q4 e-tron 40", "")
	odd := add("d", "Lada", "Niva Electric", "")
	eqa := add("e", "Mercedes-Benz", "EQA 250+", "")

	fam := func(id int64) (string, bool) {
		d := c.car(id)
		return deref(d.ModelFamily), d.ModelFamilyManual
	}
	for id, want := range map[int64]string{id4: "VW ID.4", q4spb: "Audi Q4 Sportback", q4: "Audi Q4", odd: "", eqa: "Mercedes EQA"} {
		if got, manual := fam(id); got != want || manual {
			t.Fatalf("car %d family = %q manual %v, want %q", id, got, manual, want)
		}
	}
	for _, s := range c.list("").Cars {
		if s.ID == q4spb && (deref(s.ModelFamily) != "Audi Q4 Sportback" || s.ModelFamilyManual) {
			t.Fatalf("summary family: %+v", s)
		}
	}

	sameIDs(t, "repeat", ids(c.list("model_family=VW+ID.4&model_family=audi+q4+sportback")), id4, q4spb)
	sameIDs(t, "comma", ids(c.list("model_family=VW%20ID.4,Audi%20Q4")), id4, q4)
	sameIDs(t, "none", ids(c.list("model_family=none")), odd)
	sameIDs(t, "none or EQA", ids(c.list("model_family=none,Mercedes+EQA")), odd, eqa)
	sameIDs(t, "AND other filters", ids(c.list("model_family=Audi+Q4,Audi+Q4+Sportback&model=sportback")), q4spb)
	sameIDs(t, "model substring unchanged", ids(c.list("model=q4")), q4spb, q4)
	c.call("GET", "/api/v1/cars?model_family=Audi+Q5", nil, 400, nil)

	var fams api.ModelFamilies
	c.call("GET", "/api/v1/model-families", nil, 200, &fams)
	want := []api.ModelFamilyCount{{Family: "Audi Q4", Make: "Audi", Count: 1}, {Family: "Audi Q4 Sportback", Make: "Audi", Count: 1}, {Family: "Mercedes EQA", Make: "Mercedes", Count: 1}, {Family: "VW ID.4", Make: "VW", Count: 1}}
	if !slices.Equal(fams.Families, want) || fams.Unmapped != 1 || !slices.Contains(fams.Known, "Škoda Enyaq Coupé") {
		t.Fatalf("model-families: %+v", fams)
	}

	// Manual override: canonical name stored, case/diacritics-insensitive input, spec_change event.
	carPath := fmt.Sprintf("/api/v1/cars/%d", odd)
	var d api.CarDetail
	c.call("PATCH", carPath, map[string]any{"model_family": "skoda enyaq coupe"}, 200, &d)
	if deref(d.ModelFamily) != "Škoda Enyaq Coupé" || !d.ModelFamilyManual {
		t.Fatalf("override: %v %v", d.ModelFamily, d.ModelFamilyManual)
	}
	if sc := eventsOfType(d.Events, "spec_change"); len(sc) == 0 || sc[0].Summary != "spec: model_family auto → Škoda Enyaq Coupé" {
		t.Fatalf("override event: %+v", sc)
	}
	sameIDs(t, "none after override", ids(c.list("model_family=none")), []int64{}...)
	sameIDs(t, "override filter", ids(c.list("model_family=Škoda+Enyaq+Coupé")), odd)
	n := len(eventsOfType(c.events(odd), "spec_change"))
	c.call("PATCH", carPath, map[string]any{"model_family": "Škoda Enyaq Coupé"}, 200, nil)
	if len(eventsOfType(c.events(odd), "spec_change")) != n {
		t.Fatal("same override wrote an event")
	}
	// An override beats the derived family.
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", q4), map[string]any{"model_family": "Audi Q4 Sportback"}, 200, nil)
	c.call("GET", "/api/v1/model-families", nil, 200, &fams)
	if fams.Unmapped != 0 || fams.Families[0].Family != "Audi Q4 Sportback" || fams.Families[0].Count != 2 || fams.Families[1].Family != "Mercedes EQA" {
		t.Fatalf("model-families after overrides: %+v", fams)
	}

	body := c.call("PATCH", carPath, map[string]any{"model_family": "Tesla Roadster"}, 422, nil)
	if !strings.Contains(string(body), "unknown model family") || !strings.Contains(string(body), "/model-families") {
		t.Fatalf("422 body: %s", body)
	}
	c.call("PATCH", carPath, map[string]any{"model_family": 4}, 422, nil)
	c.call("PATCH", carPath, map[string]any{"model_family": nil}, 200, &d)
	if d.ModelFamily != nil || d.ModelFamilyManual {
		t.Fatalf("back to auto: %v %v", d.ModelFamily, d.ModelFamilyManual)
	}
	if sc := eventsOfType(d.Events, "spec_change"); sc[0].Summary != "spec: model_family Škoda Enyaq Coupé → auto" {
		t.Fatalf("clear event: %+v", sc[0])
	}
	// A spec edit re-derives the family at read time.
	c.call("PATCH", carPath, map[string]any{"make": "Kia", "model": "EV9 GT-Line"}, 200, &d)
	if deref(d.ModelFamily) != "Kia EV9" || d.ModelFamilyManual {
		t.Fatalf("derived after spec edit: %v", d.ModelFamily)
	}
}

func TestMergeCarriesGoodDealAndFamily(t *testing.T) {
	c := newServer(t)
	add := func(tag string) int64 {
		return c.upsert(map[string]any{"url": "https://example.invalid/" + tag, "make": "Lada", "model": "Niva Electric"}).CarID
	}
	gdPath := func(id int64) string { return fmt.Sprintf("/api/v1/cars/%d/good-deal", id) }
	famPatch := func(id int64, fam string) {
		c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", id), map[string]any{"model_family": fam}, 200, nil)
	}
	merge := func(target, source int64) api.CarDetail {
		var d api.CarDetail
		c.call("POST", fmt.Sprintf("/api/v1/cars/%d/merge", target), map[string]any{"from": []string{fmt.Sprint(source)}}, 200, &d)
		return d
	}

	// Unflagged target without override takes the source's flag, note, by, at and override.
	target, source := add("t1"), add("s1")
	at := time.Date(2026, 11, 3, 8, 0, 0, 0, time.UTC)
	c.as("deal-finder").call("PUT", gdPath(source), map[string]any{"good_deal": true, "note": "T2-4", "at": at}, 200, nil)
	famPatch(source, "MINI Countryman")
	d := merge(target, source)
	if !d.GoodDeal || deref(d.GoodDealNote) != "T2-4" || deref(d.GoodDealBy) != "deal-finder" || !d.GoodDealAt.Equal(at) {
		t.Fatalf("merged good deal: %+v %v %v %v", d.GoodDeal, d.GoodDealNote, d.GoodDealBy, d.GoodDealAt)
	}
	if deref(d.ModelFamily) != "MINI Countryman" || !d.ModelFamilyManual {
		t.Fatalf("merged family: %v %v", d.ModelFamily, d.ModelFamilyManual)
	}

	// A flagged target keeps its own flag/note; a target override wins.
	target, source = add("t2"), add("s2")
	c.as("robin").call("PUT", gdPath(target), map[string]any{"good_deal": true, "note": "mine"}, 200, nil)
	c.call("PUT", gdPath(source), map[string]any{"good_deal": true, "note": "theirs"}, 200, nil)
	famPatch(target, "Kia EV6")
	famPatch(source, "VW ID.4")
	d = merge(target, source)
	if !d.GoodDeal || deref(d.GoodDealNote) != "mine" || deref(d.GoodDealBy) != "robin" || deref(d.ModelFamily) != "Kia EV6" {
		t.Fatalf("target kept: %+v %v %v %v", d.GoodDeal, d.GoodDealNote, d.GoodDealBy, d.ModelFamily)
	}

	// An unflagged source never clears a flagged target.
	target, source = add("t3"), add("s3")
	c.call("PUT", gdPath(target), map[string]any{"good_deal": true}, 200, nil)
	if d = merge(target, source); !d.GoodDeal || d.ModelFamily != nil {
		t.Fatalf("flag lost or family invented: %+v %v", d.GoodDeal, d.ModelFamily)
	}

	// Split copies the override to the new car (same physical model), never the flag.
	famPatch(target, "Nissan Ariya")
	var split api.CarDetail
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/split", target), map[string]any{"listing_ids": []int64{d.Listings[1].ID}}, 200, &split)
	if deref(split.ModelFamily) != "Nissan Ariya" || !split.ModelFamilyManual || split.GoodDeal {
		t.Fatalf("split: %v %v %v", split.ModelFamily, split.ModelFamilyManual, split.GoodDeal)
	}
}
