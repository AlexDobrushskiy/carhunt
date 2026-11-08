package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"io"
	"math/rand"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gen2brain/avif"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/store"
)

// --- harness ---------------------------------------------------------------------

type client struct {
	t     *testing.T
	base  string
	token string
	hdr   map[string]string
	dir   string // data dir of the in-process server
	st    *store.Store
}

// newServer runs the API with the EV worked-example profile (PT home; internal/profile/testdata/ev.yaml).
func newServer(t *testing.T) *client {
	t.Helper()
	return newServerWith(t, "../profile/testdata/ev.yaml")
}

// newServerWith runs the API with a profile file ("" = the neutral default profile).
func newServerWith(t *testing.T, profilePath string) *client {
	t.Helper()
	dir := t.TempDir()
	st, err := store.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	if profilePath != "" {
		p, err := profile.Load(profilePath)
		if err != nil {
			t.Fatal(err)
		}
		st.SetProfile(p)
	}
	srv := httptest.NewServer(NewHandler(st, map[string]string{"agents": "tok-agents", "web": "tok-web"}))
	t.Cleanup(srv.Close)
	return &client{t: t, base: srv.URL, token: "tok-agents", dir: dir, st: st}
}

func (c *client) as(author string) *client {
	cp := *c
	cp.hdr = map[string]string{"X-Author": author}
	return &cp
}

