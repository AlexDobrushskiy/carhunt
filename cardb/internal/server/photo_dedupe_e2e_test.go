package server

import (
	"fmt"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

// Dealer banner / stock images are shared across different cars. They must never link or merge
// different cars (prod 2026-11-03: BMW iX1s and MINIs merged into a dropped VW ID.5).
func TestPhotoDedupeSharedBanners(t *testing.T) {
	c := newServer(t)
	img := func(seed int64) []byte { return jpegOf(t, pattern(seed, 1000, 667), 85) }
	reenc := func(seed int64) []byte { return jpegOf(t, degraded(pattern(seed, 1000, 667), seed), 60) }
	imgs := imageServer(t, map[string][]byte{
		"/banner1.jpg": reenc(101), "/banner2.jpg": reenc(102),
		"/ix1-a.jpg": img(201), "/ix1-b.jpg": img(202),
		"/id5-own1.jpg": reenc(11), "/id5-own2.jpg": reenc(12), "/id5-own3.jpg": reenc(13),
		"/q4-a.jpg": img(301), "/q4-b.jpg": img(302),
		"/eqa-a.jpg": img(401),
	})
	dealer := func(phone string) map[string]any {
		return map[string]any{"name": "Autohaus Main", "type": "dealer", "contacts": []map[string]any{{"kind": "phone", "value": phone}}}
	}

	// The dealer's VW ID.5, dropped by the owner: its own photos plus the dealer's two banners.
	id5 := c.upsert(map[string]any{
		"url": "https://www.autoscout24.de/angebote/vw-id-5-pro-elektro-11111111-1111-1111-1111-111111111111", "price": 36900,
		"make": "VW", "model": "ID.5 Pro", "reg_date": "2024-06", "km": 24800, "city": "Kassel", "country": "DE",
		"seller": dealer("+49 555 1234567"),
	})
	for _, s := range []int64{11, 12, 13, 101, 102} {
		c.uploadPhoto(id5.CarID, img(s), map[string]string{"source": "ad", "listing_id": fmt.Sprint(id5.ListingID)}, 201)
	}
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/status", id5.CarID), map[string]any{"status": "dropped", "reason": "👎"}, 200, nil)

	// 1. A different car (BMW iX1, other city, other phone) whose ad carries the same two banners:
	// its own car, no link, no proposal.
	ix1 := c.upsert(map[string]any{
		"url": "https://www.autoscout24.be/fr/offres/bmw-ix1-xdrive30-22222222-2222-2222-2222-222222222222", "price": 39900,
		"make": "BMW", "model": "iX1 xDrive30", "reg_date": "2025-03", "km": 12000, "city": "Antwerpen", "country": "BE",
		"seller":     dealer("+32 3 555 0101"),
		"photo_urls": []string{imgs.URL + "/banner1.jpg", imgs.URL + "/banner2.jpg", imgs.URL + "/ix1-a.jpg", imgs.URL + "/ix1-b.jpg"},
	})
	if !ix1.CarCreated || ix1.LinkedBy != nil || ix1.CarID == id5.CarID {
		t.Fatalf("iX1 with shared banners linked to the ID.5: %+v", ix1)
	}
	if len(ix1.DuplicateCandidates) != 0 {
		t.Fatalf("iX1 got a duplicate proposal from banners alone: %+v", ix1.DuplicateCandidates)
	}

	// 2. A different car created without photos, banners attached afterwards: no auto-merge.
	eqa := c.upsert(map[string]any{
		"url": "https://www.autoscout24.es/anuncios/mercedes-eqa-250-33333333-3333-3333-3333-333333333333", "price": 33000,
		"make": "Mercedes", "model": "EQA 250", "reg_date": "2023-06", "km": 41000, "city": "Madrid", "country": "ES",
	})
	for _, s := range []int64{101, 102} {
		c.uploadPhoto(eqa.CarID, img(s), map[string]string{"source": "ad", "listing_id": fmt.Sprint(eqa.ListingID)}, 201)
	}
	if got := c.car(eqa.CarID); got.ID != eqa.CarID || len(got.MergedFrom) > 0 {
		t.Fatalf("EQA merged by banner photos: live car %d, merged_from %v", got.ID, got.MergedFrom)
	}

	// 3. Same model, close km, but the only shared photos are banners now seen on ≥3 cars: not a link.
	twin := c.upsert(map[string]any{
		"url": "https://www.mobile.de/fahrzeuge/details.html?id=444444444", "price": 36500,
		"make": "VW", "model": "ID.5 Pro", "reg_date": "2024-06", "km": 25900, "city": "Kassel", "country": "DE",
		"seller":     dealer("+49 555 1234567"),
		"photo_urls": []string{imgs.URL + "/banner1.jpg", imgs.URL + "/banner2.jpg", imgs.URL + "/q4-a.jpg"},
	})
	if !twin.CarCreated || twin.LinkedBy != nil {
		t.Fatalf("same-model car linked by stock banners only: %+v", twin)
	}

	// The ID.5 keeps exactly its own listing and status.
	car := c.car(id5.CarID)
	if len(car.Listings) != 1 || car.Status != "dropped" || len(car.MergedFrom) != 0 {
		t.Fatalf("ID.5 after the sweep: %d listings, status %s, merged_from %v", len(car.Listings), car.Status, car.MergedFrom)
	}

	// 4. The same ID.5 relisted on mobile.de (its own photos re-encoded): still recognised, but because it is
	// dropped it is proposed, not silently pulled in.
	relist := c.upsert(map[string]any{
		"url": "https://www.mobile.de/fahrzeuge/details.html?id=555555555", "price": 35900,
		"make": "VW", "model": "ID.5 Pro", "reg_date": "2024-06", "km": 25300, "city": "Kassel",
		"seller":     dealer("+49 555 1234567"),
		"photo_urls": []string{imgs.URL + "/id5-own1.jpg", imgs.URL + "/id5-own2.jpg", imgs.URL + "/id5-own3.jpg", imgs.URL + "/banner1.jpg"},
	})
	if !relist.CarCreated || relist.LinkedBy != nil {
		t.Fatalf("relist of a dropped car auto-linked: %+v", relist)
	}
	found := false
	for _, d := range relist.DuplicateCandidates {
		if (d.CarA == id5.CarID || d.CarB == id5.CarID) && strings.Contains(strings.Join(d.Reasons, ","), "3 matching photos") {
			found = true
		}
	}
	if !found {
		t.Fatalf("relist of the dropped ID.5 not proposed: %+v", relist.DuplicateCandidates)
	}
}

// A live car relisted elsewhere with its own photos is still linked automatically.
func TestPhotoDedupeTrueRelistLinks(t *testing.T) {
	c := newServer(t)
	img := func(seed int64) []byte { return jpegOf(t, pattern(seed, 1000, 667), 85) }
	reenc := func(seed int64) []byte { return jpegOf(t, degraded(pattern(seed, 1000, 667), seed), 60) }
	imgs := imageServer(t, map[string][]byte{"/1.jpg": reenc(1), "/2.jpg": reenc(2), "/3.jpg": reenc(3)})
	a := c.upsert(map[string]any{"url": "https://www.leboncoin.fr/ad/voitures/2876543299", "make": "Skoda", "model": "Enyaq 80",
		"reg_date": "2023-11", "km": 18700, "city": "Lille"})
	for _, s := range []int64{1, 2, 3, 4, 5, 6} {
		c.uploadPhoto(a.CarID, img(s), map[string]string{"source": "ad"}, 201)
	}
	b := c.upsert(map[string]any{"url": "https://www.lacentrale.fr/auto-occasion-annonce-87101234567.html", "make": "Skoda", "model": "Enyaq 80",
		"km": 18900, "photo_urls": []string{imgs.URL + "/1.jpg", imgs.URL + "/2.jpg", imgs.URL + "/3.jpg"}})
	if b.CarCreated || b.LinkedBy == nil || *b.LinkedBy != "photos" || b.CarID != a.CarID {
		t.Fatalf("true relist not linked by photos: %+v", b)
	}
	// Two existing cars that turn out to share photos are proposed, never auto-merged.
	d := c.upsert(map[string]any{"url": "https://www.leboncoin.fr/ad/voitures/2876543300", "make": "Skoda", "model": "Enyaq 80", "km": 18800})
	for _, s := range []int64{4, 5, 6} {
		c.uploadPhoto(d.CarID, img(s), map[string]string{"source": "ad"}, 201)
	}
	if got := c.car(d.CarID); got.ID != d.CarID {
		t.Fatalf("existing car auto-merged by photos into %d", got.ID)
	}
	var dups []api.DuplicateCandidate
	c.call("GET", fmt.Sprintf("/api/v1/duplicates?car=%d", d.CarID), nil, 200, &dups)
	if len(dups) != 1 || dups[0].Score < 0.9 {
		t.Fatalf("photo duplicate of an existing car not proposed: %+v", dups)
	}
}