func (c *client) raw(method, path string, body io.Reader, contentType string) (int, []byte, http.Header) {
	c.t.Helper()
	req, err := http.NewRequest(method, c.base+path, body)
	if err != nil {
		c.t.Fatal(err)
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for k, v := range c.hdr {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		c.t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b, resp.Header
}

// call sends JSON, checks the status and decodes the response into out (if non-nil).
func (c *client) call(method, path string, body any, want int, out any) []byte {
	c.t.Helper()
	var r io.Reader
	ct := ""
	if body != nil {
		switch b := body.(type) {
		case string:
			r = strings.NewReader(b)
		default:
			j, err := json.Marshal(body)
			if err != nil {
				c.t.Fatal(err)
			}
			r = bytes.NewReader(j)
		}
		ct = "application/json"
	}
	status, resp, _ := c.raw(method, path, r, ct)
	if status != want {
		c.t.Fatalf("%s %s: status %d, want %d; body: %s", method, path, status, want, resp)
	}
	if out != nil {
		if err := json.Unmarshal(resp, out); err != nil {
			c.t.Fatalf("%s %s: decode %T: %v; body: %s", method, path, out, err, resp)
		}
	}
	return resp
}

func (c *client) upsert(in map[string]any) api.UpsertResult {
	c.t.Helper()
	var res api.UpsertResult
	c.call("POST", "/api/v1/listings/upsert", in, 200, &res)
	return res
}

func (c *client) car(ref any) api.CarDetail {
	c.t.Helper()
	var d api.CarDetail
	c.call("GET", fmt.Sprintf("/api/v1/cars/%v", ref), nil, 200, &d)
	return d
}

func (c *client) events(ref any) []api.Event {
	c.t.Helper()
	var evs []api.Event
	c.call("GET", fmt.Sprintf("/api/v1/cars/%v/events", ref), nil, 200, &evs)
	return evs
}

func (c *client) list(query string) api.CarList {
	c.t.Helper()
	var l api.CarList
	c.call("GET", "/api/v1/cars?"+query, nil, 200, &l)
	return l
}

func eventsOfType(evs []api.Event, typ string) []api.Event {
	var out []api.Event
	for _, e := range evs {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

func ids(l api.CarList) []int64 {
	out := []int64{}
	for _, c := range l.Cars {
		out = append(out, c.ID)
	}
	return out
}

func sameIDs(t *testing.T, label string, got []int64, want ...int64) {
	t.Helper()
	g, w := slices.Clone(got), slices.Clone(want)
	slices.Sort(g)
	slices.Sort(w)
	if !slices.Equal(g, w) {
		t.Fatalf("%s: got ids %v, want %v", label, got, want)
	}
}

func ptr[T any](v T) *T { return &v }

// --- test images ---------------------------------------------------------------------

// pattern draws an 8x8 grid of random colours; different seeds give unrelated perceptual hashes.
func pattern(seed int64, w, h int) image.Image {
	rng := rand.New(rand.NewSource(seed))
	var cells [8][8]color.RGBA
	for y := range 8 {
		for x := range 8 {
			cells[y][x] = color.RGBA{uint8(rng.Intn(256)), uint8(rng.Intn(256)), uint8(rng.Intn(256)), 255}
		}
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := range h {
		for x := range w {
			img.Set(x, y, cells[y*8/h][x*8/w])
		}
	}
	return img
}

// degraded crops a 2 % border and adds noise: a re-uploaded copy whose pHash differs by a few bits.
func degraded(img image.Image, seed int64) image.Image {
	rng := rand.New(rand.NewSource(seed))
	b := img.Bounds()
	dx, dy := b.Dx()*2/100, b.Dy()*2/100
	out := image.NewRGBA(image.Rect(0, 0, b.Dx()-2*dx, b.Dy()-2*dy))
	clamp := func(v uint32, n int) uint8 { return uint8(max(0, min(255, int(v>>8)+n))) }
	for y := range out.Bounds().Dy() {
		for x := range out.Bounds().Dx() {
			r, g, bl, _ := img.At(x+dx, y+dy).RGBA()
			n := rng.Intn(41) - 20
			out.Set(x, y, color.RGBA{clamp(r, n), clamp(g, n), clamp(bl, n), 255})
		}
	}
	return out
}

func jpegOf(t *testing.T, img image.Image, quality int) []byte {
	t.Helper()
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: quality}); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func imageServer(t *testing.T, files map[string][]byte) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, ok := files[r.URL.Path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "image/jpeg")
		w.Write(b)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func (c *client) uploadPhoto(car any, data []byte, fields map[string]string, want int) api.Photo {
	c.t.Helper()
	return c.uploadPhotoAs(car, "photo.jpg", data, fields, want)
}

// uploadPhotoAs sends the file with the given filename and a generic application/octet-stream part type.
func (c *client) uploadPhotoAs(car any, filename string, data []byte, fields map[string]string, want int) api.Photo {
	c.t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		c.t.Fatal(err)
	}
	fw.Write(data)
	for k, v := range fields {
		mw.WriteField(k, v)
	}
	mw.Close()
	status, body, _ := c.raw("POST", fmt.Sprintf("/api/v1/cars/%v/photos", car), &buf, mw.FormDataContentType())
	if status != want {
		c.t.Fatalf("upload photo: status %d, want %d: %s", status, want, body)
	}
	var p api.Photo
	if err := json.Unmarshal(body, &p); err != nil {
		c.t.Fatal(err)
	}
	return p
}

// --- tests ---------------------------------------------------------------------------

func TestAuthAndHealth(t *testing.T) {
	c := newServer(t)
	anon := *c
	anon.token = ""
	anon.call("GET", "/healthz", nil, 200, nil)
	var h api.Health
	anon.call("GET", "/api/v1/health", nil, 200, &h)
	if !h.OK || h.Version == "" {
		t.Fatalf("health = %+v", h)
	}
	spec := anon.call("GET", "/api/v1/openapi.yaml", nil, 200, nil)
	if !bytes.Contains(spec, []byte("openapi: 3.1.0")) {
		t.Fatal("openapi.yaml not served")
	}
	var e api.Error
	anon.call("GET", "/api/v1/cars", nil, 401, &e)
	if e.Error == "" {
		t.Fatal("401 without error message")
	}
	bad := *c
	bad.token = "nope"
	bad.call("GET", "/api/v1/stats", nil, 401, nil)
	c.call("GET", "/api/v1/stats", nil, 200, nil)
	c.call("GET", "/api/v1/cars/999", nil, 404, &e)
	c.call("GET", "/api/v1/cars/no-such-alias", nil, 404, nil)
	c.call("GET", "/api/v1/nope", nil, 404, nil)
	c.call("POST", "/api/v1/listings/upsert", "{not json", 400, nil)
	c.call("POST", "/api/v1/listings/upsert", map[string]any{"price": 1}, 422, nil)

	// Token name is the default author.
	res := c.upsert(map[string]any{"url": "https://www.standvirtual.com/carros/anuncio/x-IDsynMn01.html", "make": "MINI"})
	if evs := c.events(res.CarID); evs[0].Author != "agents" {
		t.Fatalf("default author = %q, want token name", evs[0].Author)
	}
}

func TestListingLifecycleDedupeMergeSplit(t *testing.T) {
	c := newServer(t)
	t0 := time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)
	svURL := "https://www.standvirtual.com/carros/anuncio/mini-countryman-e-favoured-IDsynMn01.html"
	base := map[string]any{
		"url": svURL + "?utm_source=x#photos", "title": "MINI Countryman E Favoured", "price": 34600,
		"seen_at": t0, "make": "MINI", "model": "Countryman E", "variant": "Favoured L", "reg_date": "2024-05",
		"km": 31200, "colour": "grey", "city": "Porto", "vin": "syn 11gc0 9r1234567",
		"seller":  map[string]any{"name": "Stand Norte", "type": "dealer", "contacts": []map[string]any{{"kind": "phone", "value": "555 000 111"}}},
		"options": map[string]any{"pano": map[string]any{"value": "yes", "source": "ad_text"}},
	}

	r1 := c.upsert(base)
	if !r1.CarCreated || !r1.ListingCreated || r1.LinkedBy != nil {
		t.Fatalf("first upsert = %+v", r1)
	}
	car := c.car(r1.CarID)
	if car.VIN == nil || *car.VIN != "SYN11GC09R1234567" || car.Country == nil || *car.Country != "PT" || *car.Market != "home" || *car.Year != 2024 {
		t.Fatalf("car specs = vin %v country %v market %v year %v", car.VIN, car.Country, car.Market, car.Year)
	}
	if car.Listings[0].URL != "https://www.standvirtual.com/carros/anuncio/mini-countryman-e-favoured-IDsynMn01.html" ||
		car.Listings[0].Site != "StandVirtual" || *car.Listings[0].SiteRef != "IDsynMn01" {
		t.Fatalf("listing = %+v", car.Listings[0])
	}
	if car.Seller == nil || car.Seller.Contacts[0].Value != "351555000111" {
		t.Fatalf("seller = %+v", car.Seller)
	}
	if len(car.Options) != 1 || car.Options[0].Value != "yes" || *car.Price != 34600 {
		t.Fatalf("options/price = %+v %v", car.Options, car.Price)
	}
	if evs := car.Events; len(evs) != 1 || evs[0].Type != "created" || !evs[0].At.Equal(t0) {
		t.Fatalf("events after create = %+v", evs)
	}
	if l := c.list(""); len(l.Cars) != 1 || l.Cars[0].Options["pano"] != "yes" || l.Cars[0].OptionSources["pano"] != "ad_text" {
		t.Fatalf("summary options = %+v sources %+v", l.Cars[0].Options, l.Cars[0].OptionSources)
	}

	// Same listing again, URL variant (no www, different slug, same ad id): nothing new.
	again := maps(base, map[string]any{"url": "https://standvirtual.com/carros/anuncio/other-slug-IDsynMn01.html", "seen_at": t0.Add(time.Hour)})
	r2 := c.upsert(again)
	if r2.ListingCreated || r2.CarCreated || r2.PriceChanged || r2.CarID != r1.CarID || r2.ListingID != r1.ListingID {
		t.Fatalf("re-upsert = %+v", r2)
	}
	if n := len(c.events(r1.CarID)); n != 1 {
		t.Fatalf("re-upsert wrote events: %d", n)
	}
	var stats api.Stats
	c.call("GET", "/api/v1/stats", nil, 200, &stats)
	if stats.Total != 1 || stats.Listings != 1 {
		t.Fatalf("stats after re-upsert = %+v", stats)
	}

	// Price drop observed later (import time kept).
	t1 := t0.Add(48 * time.Hour)
	r3 := c.upsert(maps(base, map[string]any{"price": 33900, "seen_at": t1}))
	if !r3.PriceChanged {
		t.Fatal("price change not reported")
	}
	r3b := c.upsert(maps(base, map[string]any{"price": 33900, "seen_at": t1.Add(time.Hour)}))
	if r3b.PriceChanged {
		t.Fatal("unchanged price reported as change")
	}
	var lst api.Listing
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r1.ListingID), nil, 200, &lst)
	if len(lst.PriceHistory) != 2 || lst.PriceHistory[0].Price != 34600 || !lst.PriceHistory[1].At.Equal(t1) || *lst.Price != 33900 {
		t.Fatalf("price history = %+v", lst.PriceHistory)
	}
	if !lst.LastSeenAt.Equal(t1.Add(time.Hour)) || !lst.FirstSeenAt.Equal(t0) {
		t.Fatalf("seen times = %v / %v", lst.FirstSeenAt, lst.LastSeenAt)
	}
	pc := eventsOfType(c.events(r1.CarID), "price_change")
	if len(pc) != 1 || pc[0].Summary != "price 34 600 → 33 900 € (StandVirtual)" || !pc[0].At.Equal(t1) {
		t.Fatalf("price_change events = %+v", pc)
	}
	var pcData struct{ From, To int }
	json.Unmarshal(pc[0].Data, &pcData)
	if pcData.From != 34600 || pcData.To != 33900 {
		t.Fatalf("price_change data = %s", pc[0].Data)
	}
	summary := c.list("")
	if *summary.Cars[0].Price != 33900 || *summary.Cars[0].PriceDrop != 700 {
		t.Fatalf("summary price/drop = %v/%v", summary.Cars[0].Price, summary.Cars[0].PriceDrop)
	}

	// Second site, same VIN → auto-linked to the same car.
	as := c.upsert(map[string]any{
		"url": "https://www.autoscout24.pt/anuncios/mini-countryman-3c1e4a5b-1111-2222-3333-444455556666", "price": 33500,
		"vin": "SYN11GC09R1234567", "make": "MINI", "model": "Countryman E", "seen_at": t1,
	})
	if as.CarCreated || as.LinkedBy == nil || *as.LinkedBy != "vin" || as.CarID != r1.CarID {
		t.Fatalf("VIN link = %+v", as)
	}
	if la := eventsOfType(c.events(r1.CarID), "listing_added"); len(la) != 1 || !strings.Contains(la[0].Summary, "AutoScout24") {
		t.Fatalf("listing_added = %+v", la)
	}
	car = c.car(r1.CarID)
	if len(car.Listings) != 2 || *car.Price != 33500 {
		t.Fatalf("after link: listings %d price %v", len(car.Listings), car.Price)
	}

	// Likely duplicate: same model/year/km±/city on OLX without VIN → new car + proposal.
	olx := c.upsert(map[string]any{
		"url": "https://www.olx.pt/d/anuncio/mini-countryman-electrico-IDJx7Yz.html", "price": 33000,
		"make": "MINI", "model": "Countryman E", "reg_date": "2024-06", "km": 31500, "city": "porto", "seen_at": t1,
	})
	if !olx.CarCreated || len(olx.DuplicateCandidates) != 1 {
		t.Fatalf("olx upsert = %+v", olx)
	}
	dup := olx.DuplicateCandidates[0]
	if dup.OtherCarID != r1.CarID || dup.Score <= 0 || dup.Status != "proposed" || len(dup.Reasons) == 0 {
		t.Fatalf("proposal = %+v", dup)
	}
	if len(eventsOfType(c.events(r1.CarID), "duplicate_proposed")) != 1 {
		t.Fatal("duplicate_proposed event missing on existing car")
	}
	var dups []api.DuplicateCandidate
	c.call("GET", "/api/v1/duplicates", nil, 200, &dups)
	if len(dups) != 1 {
		t.Fatalf("duplicates = %+v", dups)
	}
	if l := c.list("has_duplicates=true"); l.Total != 2 {
		t.Fatalf("has_duplicates total = %d", l.Total)
	}
	// Re-upsert the OLX ad: no duplicate proposal twice.
	c.upsert(map[string]any{"url": "https://olx.pt/d/anuncio/mini-countryman-electrico-IDJx7Yz.html", "price": 33000, "seen_at": t1})
	if n := len(eventsOfType(c.events(olx.CarID), "duplicate_proposed")); n != 1 {
		t.Fatalf("duplicate_proposed on re-upsert: %d", n)
	}

	// Merge the OLX car into the first one.
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/aliases", olx.CarID), map[string]any{"alias": "olx-mini"}, 200, nil)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", olx.CarID), map[string]any{"value": "maybe"}, 200, nil)
	var merged api.CarDetail
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/merge", r1.CarID), map[string]any{"from": []string{fmt.Sprint(olx.CarID)}}, 200, &merged)
	if len(merged.Listings) != 3 || !slices.Contains(merged.MergedFrom, olx.CarID) || !slices.Contains(merged.Aliases, "olx-mini") {
		t.Fatalf("merged = listings %d merged_from %v aliases %v", len(merged.Listings), merged.MergedFrom, merged.Aliases)
	}
	if merged.Verdict == nil || merged.Verdict.Value != "maybe" || *merged.Price != 33000 {
		t.Fatalf("merged verdict/price = %+v %v", merged.Verdict, merged.Price)
	}
	if got := c.car(olx.CarID); got.ID != r1.CarID {
		t.Fatalf("merged id resolves to %d", got.ID)
	}
	if got := c.car("olx-mini"); got.ID != r1.CarID {
		t.Fatalf("alias resolves to %d", got.ID)
	}
	c.call("GET", "/api/v1/duplicates?status=merged", nil, 200, &dups)
	if len(dups) != 1 {
		t.Fatalf("merged proposals = %+v", dups)
	}
	if l := c.list(""); l.Total != 1 {
		t.Fatalf("list after merge total = %d", l.Total)
	}
	nMerge := len(eventsOfType(c.events(r1.CarID), "merge"))
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/merge", r1.CarID), map[string]any{"from": []string{fmt.Sprint(olx.CarID)}}, 200, nil)
	if n := len(eventsOfType(c.events(r1.CarID), "merge")); n != nMerge || n != 1 {
		t.Fatalf("merge events = %d (was %d)", n, nMerge)
	}
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/merge", r1.CarID), map[string]any{"from": []string{}}, 422, nil)

	// Split the OLX listing back out.
	var split api.CarDetail
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/split", r1.CarID), map[string]any{"listing_ids": []int64{olx.ListingID}}, 200, &split)
	if split.ID == r1.CarID || len(split.Listings) != 1 || split.Listings[0].ID != olx.ListingID || split.VIN != nil || *split.Model != "Countryman E" {
		t.Fatalf("split car = %+v", split)
	}
	if len(eventsOfType(split.Events, "split")) != 1 || len(eventsOfType(c.events(r1.CarID), "split")) != 1 {
		t.Fatal("split events missing")
	}
	if got := c.car(r1.CarID); len(got.Listings) != 2 {
		t.Fatalf("original keeps %d listings", len(got.Listings))
	}
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/split", r1.CarID), map[string]any{"listing_ids": []int64{olx.ListingID}}, 422, nil)
	// A split pair is never re-proposed or re-merged.
	c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/x-IDJx7Yz.html", "km": 31500, "seen_at": t1.Add(time.Hour)})
	c.call("GET", fmt.Sprintf("/api/v1/duplicates?car=%d", split.ID), nil, 200, &dups)
	if len(dups) != 0 {
		t.Fatalf("split pair re-proposed: %+v", dups)
	}

	// Listing removed / relisted, idempotent.
	c.upsert(map[string]any{"url": svURL, "listing_status": "removed", "seen_at": t1.Add(2 * time.Hour)})
	c.upsert(map[string]any{"url": svURL, "listing_status": "removed", "seen_at": t1.Add(3 * time.Hour)})
	evs := c.events(r1.CarID)
	if n := len(eventsOfType(evs, "listing_removed")); n != 1 {
		t.Fatalf("listing_removed events = %d", n)
	}
	// Seen again without listing_status: an older seen_at (import replay) leaves it removed…
	if old := c.upsert(map[string]any{"url": svURL, "seen_at": t1.Add(time.Hour)}); old.Relisted {
		t.Fatal("old sighting reported relisted")
	}
	var cur api.Listing
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r1.ListingID), nil, 200, &cur)
	if cur.Status != "removed" || cur.RemovedAt == nil || !cur.RemovedAt.Equal(t1.Add(2*time.Hour)) {
		t.Fatalf("old sighting relisted: %+v", cur)
	}
	// …a later one relists it (once).
	if rr := c.upsert(map[string]any{"url": svURL, "seen_at": t1.Add(4 * time.Hour)}); !rr.Relisted {
		t.Fatal("relist not reported")
	}
	if rr := c.upsert(map[string]any{"url": svURL, "seen_at": t1.Add(5 * time.Hour)}); rr.Relisted {
		t.Fatal("already-live listing reported relisted")
	}
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r1.ListingID), nil, 200, &cur)
	rl := eventsOfType(c.events(r1.CarID), "listing_relisted")
	if cur.Status != "live" || cur.RemovedAt != nil || len(rl) != 1 || !rl[0].At.Equal(t1.Add(4*time.Hour)) {
		t.Fatalf("relist by sighting = %+v, events %+v", cur, rl)
	}
	var patched api.Listing
	c.call("PATCH", fmt.Sprintf("/api/v1/listings/%d", r1.ListingID), map[string]any{"status": "sold"}, 200, nil)
	c.call("PATCH", fmt.Sprintf("/api/v1/listings/%d", r1.ListingID), map[string]any{"status": "live"}, 200, &patched)
	if patched.Status != "live" || patched.RemovedAt != nil || len(eventsOfType(c.events(r1.CarID), "listing_relisted")) != 2 {
		t.Fatalf("relist via PATCH = %+v", patched)
	}
	var found []api.Listing
	c.call("GET", "/api/v1/listings?url="+svURL+"%3Futm_medium%3Dx", nil, 200, &found)
	if len(found) != 1 || found[0].ID != r1.ListingID {
		t.Fatalf("find by url = %+v", found)
	}
	c.call("GET", "/api/v1/listings?site=autoscout24", nil, 200, &found)
	if len(found) != 1 {
		t.Fatalf("find by site = %d", len(found))
	}
}

func maps(a map[string]any, b map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range a {
		out[k] = v
	}
	for k, v := range b {
		out[k] = v
	}
	return out
}

func TestPriceBackfillOutOfOrder(t *testing.T) {
	c := newServer(t)
	t0 := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	u := "https://www.custojusto.pt/porto/automoveis/tesla-model-3-44412345"
	c.upsert(map[string]any{"url": u, "price": 30000, "seen_at": t0, "make": "Tesla", "model": "Model 3"})
	c.upsert(map[string]any{"url": u, "price": 28000, "seen_at": t0.Add(72 * time.Hour)})
	// An older observation arrives late: history slot only, current price unchanged.
	r := c.upsert(map[string]any{"url": u, "price": 29000, "seen_at": t0.Add(24 * time.Hour)})
	var l api.Listing
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r.ListingID), nil, 200, &l)
	if *l.Price != 28000 || len(l.PriceHistory) != 3 || l.PriceHistory[1].Price != 29000 {
		t.Fatalf("backfill: price %v history %+v", *l.Price, l.PriceHistory)
	}
	if *l.SiteRef != "44412345" || l.Site != "CustoJusto" {
		t.Fatalf("custojusto ref = %v %s", l.SiteRef, l.Site)
	}
	// Replaying the whole import changes nothing.
	n := len(c.events(r.CarID))
	c.upsert(map[string]any{"url": u, "price": 30000, "seen_at": t0})
	c.upsert(map[string]any{"url": u, "price": 29000, "seen_at": t0.Add(24 * time.Hour)})
	c.upsert(map[string]any{"url": u, "price": 28000, "seen_at": t0.Add(72 * time.Hour)})
	if got := len(c.events(r.CarID)); got != n {
		t.Fatalf("replay wrote events: %d → %d", n, got)
	}
}

func TestMessages(t *testing.T) {
	c := newServer(t)
	priv := c.upsert(map[string]any{
		"url": "https://www.olx.pt/d/anuncio/vw-id3-IDaaa111.html", "make": "VW", "model": "ID.3",
		"seller": map[string]any{"name": "João", "type": "private", "contacts": []map[string]any{{"kind": "whatsapp", "value": "555 345 678"}}}, // national: PT home
	})
	at := time.Date(2026, 10, 20, 9, 30, 15, 0, time.UTC)
	msg := map[string]any{"counterpart": "+351 555345678", "channel": "whatsapp", "direction": "out", "text": "Olá, ainda está disponível?", "at": at}
	var m1, m2 api.Message
	c.call("POST", "/api/v1/messages", msg, 201, &m1)
	if m1.CarID != priv.CarID || *m1.Counterpart != "351555345678" || m1.SenderKind != "agent" || m1.Sender != "agents" || m1.Delivery != "sent" {
		t.Fatalf("message = %+v", m1)
	}
	// Same text within the same minute → same derived dedupe key.
	c.call("POST", "/api/v1/messages", maps(msg, map[string]any{"at": at.Add(20 * time.Second)}), 200, &m2)
	if m2.ID != m1.ID {
		t.Fatal("derived dedupe key did not dedupe")
	}
	// external_id idempotency.
	in := map[string]any{"counterpart": "+351555345678", "channel": "whatsapp", "direction": "in", "text": "Sim", "external_id": "wamid.1", "at": at.Add(time.Minute)}
	c.call("POST", "/api/v1/messages", in, 201, &m1)
	c.call("POST", "/api/v1/messages", maps(in, map[string]any{"text": "edited"}), 200, &m2)
	if m1.ID != m2.ID || m2.Text != "Sim" || m1.SenderKind != "seller" || m1.Delivery != "received" {
		t.Fatalf("external id dedupe: %+v / %+v", m1, m2)
	}
	// Explicit dedupe_key.
	dk := map[string]any{"car": fmt.Sprint(priv.CarID), "channel": "phone", "direction": "out", "text": "called, no answer", "dedupe_key": "call-1"}
	c.call("POST", "/api/v1/messages", dk, 201, &m1)
	c.call("POST", "/api/v1/messages", maps(dk, map[string]any{"at": at.Add(time.Hour)}), 200, &m2)
	if m1.ID != m2.ID {
		t.Fatal("dedupe_key did not dedupe")
	}

	// Dealer phone shared by two cars → ambiguous counterpart.
	dealer := map[string]any{"name": "Auto Lda", "type": "dealer", "contacts": []map[string]any{{"kind": "phone", "value": "00351 555 111 222"}}}
	d1 := c.upsert(map[string]any{"url": "https://www.standvirtual.com/carros/anuncio/a-IDd1.html", "make": "Kia", "model": "EV6", "seller": dealer})
	d2 := c.upsert(map[string]any{"url": "https://www.standvirtual.com/carros/anuncio/b-IDd2.html", "make": "Hyundai", "model": "Ioniq 5", "seller": dealer})
	if d1.CarID == d2.CarID {
		t.Fatal("dealer cars must not auto-link by phone")
	}
	if c.car(d1.CarID).Seller.ID != c.car(d2.CarID).Seller.ID {
		t.Fatal("dealer seller not shared")
	}
	var e api.Error
	amb := map[string]any{"counterpart": "555111222", "channel": "phone", "direction": "in", "text": "Bom dia"}
	c.call("POST", "/api/v1/messages", amb, 422, &e)
	if !strings.Contains(e.Error, "several") {
		t.Fatalf("ambiguous error = %q", e.Error)
	}
	c.call("POST", "/api/v1/messages", maps(amb, map[string]any{"listing_url": "https://standvirtual.com/carros/anuncio/zzz-IDd2.html"}), 201, &m1)
	if m1.CarID != d2.CarID {
		t.Fatalf("listing_url resolved to %d", m1.CarID)
	}
	c.call("POST", "/api/v1/messages", map[string]any{"counterpart": "999999999", "channel": "sms", "direction": "in", "text": "?"}, 422, nil)
	c.call("POST", "/api/v1/messages", map[string]any{"car": "1", "channel": "sms", "direction": "sideways", "text": "?"}, 422, nil)

	var log []api.Message
	c.call("GET", fmt.Sprintf("/api/v1/cars/%d/messages", priv.CarID), nil, 200, &log)
	if len(log) != 3 || log[0].At.After(log[1].At) {
		t.Fatalf("chat log = %+v", log)
	}
	sum := c.list("")
	for _, cs := range sum.Cars {
		if cs.ID == priv.CarID && (cs.MessageCount != 3 || *cs.LastMessageDirection != "out") {
			t.Fatalf("summary message fields = %d %v", cs.MessageCount, *cs.LastMessageDirection)
		}
	}
	var act []api.ActivityItem
	c.call("GET", "/api/v1/activity?since="+at.Add(30*time.Second).Format(time.RFC3339), nil, 200, &act)
	for _, a := range act {
		if !a.At.After(at.Add(30 * time.Second)) {
			t.Fatalf("activity item before since: %+v", a)
		}
	}
	kinds := map[string]bool{}
	for _, a := range act {
		kinds[a.Kind] = true
	}
	if !kinds["message"] || !kinds["event"] {
		t.Fatalf("activity kinds = %v", kinds)
	}
	c.call("GET", "/api/v1/activity?since=yesterday", nil, 400, nil)
}

// Use case: post a message resolved by counterpart, upload the photo to the car it landed on, link it in.
func TestPatchMessageLinksPhoto(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{
		"url": "https://www.olx.pt/d/anuncio/cupra-born-IDmsg1.html", "make": "Cupra", "model": "Born",
		"seller": map[string]any{"type": "private", "contacts": []map[string]any{{"kind": "whatsapp", "value": "555 000 222"}}},
	})
	other := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/x-IDmsg2.html", "make": "Fiat", "model": "600e"})
	in := map[string]any{"counterpart": "555000222", "channel": "whatsapp", "direction": "in", "text": "Fotos do interior",
		"external_id": "wamid.ph1", "attachments": []map[string]any{{"kind": "image", "mime": "image/jpeg"}}}
	var m api.Message
	c.call("POST", "/api/v1/messages", in, 201, &m)
	if m.CarID != r.CarID || len(m.Attachments) != 1 || m.Attachments[0].PhotoID != nil {
		t.Fatalf("posted = %+v", m)
	}
	ph := c.uploadPhoto(m.CarID, jpegOf(t, pattern(11, 640, 480), 85), map[string]string{"source": "seller", "source_ref": "wamid.ph1"}, 201)
	foreign := c.uploadPhoto(other.CarID, jpegOf(t, pattern(12, 640, 480), 85), nil, 201)

	path := fmt.Sprintf("/api/v1/messages/%d", m.ID)
	var p api.Message
	c.call("PATCH", path, map[string]any{"attachments": []map[string]any{{"kind": "image", "mime": "image/jpeg", "photo_id": ph.ID}}}, 200, &p)
	if len(p.Attachments) != 1 || p.Attachments[0].PhotoID == nil || *p.Attachments[0].PhotoID != ph.ID || p.Text != "Fotos do interior" {
		t.Fatalf("patched = %+v", p)
	}
	c.call("PATCH", path, map[string]any{"attachments": []map[string]any{{"kind": "image", "photo_id": foreign.ID}}}, 422, nil)
	c.call("PATCH", path, map[string]any{"delivery": "teleported"}, 422, nil)
	c.call("PATCH", path, map[string]any{"text": "", "attachments": []map[string]any{}}, 422, nil)
	c.call("PATCH", "/api/v1/messages/99999", map[string]any{"text": "x"}, 404, nil)

	// error set then cleared; text edit; idempotency key unchanged.
	c.call("PATCH", path, map[string]any{"delivery": "failed", "error": "timeout"}, 200, &p)
	if p.Delivery != "failed" || p.Error == nil || *p.Error != "timeout" {
		t.Fatalf("error set = %+v", p)
	}
	c.call("PATCH", path, map[string]any{"delivery": "received", "error": "", "text": "Fotos do interior (2)"}, 200, &p)
	if p.Error != nil || p.Delivery != "received" || p.Text != "Fotos do interior (2)" {
		t.Fatalf("error cleared = %+v", p)
	}
	var again api.Message
	c.call("POST", "/api/v1/messages", in, 200, &again)
	if again.ID != m.ID || *again.Attachments[0].PhotoID != ph.ID {
		t.Fatalf("re-post after patch = %+v", again)
	}
	var log []api.Message
	c.call("GET", fmt.Sprintf("/api/v1/cars/%d/messages", r.CarID), nil, 200, &log)
	if len(log) != 1 || *log[0].Attachments[0].PhotoID != ph.ID {
		t.Fatalf("chat log = %+v", log)
	}
	c.call("POST", "/api/v1/messages", map[string]any{"car": fmt.Sprint(r.CarID), "channel": "whatsapp", "direction": "out",
		"text": "ok", "attachments": []map[string]any{{"kind": "image", "photo_id": foreign.ID}}}, 422, nil)

	var h api.Health
	c.call("GET", "/api/v1/health", nil, 200, &h)
	if h.Version != api.Version {
		t.Fatalf("health version = %q, want %q", h.Version, api.Version)
	}
}

// Imports replay history: first fills stay silent and every write can carry its original time.
func TestImportTimesAndQuietFills(t *testing.T) {
	c := newServer(t)
	t0 := time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC)
	u := "https://www.standvirtual.com/carros/anuncio/ioniq-5-IDimp1.html"
	r := c.upsert(map[string]any{"url": u, "make": "Hyundai", "model": "Ioniq 5", "seen_at": t0})
	// Fill-if-empty from a later upsert: no spec_change (or option/fact) event.
	c.upsert(map[string]any{"url": u, "km": 41000, "colour": "white", "seen_at": t0.Add(time.Hour),
		"options": map[string]any{"heat_pump": map[string]any{"value": "yes"}}, "facts": map[string]any{"owners": map[string]any{"value": "1"}}})
	evs := c.events(r.CarID)
	if len(evs) != 1 || evs[0].Type != "created" {
		t.Fatalf("fills wrote events: %+v", evs)
	}
	if car := c.car(r.CarID); *car.Km != 41000 || len(car.Options) != 1 || len(car.Facts) != 1 {
		t.Fatalf("fills not stored: km %v options %d facts %d", car.Km, len(car.Options), len(car.Facts))
	}
	// Overwrite replacing a value is a change.
	c.upsert(map[string]any{"url": u, "km": 42500, "overwrite": true, "seen_at": t0.Add(2 * time.Hour)})
	if sc := eventsOfType(c.events(r.CarID), "spec_change"); len(sc) != 1 || sc[0].Summary != "spec: km 41 000 → 42 500" || !sc[0].At.Equal(t0.Add(2*time.Hour)) {
		t.Fatalf("overwrite spec_change = %+v", sc)
	}

	// `at` on every write becomes the event time and the stored timestamp.
	at := func(h int) time.Time { return t0.Add(time.Duration(24*h) * time.Hour) }
	car := fmt.Sprint(r.CarID)
	var o api.Option
	c.call("PUT", "/api/v1/cars/"+car+"/options/heat_pump", map[string]any{"value": "no", "source": "vin_decoder", "at": at(1)}, 200, &o)
	var f api.Fact
	c.call("PUT", "/api/v1/cars/"+car+"/facts/owners", map[string]any{"value": "2", "at": at(2)}, 200, &f)
	var v api.Verdict
	c.call("PUT", "/api/v1/cars/"+car+"/verdict", map[string]any{"value": "up", "author": "owner", "at": at(3)}, 200, &v)
	var n api.Note
	c.call("POST", "/api/v1/cars/"+car+"/notes", map[string]any{"text": "imported note", "at": at(4)}, 201, &n)
	var d api.CarDetail
	c.call("POST", "/api/v1/cars/"+car+"/status", map[string]any{"status": "contacted", "at": at(5)}, 200, &d)
	c.call("PATCH", "/api/v1/cars/"+car, map[string]any{"colour": "black", "status": "talking", "at": at(6)}, 200, &d)
	c.call("PATCH", "/api/v1/cars/"+car, map[string]any{"at": "last tuesday"}, 422, nil)
	if !o.UpdatedAt.Equal(at(1)) || !f.UpdatedAt.Equal(at(2)) || !v.UpdatedAt.Equal(at(3)) || !n.CreatedAt.Equal(at(4)) || !n.UpdatedAt.Equal(at(4)) {
		t.Fatalf("stored times: option %v fact %v verdict %v note %v", o.UpdatedAt, f.UpdatedAt, v.UpdatedAt, n.CreatedAt)
	}
	if !d.StatusChangedAt.Equal(at(6)) || !d.UpdatedAt.Equal(at(6)) {
		t.Fatalf("car times: status_changed_at %v updated_at %v", d.StatusChangedAt, d.UpdatedAt)
	}
	want := map[string][]time.Time{
		"option_change": {at(1)}, "fact_change": {at(2)}, "verdict": {at(3)}, "note": {at(4)},
		"status_change": {at(6), at(5)}, "spec_change": {at(6), t0.Add(2 * time.Hour)},
	}
	all := c.events(r.CarID)
	for typ, times := range want {
		got := eventsOfType(all, typ)
		if len(got) != len(times) {
			t.Fatalf("%s events = %+v", typ, got)
		}
		for i, tm := range times {
			if !got[i].At.Equal(tm) {
				t.Fatalf("%s[%d].at = %v, want %v", typ, i, got[i].At, tm)
			}
		}
	}
	// An older `at` never moves the car's updated_at backwards.
	c.call("PUT", "/api/v1/cars/"+car+"/verdict", map[string]any{"value": "maybe", "at": at(1)}, 200, nil)
	if got := c.car(car); !got.UpdatedAt.Equal(at(6)) {
		t.Fatalf("updated_at went backwards: %v", got.UpdatedAt)
	}
}

// A send logged live (dedupe_key, no external id) is reconciled when the importer later finds the provider id.
func TestMessageExternalIDReconcile(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/x-IDrec1.html", "make": "MG", "model": "4",
		"seller": map[string]any{"type": "private", "contacts": []map[string]any{{"kind": "whatsapp", "value": "955 555 444"}}}})
	car := fmt.Sprint(r.CarID)
	at := time.Date(2026, 10, 30, 18, 0, 0, 0, time.UTC)
	var live, rec, again api.Message
	c.as("ev-say-7").call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "whatsapp", "direction": "out",
		"text": "Bom dia, ainda disponível?", "at": at, "dedupe_key": "sends:1730311200"}, 201, &live)
	if live.ExternalID != nil || live.DedupeKey == nil || *live.DedupeKey != "sends:1730311200" || live.Sender != "ev-say-7" {
		t.Fatalf("live = %+v", live)
	}
	imp := map[string]any{"car": car, "channel": "whatsapp", "direction": "out", "text": "Bom dia, ainda disponível?",
		"at": at.Add(2 * time.Second), "dedupe_key": "sends:1730311200", "external_id": "3EB0ABC", "sender": "owner", "sender_kind": "owner"}
	c.as("import").call("POST", "/api/v1/messages", imp, 200, &rec)
	if rec.ID != live.ID || rec.ExternalID == nil || *rec.ExternalID != "3EB0ABC" || rec.Sender != "ev-say-7" || rec.SenderKind != "agent" || !rec.At.Equal(at) {
		t.Fatalf("reconciled = %+v (sender fields are filled only when empty/unknown)", rec)
	}
	c.call("POST", "/api/v1/messages", map[string]any{"channel": "whatsapp", "direction": "out", "text": "x", "external_id": "3EB0ABC", "car": car}, 200, &again)
	if again.ID != live.ID {
		t.Fatal("external id lookup after reconcile")
	}
	// A row that already has an external id is never re-keyed.
	c.call("POST", "/api/v1/messages", maps(imp, map[string]any{"external_id": "3EB0OTHER"}), 200, &again)
	if again.ID != live.ID || *again.ExternalID != "3EB0ABC" {
		t.Fatalf("re-keyed = %+v", again)
	}
	// The id is already used on that channel by another row → leave the matched row as is.
	var k3 api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "whatsapp", "direction": "out", "text": "segunda", "dedupe_key": "sends:2"}, 201, &k3)
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "other", "direction": "out", "text": "segunda", "dedupe_key": "sends:2", "external_id": "3EB0ABC"}, 200, &again)
	if again.ID != k3.ID || again.ExternalID != nil {
		t.Fatalf("conflicting attach = %+v", again)
	}
	var log []api.Message
	c.call("GET", "/api/v1/cars/"+car+"/messages", nil, 200, &log)
	if len(log) != 2 || *log[0].DedupeKey != "sends:1730311200" || !strings.HasPrefix(*log[1].DedupeKey, "sends:") {
		t.Fatalf("log = %+v", log)
	}
	var auto api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "sms", "direction": "in", "text": "ok"}, 201, &auto)
	if auto.DedupeKey == nil || !strings.HasPrefix(*auto.DedupeKey, "auto:") {
		t.Fatalf("derived key = %v", auto.DedupeKey)
	}
}

func photoFiles(t *testing.T, dir string) []string {
	t.Helper()
	files, err := filepath.Glob(filepath.Join(dir, "photos", "*", "*.jpg"))
	if err != nil {
		t.Fatal(err)
	}
	for i := range files {
		files[i] = filepath.Base(files[i])
	}
	return files
}

func TestDeleteCar(t *testing.T) {
	c := newServer(t)
	u := fmt.Sprintf("https://example.invalid/e2e-%d", time.Now().UnixNano())
	junk := c.upsert(map[string]any{"url": u, "make": "Junk", "model": "Ad", "price": 1000, "km": 1000, "reg_date": "2024-01", "city": "Porto",
		"seller": map[string]any{"type": "dealer", "name": "Junk Motors", "contacts": []map[string]any{{"kind": "phone", "value": "955 999 000"}}}})
	c.upsert(map[string]any{"url": u, "price": 900})
	keep := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/keep-IDkeep1.html", "make": "Junk", "model": "Ad", "km": 1100, "reg_date": "2024-01", "city": "Porto"})
	if len(keep.DuplicateCandidates) != 1 {
		t.Fatalf("setup: expected a duplicate proposal, got %+v", keep.DuplicateCandidates)
	}
	car := fmt.Sprint(junk.CarID)
	shared := jpegOf(t, pattern(31, 400, 300), 85)
	only := jpegOf(t, pattern(32, 400, 300), 85)
	ph := c.uploadPhoto(car, only, nil, 201)
	c.uploadPhoto(car, shared, nil, 201)
	keepPhoto := c.uploadPhoto(keep.CarID, shared, nil, 201)
	c.raw("GET", fmt.Sprintf("/api/v1/photos/%d?size=thumb", ph.ID), nil, "") // render a derived size
	c.call("PUT", "/api/v1/cars/"+car+"/options/pano", map[string]any{"value": "yes"}, 200, nil)
	c.call("PUT", "/api/v1/cars/"+car+"/facts/owners", map[string]any{"value": "1"}, 200, nil)
	c.call("PUT", "/api/v1/cars/"+car+"/verdict", map[string]any{"value": "down"}, 200, nil)
	c.call("POST", "/api/v1/cars/"+car+"/notes", map[string]any{"text": "junk"}, 201, nil)
	c.call("POST", "/api/v1/cars/"+car+"/aliases", map[string]any{"alias": "junk-1"}, 200, nil)
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "sms", "direction": "out", "text": "hi"}, 201, nil)
	before := len(photoFiles(t, c.dir))

	c.call("DELETE", "/api/v1/cars/"+car, nil, 400, nil)
	c.call("DELETE", "/api/v1/cars/"+car+"?confirm=abc", nil, 400, nil)
	c.call("DELETE", "/api/v1/cars/junk-1?confirm="+fmt.Sprint(keep.CarID), nil, 400, nil)
	c.call("DELETE", "/api/v1/cars/999?confirm=999", nil, 404, nil)
	c.call("DELETE", "/api/v1/cars/junk-1?confirm="+car, nil, 204, nil)

	c.call("GET", "/api/v1/cars/"+car, nil, 404, nil)
	c.call("GET", "/api/v1/cars/junk-1", nil, 404, nil)
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", junk.ListingID), nil, 404, nil)
	c.call("GET", fmt.Sprintf("/api/v1/photos/%d", ph.ID), nil, 404, nil)
	c.call("GET", fmt.Sprintf("/api/v1/photos/%d", keepPhoto.ID), nil, 200, nil) // same bytes on the other car survive
	var dups []api.DuplicateCandidate
	c.call("GET", fmt.Sprintf("/api/v1/duplicates?car=%d", keep.CarID), nil, 200, &dups)
	if len(dups) != 0 {
		t.Fatalf("duplicate rows left: %+v", dups)
	}
	var st api.Stats
	c.call("GET", "/api/v1/stats", nil, 200, &st)
	if st.Total != 1 || st.Listings != 1 || st.Messages != 0 || st.DuplicateProposals != 0 {
		t.Fatalf("stats after delete = %+v", st)
	}
	files := photoFiles(t, c.dir)
	if len(files) != before-2 || len(files) != 1 { // unique photo + its thumb gone, shared original kept
		t.Fatalf("photo files %d → %v", before, files)
	}
	for _, f := range files {
		if _, err := os.Stat(filepath.Join(c.dir, "photos", f[:2], f)); err != nil {
			t.Fatal(err)
		}
	}
	// The seller is kept; the URL is free again and makes a fresh car.
	again := c.upsert(map[string]any{"url": u, "make": "Junk"})
	if !again.CarCreated || again.CarID == junk.CarID {
		t.Fatalf("re-upsert after delete = %+v", again)
	}

	// A car that tombstones point at is refused.
	other := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/m-IDkeep2.html", "make": "X"})
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/merge", keep.CarID), map[string]any{"from": []string{fmt.Sprint(other.CarID)}}, 200, nil)
	var e api.Error
	c.call("DELETE", fmt.Sprintf("/api/v1/cars/%d?confirm=%d", keep.CarID, keep.CarID), nil, 409, &e)
	if !strings.Contains(e.Error, fmt.Sprint(other.CarID)) {
		t.Fatalf("409 message = %q", e.Error)
	}
	c.call("GET", fmt.Sprintf("/api/v1/cars/%d", keep.CarID), nil, 200, nil)
}

func TestNotesCRUD(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.mobile.de/fahrzeuge/details.html?id=412345678&lang=en&utm_campaign=x", "make": "BMW", "model": "iX1"})
	var l api.Listing
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r.ListingID), nil, 200, &l)
	if *l.SiteRef != "412345678" || l.Site != "mobile.de" || strings.Contains(l.URL, "utm") {
		t.Fatalf("mobile.de listing = %+v", l)
	}
	if car := c.car(r.CarID); *car.Market != "abroad" {
		t.Fatalf("mobile.de market = %v", car.Market)
	}
	var n1, n2 api.Note
	c.as("owner").call("POST", fmt.Sprintf("/api/v1/cars/%d/notes", r.CarID), map[string]any{"text": "Ask about the heat pump"}, 201, &n1)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/notes", r.CarID), map[string]any{"text": "Seller replies slowly", "author": "import-wa"}, 201, &n2)
	if n1.Author != "owner" || n1.AuthorKind != "owner" || n2.AuthorKind != "import" {
		t.Fatalf("author kinds = %q %q", n1.AuthorKind, n2.AuthorKind)
	}
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/notes", r.CarID), map[string]any{"text": "   "}, 422, nil)
	var notes []api.Note
	c.call("GET", fmt.Sprintf("/api/v1/cars/%d/notes", r.CarID), nil, 200, &notes)
	if len(notes) != 2 || notes[0].ID != n2.ID {
		t.Fatalf("notes newest first = %+v", notes)
	}
	var p api.Note
	c.call("PATCH", fmt.Sprintf("/api/v1/notes/%d", n1.ID), map[string]any{"pinned": true, "text": "Ask about the heat pump option"}, 200, &p)
	if !p.Pinned || p.Text != "Ask about the heat pump option" {
		t.Fatalf("patched note = %+v", p)
	}
	if car := c.car(r.CarID); car.Notes[0].ID != n1.ID {
		t.Fatal("detail notes not pinned-first")
	}
	if l := c.list("q=heat+pump"); l.Total != 1 {
		t.Fatalf("q over notes total = %d", l.Total)
	}
	c.call("DELETE", fmt.Sprintf("/api/v1/notes/%d", n1.ID), nil, 204, nil)
	c.call("DELETE", fmt.Sprintf("/api/v1/notes/%d", n1.ID), nil, 404, nil)
	c.call("PATCH", fmt.Sprintf("/api/v1/notes/%d", n1.ID), map[string]any{"pinned": false}, 404, nil)
	c.call("GET", fmt.Sprintf("/api/v1/cars/%d/notes", r.CarID), nil, 200, &notes)
	if len(notes) != 1 {
		t.Fatalf("notes after delete = %d", len(notes))
	}
}

func TestVerdict(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.lacentrale.fr/auto-occasion-annonce-69112345678.html", "make": "Renault", "model": "Megane E-Tech"})
	owner := c.as("owner")
	var v api.Verdict
	owner.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), map[string]any{"value": "up"}, 200, &v)
	if v.Value != "up" || v.Author != "owner" {
		t.Fatalf("verdict = %+v", v)
	}
	owner.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), map[string]any{"value": "up"}, 200, nil)
	owner.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), map[string]any{"value": "down", "note": "too far"}, 200, &v)
	if v.Note == nil || *v.Note != "too far" {
		t.Fatalf("verdict note = %+v", v)
	}
	vs := eventsOfType(c.events(r.CarID), "verdict")
	if len(vs) != 2 || !strings.Contains(vs[0].Summary, "down") {
		t.Fatalf("verdict events = %+v", vs)
	}
	if l := c.list("verdict=down"); l.Total != 1 {
		t.Fatal("verdict filter down")
	}
	owner.call("PUT", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), map[string]any{"value": "meh"}, 422, nil)
	owner.call("DELETE", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), nil, 204, nil)
	owner.call("DELETE", fmt.Sprintf("/api/v1/cars/%d/verdict", r.CarID), nil, 204, nil)
	if n := len(eventsOfType(c.events(r.CarID), "verdict")); n != 3 {
		t.Fatalf("verdict events after clear = %d", n)
	}
	if car := c.car(r.CarID); car.Verdict != nil {
		t.Fatal("verdict not cleared")
	}
	if l := c.list("verdict=none"); l.Total != 1 {
		t.Fatal("verdict filter none")
	}
	var st api.Stats
	c.call("GET", "/api/v1/stats", nil, 200, &st)
	if st.ByVerdict["none"] != 1 || st.ByStatus["new"] != 1 {
		t.Fatalf("stats = %+v", st)
	}
}

func TestOptionsAndFilters(t *testing.T) {
	c := newServer(t)
	mk := func(u, model string) int64 {
		return c.upsert(map[string]any{"url": u, "make": "Skoda", "model": model}).CarID
	}
	a := mk("https://www.standvirtual.com/carros/anuncio/a-IDopt1.html", "Enyaq")
	b := mk("https://www.standvirtual.com/carros/anuncio/b-IDopt2.html", "Elroq")
	cc := mk("https://www.standvirtual.com/carros/anuncio/c-IDopt3.html", "Enyaq Coupe")
	put := func(car int64, key, val string) api.Option {
		var o api.Option
		c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/options/%s", car, key), map[string]any{"value": val, "source": "ad_text", "source_ref": "photo 3"}, 200, &o)
		return o
	}
	o := put(a, "pano", "yes")
	if o.Value != "yes" || *o.SourceRef != "photo 3" || o.Author != "agents" {
		t.Fatalf("option = %+v", o)
	}
	put(a, "pano", "yes") // idempotent
	put(b, "pano", "no")
	put(a, "power_tailgate", "yes")
	put(cc, "power_tailgate", "no")
	// First fills are silent; only replacing an existing value is a change.
	if n := len(eventsOfType(c.events(a), "option_change")); n != 0 {
		t.Fatalf("first-fill option_change events on a = %d", n)
	}
	put(cc, "power_tailgate", "yes")
	put(cc, "power_tailgate", "no")
	if oc := eventsOfType(c.events(cc), "option_change"); len(oc) != 2 || oc[0].Summary != "option power_tailgate: yes → no (ad_text)" {
		t.Fatalf("option_change on change = %+v", oc)
	}
	cases := map[string][]int64{
		"option=pano:yes":            {a},
		"option=pano:no":             {b},
		"option=pano:unknown":        {cc},
		"option=pano:yes_or_unknown": {a, cc},
		"option=pano:yes_or_unknown&option=power_tailgate:yes": {a},
		"option=heat_pump:unknown":                             {a, b, cc},
		"model=enyaq":                                          {a, cc},
		"make=skoda&model=coupe":                               {cc},
	}
	for q, want := range cases {
		sameIDs(t, q, ids(c.list(q)), want...)
	}
	c.call("GET", "/api/v1/cars?option=pano", nil, 400, nil)
	c.call("GET", "/api/v1/cars?option=pano:maybe", nil, 400, nil)
	c.call("GET", "/api/v1/cars?status=bogus", nil, 400, nil)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/options/pano", a), map[string]any{"value": "maybe"}, 422, nil)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/options/pano", a), map[string]any{"value": "yes", "source": "rumour"}, 422, nil)

	// Delete → unknown again.
	c.call("DELETE", fmt.Sprintf("/api/v1/cars/%d/options/pano", a), nil, 204, nil)
	sameIDs(t, "after delete", ids(c.list("option=pano:unknown")), a, cc)
	if l := c.list("option=pano:yes"); l.Total != 0 {
		t.Fatal("deleted option still matches")
	}

	var f api.Fact
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/facts/warranty", a), map[string]any{"value": "until 2027-05", "source": "seller_said"}, 200, &f)
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/facts/warranty", a), map[string]any{"value": "until 2027-05", "source": "seller_said"}, 200, nil)
	if f.Value != "until 2027-05" || len(eventsOfType(c.events(a), "fact_change")) != 0 {
		t.Fatalf("fact first fill = %+v", f)
	}
	c.call("PUT", fmt.Sprintf("/api/v1/cars/%d/facts/warranty", a), map[string]any{"value": "until 2028-05", "source": "vin_decoder"}, 200, nil)
	if fc := eventsOfType(c.events(a), "fact_change"); len(fc) != 1 || !strings.Contains(fc[0].Summary, "until 2027-05 → until 2028-05") {
		t.Fatalf("fact change = %+v", fc)
	}
	c.call("DELETE", fmt.Sprintf("/api/v1/cars/%d/facts/warranty", a), nil, 204, nil)
	if car := c.car(a); len(car.Facts) != 0 {
		t.Fatal("fact not deleted")
	}
}

func TestPatchCarNullClearingAndStatus(t *testing.T) {
	c := newServer(t)
	var car api.CarDetail
	c.call("POST", "/api/v1/cars", map[string]any{
		"make": "Peugeot", "model": "e-3008", "km": 12000, "colour": "blue", "summary": "nice spec",
		"slug": "pt-e3008-porto", "red_flags": []string{"paint"},
	}, 201, &car)
	if car.Slug == nil || *car.Slug != "pt-e3008-porto" || !slices.Contains(car.Aliases, "pt-e3008-porto") {
		t.Fatalf("created = %+v", car)
	}
	var p api.CarDetail
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", `{"km": null, "summary": null, "colour": "grey", "red_flags": null, "needs_owner": true, "needs_owner_reason": "price ok?"}`, 200, &p)
	if p.Km != nil || p.Summary != nil || *p.Colour != "grey" || len(p.RedFlags) != 0 || !p.NeedsOwner {
		t.Fatalf("patched = km %v summary %v colour %v flags %v", p.Km, p.Summary, p.Colour, p.RedFlags)
	}
	sc := eventsOfType(p.Events, "spec_change")
	if len(sc) != 1 || !strings.Contains(sc[0].Summary, "km 12 000 → —") || !strings.Contains(sc[0].Summary, "colour blue → grey") {
		t.Fatalf("spec_change = %+v", sc)
	}
	// Same patch again: no new spec_change.
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", `{"km": null, "colour": "grey"}`, 200, &p)
	if n := len(eventsOfType(p.Events, "spec_change")); n != 1 {
		t.Fatalf("idempotent patch wrote spec_change: %d", n)
	}
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", `{"kmh": 5}`, 422, nil)
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", `{"drive": "4x4"}`, 422, nil)
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", `{"status": "talking", "status_reason": "replied on WA"}`, 200, &p)
	st := eventsOfType(p.Events, "status_change")
	if p.Status != "talking" || len(st) != 1 || !strings.Contains(st[0].Summary, "new → talking (replied on WA)") || p.StatusChangedAt == nil {
		t.Fatalf("status change = %s %+v", p.Status, st)
	}
	c.call("POST", "/api/v1/cars/pt-e3008-porto/status", map[string]any{"status": "talking"}, 200, &p)
	c.call("POST", "/api/v1/cars/pt-e3008-porto/status", map[string]any{"status": "bogus"}, 422, nil)
	if n := len(eventsOfType(p.Events, "status_change")); n != 1 {
		t.Fatalf("no-op status wrote event: %d", n)
	}
	if l := c.list("needs_owner=true"); l.Total != 1 {
		t.Fatal("needs_owner filter")
	}

	// Alias collision → 409; numeric alias → 422.
	var other api.CarDetail
	c.call("POST", "/api/v1/cars", map[string]any{"make": "Peugeot", "model": "e-208", "plate": "aa-11-bb"}, 201, &other)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/aliases", other.ID), map[string]any{"alias": "PT-E3008-PORTO"}, 409, nil)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/aliases", other.ID), map[string]any{"alias": "42"}, 422, nil)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/aliases", other.ID), map[string]any{"alias": "C2"}, 200, nil)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/aliases", other.ID), map[string]any{"alias": "c2"}, 200, nil)
	if got := c.car("C2"); got.ID != other.ID {
		t.Fatal("alias lookup")
	}

	// Setting a plate that matches another car auto-merges into the older car.
	var live api.CarDetail
	c.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", other.ID), map[string]any{"km": 5000}, 200, nil)
	c.call("PATCH", "/api/v1/cars/pt-e3008-porto", map[string]any{"plate": "AA11BB"}, 200, &live)
	older := min(car.ID, other.ID)
	if live.ID != older || len(eventsOfType(live.Events, "merge")) != 1 {
		t.Fatalf("auto-merge by plate: live %d (want %d), events %+v", live.ID, older, eventsOfType(live.Events, "merge"))
	}
	if l := c.list(""); l.Total != 1 {
		t.Fatalf("total after auto-merge = %d", l.Total)
	}
}

func TestPhotos(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.leboncoin.fr/ad/voitures/2876543210", "make": "Tesla", "model": "Model Y", "km": 40000})
	var l api.Listing
	c.call("GET", fmt.Sprintf("/api/v1/listings/%d", r.ListingID), nil, 200, &l)
	if *l.SiteRef != "2876543210" {
		t.Fatalf("leboncoin ref = %v", *l.SiteRef)
	}
	img1 := jpegOf(t, pattern(1, 1200, 800), 90)
	img2 := jpegOf(t, pattern(2, 1200, 800), 90)
	img3 := jpegOf(t, pattern(3, 1200, 800), 90)
	p1 := c.uploadPhoto(r.CarID, img1, map[string]string{"caption": "front", "source": "ad", "source_ref": "1", "listing_id": fmt.Sprint(r.ListingID)}, 201)
	if p1.Width != 1200 || p1.Height != 800 || len(p1.PHash) != 16 || *p1.Caption != "front" || p1.URL != fmt.Sprintf("/api/v1/photos/%d", p1.ID) {
		t.Fatalf("photo = %+v", p1)
	}
	again := c.uploadPhoto(r.CarID, img1, nil, 200)
	if again.ID != p1.ID {
		t.Fatal("same bytes created a second photo")
	}
	p2 := c.uploadPhoto(r.CarID, img2, map[string]string{"source": "ad"}, 201)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), nil, 400, nil)
	c.uploadPhoto(r.CarID, []byte("not an image"), nil, 422)
	// Decoded by content, not by name/part type: WhatsApp .jfif (JPEG) and a PNG named .jpg both work.
	jf := c.uploadPhotoAs(r.CarID, "IMG-20261020-WA0007.jfif", jpegOf(t, pattern(21, 300, 200), 80), nil, 201)
	var pngBuf bytes.Buffer
	png.Encode(&pngBuf, pattern(22, 300, 200))
	pn := c.uploadPhotoAs(r.CarID, "really-a-png.jpg", pngBuf.Bytes(), nil, 201)
	if jf.Width != 300 || pn.Width != 300 {
		t.Fatalf("content-sniffed uploads = %+v / %+v", jf, pn)
	}
	c.call("DELETE", fmt.Sprintf("/api/v1/photos/%d", jf.ID), nil, 204, nil)
	c.call("DELETE", fmt.Sprintf("/api/v1/photos/%d", pn.ID), nil, 204, nil)

	// Serving: thumb ≈ 400 px wide, ETag, 304.
	status, body, hdr := c.raw("GET", fmt.Sprintf("/api/v1/photos/%d?size=thumb", p1.ID), nil, "")
	if status != 200 || hdr.Get("Content-Type") != "image/jpeg" || !strings.Contains(hdr.Get("Cache-Control"), "immutable") {
		t.Fatalf("thumb: %d %v", status, hdr)
	}
	cfg, err := jpeg.DecodeConfig(bytes.NewReader(body))
	if err != nil || cfg.Width != 400 || cfg.Height != 267 {
		t.Fatalf("thumb size = %dx%d (%v)", cfg.Width, cfg.Height, err)
	}
	status, body, _ = c.raw("GET", fmt.Sprintf("/api/v1/photos/%d", p1.ID), nil, "")
	if cfg, _ = jpeg.DecodeConfig(bytes.NewReader(body)); status != 200 || cfg.Width != 1200 {
		t.Fatalf("full = %d %d", status, cfg.Width)
	}
	cond := c.as("x")
	cond.hdr["If-None-Match"] = hdr.Get("ETag")
	if status, _, _ = cond.raw("GET", fmt.Sprintf("/api/v1/photos/%d?size=thumb", p1.ID), nil, ""); status != 304 {
		t.Fatalf("conditional GET = %d", status)
	}
	anon := *c
	anon.token = ""
	if status, _, _ = anon.raw("GET", fmt.Sprintf("/api/v1/photos/%d?token=tok-web", p1.ID), nil, ""); status != 401 {
		t.Fatalf("photo via ?token= = %d, want 401 (tokens never in URLs)", status)
	}
	c.call("GET", fmt.Sprintf("/api/v1/photos/%d?size=huge", p1.ID), nil, 400, nil)

	// Cover + list summary.
	c.call("PATCH", fmt.Sprintf("/api/v1/photos/%d", p2.ID), map[string]any{"cover": true}, 200, nil)
	sum := c.list("")
	if *sum.Cars[0].CoverPhotoID != p2.ID || sum.Cars[0].PhotoCount != 2 {
		t.Fatalf("cover/photo_count = %v %d", sum.Cars[0].CoverPhotoID, sum.Cars[0].PhotoCount)
	}

	// JSON {url} upload, fetched by the server.
	imgs := imageServer(t, map[string][]byte{
		"/3.jpg": img3,
		// Re-encoded copies: different bytes, same picture.
		"/1b.jpg": jpegOf(t, degraded(pattern(1, 1000, 667), 1), 60),
		"/2b.jpg": jpegOf(t, degraded(pattern(2, 1000, 667), 2), 60),
		"/9.jpg":  jpegOf(t, pattern(9, 800, 600), 80),
	})
	var p3 api.Photo
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), map[string]any{"url": imgs.URL + "/3.jpg", "caption": "rear"}, 201, &p3)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), map[string]any{"url": imgs.URL + "/3.jpg"}, 200, nil)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), map[string]any{"url": imgs.URL + "/missing.jpg"}, 422, nil)

	// A new listing elsewhere with two re-encoded copies of this car's photos → same car (≥2 pHash matches).
	dup := c.upsert(map[string]any{
		"url": "https://www.coches.net/tesla-model-y-long-range-electrico-2022-en-madrid-58123456-covo.aspx", "make": "Tesla", "model": "Model Y",
		"km": 40500, "photo_urls": []string{imgs.URL + "/1b.jpg", imgs.URL + "/2b.jpg", imgs.URL + "/404.jpg"},
	})
	if dup.CarCreated || dup.LinkedBy == nil || *dup.LinkedBy != "photos" || dup.CarID != r.CarID {
		t.Fatalf("photo dedupe = %+v", dup)
	}
	if len(dup.PhotoErrors) != 1 || !strings.Contains(dup.PhotoErrors[0], "404") {
		t.Fatalf("photo errors = %v", dup.PhotoErrors)
	}
	car := c.car(r.CarID)
	if len(car.Photos) != 5 || len(car.Listings) != 2 {
		t.Fatalf("after photo link: %d photos, %d listings", len(car.Photos), len(car.Listings))
	}
	// One matching photo only → proposal, not a link.
	one := c.upsert(map[string]any{
		"url": "https://www.olx.pt/d/anuncio/tesla-y-IDphoto1.html", "make": "Tesla", "model": "Model Y",
		"photo_urls": []string{imgs.URL + "/3.jpg", imgs.URL + "/9.jpg"},
	})
	if !one.CarCreated || len(one.DuplicateCandidates) != 1 || !slices.Contains(one.DuplicateCandidates[0].Reasons, "1 matching photo") {
		t.Fatalf("1-photo proposal = %+v", one)
	}
	var rej api.DuplicateCandidate
	c.call("POST", fmt.Sprintf("/api/v1/duplicates/%d/reject", one.DuplicateCandidates[0].ID), nil, 200, &rej)
	if rej.Status != "rejected" {
		t.Fatal("reject")
	}
	// Uploading the second matching photo now would be certain, but the pair was rejected: no merge.
	c.uploadPhoto(one.CarID, img2, nil, 201)
	if got := c.car(one.CarID); got.ID != one.CarID {
		t.Fatal("rejected pair was auto-merged")
	}

	c.call("DELETE", fmt.Sprintf("/api/v1/photos/%d", p3.ID), nil, 204, nil)
	c.call("GET", fmt.Sprintf("/api/v1/photos/%d", p3.ID), nil, 404, nil)
}

// Subito/Milanuncios CDNs negotiate (or fix) AVIF; the server must not ask for it and must decode it anyway.
func TestPhotoFormatsAVIFAndHEIC(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.subito.it/auto/tesla-model-3-milano-612345678.htm", "make": "Tesla", "model": "Model 3"})
	jpg := jpegOf(t, pattern(51, 600, 400), 85)
	var avifBuf bytes.Buffer
	if err := avif.Encode(&avifBuf, pattern(52, 600, 400), avif.Options{Quality: 70, Speed: 10}); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var accepts, agents []string
	cdn := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		accepts, agents = append(accepts, r.Header.Get("Accept")), append(agents, r.Header.Get("User-Agent"))
		mu.Unlock()
		switch {
		case r.URL.Path == "/fixed-avif" || strings.Contains(r.Header.Get("Accept"), "image/avif"):
			w.Header().Set("Content-Type", "image/avif")
			w.Write(avifBuf.Bytes())
		default:
			w.Header().Set("Content-Type", "image/jpeg")
			w.Write(jpg)
		}
	}))
	defer cdn.Close()

	var p api.Photo
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), map[string]any{"url": cdn.URL + "/negotiated?rule=gallery-desktop-2x-auto"}, 201, &p)
	if p.Width != 600 || p.Height != 400 {
		t.Fatalf("negotiated photo = %+v", p)
	}
	if strings.Contains(accepts[0], "avif") || !strings.HasPrefix(accepts[0], "image/jpeg") || !strings.HasPrefix(agents[0], "Mozilla/5.0") {
		t.Fatalf("fetch headers: Accept %q, User-Agent %q", accepts[0], agents[0])
	}
	// A CDN that serves AVIF regardless of Accept (Subito's cached -auto rules): decoded anyway.
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), map[string]any{"url": cdn.URL + "/fixed-avif"}, 201, &p)
	if p.Width != 600 {
		t.Fatalf("avif photo = %+v", p)
	}
	status, body, _ := c.raw("GET", fmt.Sprintf("/api/v1/photos/%d", p.ID), nil, "")
	if _, format, err := image.DecodeConfig(bytes.NewReader(body)); status != 200 || format != "jpeg" || err != nil {
		t.Fatalf("served avif as %s (%d, %v)", format, status, err)
	}
	// Same through upsert photo_urls.
	up := c.upsert(map[string]any{"url": "https://www.milanuncios.com/coches-de-segunda-mano/tesla-model-3-512345678.htm", "car": fmt.Sprint(r.CarID),
		"photo_urls": []string{cdn.URL + "/fixed-avif", cdn.URL + "/other.jpg"}})
	if len(up.PhotoErrors) != 0 {
		t.Fatalf("photo_errors = %v", up.PhotoErrors)
	}
	// iPhone HEIC via multipart, named .HEIC.
	heic, err := os.ReadFile("../imaging/testdata/blocks.heic")
	if err != nil {
		t.Fatal(err)
	}
	hp := c.uploadPhotoAs(r.CarID, "IMG_4021.HEIC", heic, map[string]string{"source": "inspection"}, 201)
	if hp.Width != 400 || hp.Height != 300 {
		t.Fatalf("heic photo = %+v", hp)
	}
	// Undecodable AVIF: named 422.
	var e api.Error
	mb, ct := multipartBody(t, "x.avif", avifBuf.Bytes()[:40])
	status, body, _ = c.raw("POST", fmt.Sprintf("/api/v1/cars/%d/photos", r.CarID), mb, ct)
	json.Unmarshal(body, &e)
	if status != 422 || !strings.Contains(e.Error, "AVIF image could not be decoded") {
		t.Fatalf("broken avif = %d %q", status, e.Error)
	}
}

func multipartBody(t *testing.T, filename string, data []byte) (io.Reader, string) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, err := mw.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	fw.Write(data)
	mw.Close()
	return &buf, mw.FormDataContentType()
}

func TestListSortAndFilter(t *testing.T) {
	c := newServer(t)
	type spec struct {
		url     string
		price   any
		km      int
		reg     string
		country string
		k2b     any
	}
	specs := []spec{
		{"https://www.standvirtual.com/carros/anuncio/a-IDs1.html", 30000, 50000, "2022-03", "PT", 10},
		{"https://www.standvirtual.com/carros/anuncio/b-IDs2.html", 25000, 20000, "2023-01", "PT", 300},
		{"https://www.mobile.de/fahrzeuge/details.html?id=9001", 28000, 35000, "2023-07", "DE", 2100},
		{"https://www.standvirtual.com/carros/anuncio/d-IDs4.html", nil, 10000, "2024-02", "PT", nil},
	}
	var carIDs []int64
	for i, s := range specs {
		in := map[string]any{"url": s.url, "make": "Kia", "model": fmt.Sprintf("Model %c", 'D'-i), "km": s.km, "reg_date": s.reg, "country": s.country}
		if s.price != nil {
			in["price"] = s.price
		}
		if s.k2b != nil {
			in["distance_km"] = s.k2b
		}
		carIDs = append(carIDs, c.upsert(in).CarID)
	}
	a, b, d, e := carIDs[0], carIDs[1], carIDs[2], carIDs[3]
	order := func(q string, want ...int64) {
		t.Helper()
		if got := ids(c.list(q)); !slices.Equal(got, want) {
			t.Fatalf("%s: got %v, want %v", q, got, want)
		}
	}
	order("sort=price", b, d, a, e) // asc, missing last
	order("sort=price&order=desc", a, d, b, e)
	order("sort=year", e, d, b, a) // desc by default, months break ties
	order("sort=km", e, b, d, a)
	order("sort=distance_km", a, b, d, e)
	order("sort=model", e, d, b, a)
	order("sort=created", e, d, b, a)
	order("price_max=28000&sort=price", b, d)
	order("price_min=26000&sort=price", d, a)
	order("year_min=2023&year_max=2023&sort=km", b, d)
	order("km_max=20000&sort=km", e, b)
	order("country=DE", d)
	order("country=pt&country=de&distance_km_max=300&sort=distance_km", a, b)
	order("market=abroad", d)
	order("market=home&sort=km", e, b, a)
	c.call("GET", "/api/v1/cars?market=PT", nil, 400, nil)
	l := c.list("sort=price&limit=2&offset=1")
	if l.Total != 4 || !slices.Equal(ids(l), []int64{d, a}) {
		t.Fatalf("paging: total %d ids %v", l.Total, ids(l))
	}
	c.call("GET", "/api/v1/cars?sort=colour", nil, 400, nil)
	c.call("GET", "/api/v1/cars?km_max=lots", nil, 400, nil)

	// Seller type filter and stats.
	c.upsert(map[string]any{"url": specs[0].url, "seller": map[string]any{"type": "private", "name": "Ana"}})
	sameIDs(t, "seller_type=private", ids(c.list("seller_type=private")), a)
	sameIDs(t, "seller_type=unknown", ids(c.list("seller_type=unknown")), b, d, e)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/status", b), map[string]any{"status": "contacted"}, 200, nil)
	sameIDs(t, "status", ids(c.list("status=contacted&status=talking")), b)
	var st api.Stats
	c.call("GET", "/api/v1/stats", nil, 200, &st)
	if st.Total != 4 || st.ByStatus["new"] != 3 || st.ByStatus["contacted"] != 1 || st.Listings != 4 || st.ByVerdict["none"] != 4 {
		t.Fatalf("stats = %+v", st)
	}
	// last_activity default sort puts the most recently touched car first.
	if got := ids(c.list(""))[0]; got != b {
		t.Fatalf("last_activity first = %d, want %d", got, b)
	}
}

func TestSellerAndEvents(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/x-IDsel1.html", "make": "Fiat", "model": "500e",
		"seller": map[string]any{"name": "Rui", "type": "private", "contacts": []map[string]any{{"kind": "email", "value": "Rui@Example.COM"}}}})
	car := c.car(r.CarID)
	var s api.Seller
	c.call("GET", fmt.Sprintf("/api/v1/sellers/%d", car.Seller.ID), nil, 200, &s)
	if s.Contacts[0].Value != "rui@example.com" || !slices.Equal(s.CarIDs, []int64{r.CarID}) {
		t.Fatalf("seller = %+v", s)
	}
	c.call("PATCH", fmt.Sprintf("/api/v1/sellers/%d", s.ID), map[string]any{"city": "Coimbra", "contacts": []map[string]any{{"kind": "phone", "value": "955 550 111"}}}, 200, &s)
	if *s.City != "Coimbra" || len(s.Contacts) != 2 {
		t.Fatalf("patched seller = %+v", s)
	}
	c.call("GET", "/api/v1/sellers/999", nil, 404, nil)

	ev := map[string]any{"type": "vin_check", "summary": "VIN decoder: pano + heat pump", "dedupe_key": "vin-check-1", "data": map[string]any{"pr": []string{"3FU"}}}
	var e1, e2 api.Event
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/events", r.CarID), ev, 201, &e1)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/events", r.CarID), ev, 200, &e2)
	if e1.ID != e2.ID || !strings.Contains(string(e1.Data), "3FU") {
		t.Fatalf("event dedupe: %+v / %+v", e1, e2)
	}
	past := time.Date(2026, 9, 15, 12, 0, 0, 0, time.UTC)
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/events", r.CarID), map[string]any{"type": "call", "summary": "called seller", "at": past}, 201, &e1)
	if !e1.At.Equal(past) {
		t.Fatalf("event at = %v", e1.At)
	}
	c.call("POST", fmt.Sprintf("/api/v1/cars/%d/events", r.CarID), map[string]any{"type": "call"}, 422, nil)
	evs := c.events(r.CarID)
	if evs[len(evs)-1].ID != e1.ID {
		t.Fatal("events not newest first")
	}
}

// Use case: two loggers record the same send under different keys (history importer + an agent's
// catch-up script) → one row. Distinct sends from one logger, photo bursts and retries stay separate.
func TestMessageNearDuplicate(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://www.autoscout24.it/annunci/vw-id4-nd1", "make": "VW", "model": "ID.4"})
	car := fmt.Sprint(r.CarID)
	ad := "https://www.autoscout24.it/annunci/vw-id4-nd1"
	at := time.Date(2026, 11, 1, 14, 41, 0, 0, time.UTC)
	text := "Buongiorno,\n\nsono interessato alla Sua Volkswagen ID.4.\nSam"
	var hist, catchup api.Message
	c.as("import").call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out",
		"counterpart": ad, "text": text, "at": at, "dedupe_key": "abroad-history:d42f4a4c"}, 201, &hist)
	// No key (server derives auto:…), whitespace differs, 40 s later.
	c.as("abroad-agent").call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out",
		"counterpart": ad, "text": "Buongiorno, sono interessato alla Sua Volkswagen ID.4. Sam ", "at": at.Add(40 * time.Second)}, 200, &catchup)
	if catchup.ID != hist.ID || catchup.MatchedBy != "near_duplicate" {
		t.Fatalf("catch-up re-log = %+v, want #%d matched_by near_duplicate", catchup, hist.ID)
	}
	// A different caller key within the window: same answer.
	var other api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out", "counterpart": ad,
		"text": text, "at": at.Add(-2 * time.Minute), "dedupe_key": "sends:1793544060.1"}, 200, &other)
	if other.ID != hist.ID {
		t.Fatalf("cross-family key = %+v", other)
	}
	// Retrying that call stays idempotent.
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out", "counterpart": ad,
		"text": text, "at": at.Add(-2 * time.Minute), "dedupe_key": "sends:1793544060.1"}, 200, &other)

	// Outside the window, another channel, the other direction → separate rows.
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out", "counterpart": ad, "text": text, "at": at.Add(time.Hour)}, 201, nil)
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "email", "direction": "out", "counterpart": "info@dealer.example.com", "text": text, "at": at}, 201, nil)
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "in", "counterpart": ad, "text": text, "at": at}, 201, nil)
	// One logger's own distinct keys = distinct sends (an accidental double send is a fact worth keeping).
	sv := map[string]any{"car": car, "channel": "standvirtual", "direction": "out", "counterpart": ad, "text": "Olá, ainda está disponível?", "at": at}
	c.call("POST", "/api/v1/messages", maps(sv, map[string]any{"dedupe_key": "sends:1793535625.0"}), 201, nil)
	c.call("POST", "/api/v1/messages", maps(sv, map[string]any{"dedupe_key": "sends:1793535846.8", "at": at.Add(222 * time.Second)}), 201, nil)
	// Photo burst: same "[image]" text, distinct provider ids.
	img := map[string]any{"car": car, "channel": "whatsapp", "direction": "in", "counterpart": "351912000111", "text": "[image]", "at": at}
	c.call("POST", "/api/v1/messages", maps(img, map[string]any{"external_id": "3EB0A1"}), 201, nil)
	c.call("POST", "/api/v1/messages", maps(img, map[string]any{"external_id": "3EB0A2"}), 201, nil)
	// A failed attempt then a successful retry; a different recipient.
	wa := map[string]any{"car": car, "channel": "whatsapp", "direction": "out", "counterpart": "491714551337", "text": "Guten Tag", "at": at}
	c.call("POST", "/api/v1/messages", maps(wa, map[string]any{"error": "no LID found"}), 201, nil)
	var ok api.Message
	c.call("POST", "/api/v1/messages", maps(wa, map[string]any{"at": at.Add(time.Minute)}), 201, &ok)
	c.call("POST", "/api/v1/messages", maps(wa, map[string]any{"counterpart": "4915112429411", "at": at.Add(66 * time.Second)}), 201, nil)
	// The provider id found later lands on the near-duplicate row.
	var rec api.Message
	c.call("POST", "/api/v1/messages", maps(wa, map[string]any{"at": at.Add(time.Minute + 3*time.Second), "external_id": "3EB0WA1", "dedupe_key": "ext-import:x"}), 200, &rec)
	if rec.ID != ok.ID || rec.ExternalID == nil || *rec.ExternalID != "3EB0WA1" {
		t.Fatalf("external id attach on near duplicate = %+v", rec)
	}
	// Intentional repeat: allow_duplicate inserts.
	var forced api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "autoscout24", "direction": "out", "counterpart": ad,
		"text": text, "at": at.Add(time.Minute), "allow_duplicate": true}, 201, &forced)

	var log []api.Message
	c.call("GET", "/api/v1/cars/"+car+"/messages", nil, 200, &log)
	if len(log) != 12 {
		for _, m := range log {
			t.Logf("#%d %s %s %s %q key=%v", m.ID, m.At.Format(time.TimeOnly), m.Channel, m.Direction, m.Text, deref(m.DedupeKey))
		}
		t.Fatalf("chat log has %d rows, want 12", len(log))
	}

	// GET /messages/duplicates lists pairs by the same rule (the forced repeat is one).
	var pairs []api.MessageDuplicate
	c.call("GET", "/api/v1/messages/duplicates", nil, 200, &pairs)
	if len(pairs) != 1 || pairs[0].Keep.ID != hist.ID || pairs[0].Drop.ID != forced.ID {
		t.Fatalf("duplicates = %+v", pairs)
	}
}

// Use case: remove a double-logged row; it vanishes from every read, leaves a timeline event,
// and a re-post of its key does not bring it back.
func TestDeleteMessage(t *testing.T) {
	c := newServer(t)
	r := c.upsert(map[string]any{"url": "https://suchen.mobile.de/fahrzeuge/details.html?id=99900000000014", "make": "Mercedes", "model": "EQB"})
	car := fmt.Sprint(r.CarID)
	at := time.Date(2026, 11, 1, 13, 40, 0, 0, time.UTC)
	var keep, dup api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "mobile.de", "direction": "out", "text": "Guten Tag", "at": at, "dedupe_key": "abroad-history:0fb6"}, 201, &keep)
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "mobile.de", "direction": "out", "text": "Guten Tag", "at": at, "allow_duplicate": true}, 201, &dup)
	before := c.car(car).UpdatedAt

	var del api.Message
	c.as("ev-listings-db-fix").call("DELETE", fmt.Sprintf("/api/v1/messages/%d?reason=%s", dup.ID, "double-logged+(dup+of+%23"+fmt.Sprint(keep.ID)+")"), nil, 200, &del)
	if del.DeletedAt == nil || deref(del.DeletedBy) != "ev-listings-db-fix" || deref(del.DeletedReason) != "double-logged (dup of #"+fmt.Sprint(keep.ID)+")" {
		t.Fatalf("deleted = %+v", del)
	}
	// Gone from the car, the message list, the list summary, stats and activity.
	d := c.car(car)
	if len(d.Messages) != 1 || d.Messages[0].ID != keep.ID {
		t.Fatalf("car messages = %+v", d.Messages)
	}
	if !d.UpdatedAt.After(before) && !d.UpdatedAt.Equal(before) {
		t.Fatalf("updated_at went back")
	}
	var log []api.Message
	c.call("GET", "/api/v1/cars/"+car+"/messages", nil, 200, &log)
	if len(log) != 1 {
		t.Fatalf("messages = %+v", log)
	}
	for _, cs := range c.list("").Cars {
		if cs.ID == r.CarID && cs.MessageCount != 1 {
			t.Fatalf("message_count = %d", cs.MessageCount)
		}
	}
	var st api.Stats
	c.call("GET", "/api/v1/stats", nil, 200, &st)
	if st.Messages != 1 {
		t.Fatalf("stats messages = %d", st.Messages)
	}
	var act []api.ActivityItem
	c.call("GET", "/api/v1/activity", nil, 200, &act)
	sawEvent := false
	for _, a := range act {
		if a.Kind == "message" && a.Message.ID == dup.ID {
			t.Fatal("deleted message in activity")
		}
		if a.Kind == "event" && a.Event.Type == "message_deleted" {
			sawEvent = true
		}
	}
	evs := eventsOfType(c.events(car), "message_deleted")
	if !sawEvent || len(evs) != 1 || evs[0].Author != "ev-listings-db-fix" || !strings.Contains(evs[0].Summary, "double-logged") {
		t.Fatalf("message_deleted events = %+v (in activity: %v)", evs, sawEvent)
	}
	// Re-posting the deleted row's own key returns it (still deleted), not a new row.
	var again api.Message
	c.call("POST", "/api/v1/messages", map[string]any{"car": car, "channel": "mobile.de", "direction": "out", "text": "Guten Tag", "at": at, "dedupe_key": *dup.DedupeKey}, 200, &again)
	if again.ID != dup.ID || again.DeletedAt == nil {
		t.Fatalf("re-post of deleted key = %+v", again)
	}
	if n := len(c.car(car).Messages); n != 1 {
		t.Fatalf("after re-post: %d messages", n)
	}
	// Deleting again is a no-op; editing a deleted row is refused; unknown id → 404.
	c.call("DELETE", fmt.Sprintf("/api/v1/messages/%d", dup.ID), nil, 200, nil)
	if n := len(eventsOfType(c.events(car), "message_deleted")); n != 1 {
		t.Fatalf("second delete wrote an event (%d)", n)
	}
	c.call("PATCH", fmt.Sprintf("/api/v1/messages/%d", dup.ID), map[string]any{"text": "x"}, 409, nil)
	c.call("DELETE", "/api/v1/messages/99999", nil, 404, nil)

	// Restore brings it back with its own event.
	var res api.Message
	c.call("POST", fmt.Sprintf("/api/v1/messages/%d/restore", dup.ID), nil, 200, &res)
	if res.DeletedAt != nil || len(c.car(car).Messages) != 2 || len(eventsOfType(c.events(car), "message_restored")) != 1 {
		t.Fatalf("restore = %+v", res)
	}
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
