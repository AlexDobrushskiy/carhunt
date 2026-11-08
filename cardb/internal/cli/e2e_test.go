package cli_test

import (
	"bytes"
	"context"
	"encoding/json"
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/cli"
	"carhunt/cardb/internal/secrets"
)

// e2e drives cli.Run against a real in-process server (see startServer in server_test.go).
type e2e struct {
	t     *testing.T
	url   string
	token string
}

func newE2E(t *testing.T) *e2e {
	t.Helper()
	// Never touch the developer's real config or environment.
	t.Setenv("CARDB_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("CARDB_URL", "")
	t.Setenv("CARDB_TOKEN", "")
	t.Setenv("CARDB_AUTHOR", "agent-session-1")
	home := t.TempDir()
	t.Setenv("CARHUNT_HOME", home)
	t.Setenv("CARHUNT_CONFIG", filepath.Join(home, "config.yaml"))
	t.Setenv("CARHUNT_SECRETS_BACKEND", "file")
	t.Setenv("CARHUNT_SECRET_CARDB_TOKEN", "")
	url, token := startServer(t)
	return &e2e{t: t, url: url, token: token}
}

type result struct {
	stdout, stderr string
	code           int
}

func (e *e2e) run(args ...string) result {
	return e.runStdin("", args...)
}

func (e *e2e) runStdin(stdin string, args ...string) result {
	e.t.Helper()
	var out, errb bytes.Buffer
	full := append([]string{"--server", e.url, "--token", e.token}, args...)
	code := cli.RunWithStdin(context.Background(), full, strings.NewReader(stdin), &out, &errb)
	return result{out.String(), errb.String(), code}
}

// ok runs a command that must succeed.
func (e *e2e) ok(args ...string) string {
	e.t.Helper()
	r := e.run(args...)
	if r.code != 0 {
		e.t.Fatalf("cardb %s: exit %d\nstdout: %s\nstderr: %s", strings.Join(args, " "), r.code, r.stdout, r.stderr)
	}
	return r.stdout
}

// okJSON runs a command with --json and decodes stdout into out.
func (e *e2e) okJSON(out any, args ...string) {
	e.t.Helper()
	s := e.ok(append([]string{"--json"}, args...)...)
	if err := json.Unmarshal([]byte(s), out); err != nil {
		e.t.Fatalf("cardb %s --json: unparsable output: %v\n%s", strings.Join(args, " "), err, s)
	}
}

func (e *e2e) upsert(args ...string) api.UpsertResult {
	e.t.Helper()
	var r api.UpsertResult
	e.okJSON(&r, append([]string{"upsert"}, args...)...)
	return r
}

func id(n int64) string { return strconv.FormatInt(n, 10) }

func writeJPEG(t *testing.T, seed uint8) string {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 64, 48))
	for y := 0; y < 48; y++ {
		for x := 0; x < 64; x++ {
			img.Set(x, y, color.RGBA{uint8(x*4) ^ seed, uint8(y*5) + seed, seed, 255})
		}
	}
	p := filepath.Join(t.TempDir(), "photo-"+strconv.Itoa(int(seed))+".jpg")
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	if err := jpeg.Encode(f, img, nil); err != nil {
		t.Fatal(err)
	}
	f.Close()
	return p
}

const adURL = "https://www.standvirtual.com/carros/anuncio/mini-countryman-e-IDsynMn01.html"

func TestUpsertIdempotent(t *testing.T) {
	e := newE2E(t)
	r1 := e.upsert("--url", adURL, "--price", "34 600", "--make", "MINI", "--model", "Countryman E",
		"--reg", "05/2024", "--km", "31.200", "--country", "pt", "--city", "Porto")
	if !r1.CarCreated || !r1.ListingCreated || r1.CarID == 0 || r1.ListingID == 0 {
		t.Fatalf("first upsert: %+v", r1)
	}
	// Same ad with tracking params and a fragment: same listing, nothing created.
	r2 := e.upsert("--url", adURL+"?utm_source=x#gallery", "--price", "34600")
	if r2.CarID != r1.CarID || r2.ListingID != r1.ListingID || r2.CarCreated || r2.ListingCreated || r2.PriceChanged {
		t.Fatalf("second upsert not idempotent: %+v vs %+v", r2, r1)
	}
	r3 := e.upsert("--url", adURL, "--price", "33900")
	if !r3.PriceChanged || r3.ListingID != r1.ListingID {
		t.Fatalf("price change not detected: %+v", r3)
	}
	var car api.CarDetail
	e.okJSON(&car, "show", id(r1.CarID))
	if car.RegDate == nil || *car.RegDate != "2024-05" || car.Km == nil || *car.Km != 31200 || car.Country == nil || *car.Country != "PT" {
		t.Fatalf("specs not normalized: reg=%v km=%v country=%v", car.RegDate, car.Km, car.Country)
	}
	if len(car.Listings) != 1 || len(car.Listings[0].PriceHistory) < 2 {
		t.Fatalf("want 1 listing with price history, got %+v", car.Listings)
	}
	// Human output carries the ids.
	out := e.ok("upsert", "--url", adURL)
	if !strings.Contains(out, "car "+id(r1.CarID)) || !strings.Contains(out, "listing "+id(r1.ListingID)+" (updated)") {
		t.Fatalf("human upsert output: %s", out)
	}
}

func TestShowFullCard(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--price", "34600", "--make", "MINI", "--model", "Countryman E", "--variant", "Favoured L",
		"--seller-name", "Rui", "--seller-type", "private", "--phone", "+351555010203",
		"--opt", "pano=yes:ad_text:Teto panorâmico", "--fact", "warranty=to 2028-11:seller_said", "--slug", "pt-testcar-lisbon")
	car := id(r.CarID)
	e.ok("verdict", car, "👍", "--note", "great spec")
	// Flags after positionals, the way agents write them.
	e.ok("note", car, "Seller is relaxed about test drives", "--pin")
	e.ok("msg", "--car", car, "--channel", "whatsapp", "--dir", "out", "Olá, ainda está disponível?")
	e.ok("msg", "--car", car, "--channel", "whatsapp", "--dir", "in", "--sender", "Rui", "--at", "2026-11-01T14:20:00Z", "Sim, está.")
	e.ok("opt", car, "heat_pump=no:vin_pr_code:S4T1", "hud=unknown")

	out := e.ok("show", "pt-testcar-lisbon") // by slug
	for _, want := range []string{
		"MINI Countryman E Favoured L", adURL, "👍", "great spec", "✓ pano", "Teto panorâmico", "✗ heat_pump",
		"warranty: to 2028-11", "seller_said", "Rui", "📌", "Seller is relaxed", "Olá, ainda está disponível?", "Sim, está.", "←", "→",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("show output lacks %q", want)
		}
	}
	if t.Failed() {
		t.Log(out)
	}

	var d api.CarDetail
	e.okJSON(&d, "show", car)
	// Oldest first: the backdated reply sorts before the message sent "now".
	if len(d.Messages) != 2 || d.Messages[0].Direction != "in" || d.Messages[1].Direction != "out" || d.Verdict == nil || d.Verdict.Value != "up" {
		t.Fatalf("detail: messages=%d verdict=%+v", len(d.Messages), d.Verdict)
	}
	if len(d.Notes) != 1 || !d.Notes[0].Pinned || d.Notes[0].Author != "agent-session-1" {
		t.Fatalf("note not pinned or author header not sent: %+v", d.Notes)
	}
}

func TestMsgByPhone(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--make", "MINI", "--model", "Countryman E", "--seller-type", "private", "--phone", "+351 555 010 203")
	var m struct {
		Message api.Message `json:"message"`
		Created bool        `json:"created"`
	}
	e.okJSON(&m, "msg", "--to", "351555010203", "--channel", "whatsapp", "--dir", "in", "--external-id", "wamid.1", "Bom dia")
	if m.Message.CarID != r.CarID || !m.Created {
		t.Fatalf("msg by phone: %+v", m)
	}
	e.okJSON(&m, "msg", "--to", "+351 555 010 203", "--channel", "whatsapp", "--dir", "in", "--external-id", "wamid.1", "Bom dia")
	if m.Created {
		t.Fatalf("re-logging the same external id created a duplicate: %+v", m)
	}
	// Text from stdin.
	r2 := e.runStdin("linha 1\nlinha 2\n", "msg", "--to", "351555010203", "--channel", "whatsapp", "--dir", "out", "-")
	if r2.code != 0 || !strings.Contains(r2.stdout, "on car "+id(r.CarID)) {
		t.Fatalf("stdin msg: %+v", r2)
	}
	var msgs []api.Message
	e.okJSON(&msgs, "msgs", id(r.CarID))
	if len(msgs) != 2 || msgs[1].Text != "linha 1\nlinha 2" {
		t.Fatalf("messages: %+v", msgs)
	}
	// Unknown counterpart is an error, not a silent drop.
	if r := e.run("msg", "--to", "351000000000", "--channel", "whatsapp", "--dir", "in", "x"); r.code == 0 {
		t.Fatalf("unknown counterpart accepted: %+v", r)
	}
}

func TestLsFilters(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", "https://www.olx.pt/d/anuncio/kia-ev6-IDabc1.html", "--make", "Kia", "--model", "EV6",
		"--price", "38000", "--km", "20000", "--reg", "2023-03", "--country", "PT", "--opt", "pano=yes")
	b := e.upsert("--url", "https://www.olx.pt/d/anuncio/hyundai-ioniq5-IDabc2.html", "--make", "Hyundai", "--model", "Ioniq 5",
		"--price", "31000", "--km", "45000", "--reg", "2022-06", "--country", "ES", "--opt", "pano=no")
	c := e.upsert("--url", "https://www.olx.pt/d/anuncio/skoda-enyaq-IDabc3.html", "--make", "Skoda", "--model", "Enyaq",
		"--price", "29500", "--km", "60000", "--reg", "2021-09", "--country", "PT")
	e.ok("status", id(a.CarID), "talking")
	e.ok("status", id(b.CarID), "ready-to-visit", "--reason", "seller ok with Saturday")
	e.ok("verdict", id(c.CarID), "dislike")

	ids := func(args ...string) []int64 {
		var l api.CarList
		e.okJSON(&l, append([]string{"ls"}, args...)...)
		var out []int64
		for _, c := range l.Cars {
			out = append(out, c.ID)
		}
		return out
	}
	eq := func(name string, got []int64, want ...int64) {
		t.Helper()
		if len(got) != len(want) {
			t.Fatalf("%s: got %v want %v", name, got, want)
		}
		seen := map[int64]bool{}
		for _, g := range got {
			seen[g] = true
		}
		for _, w := range want {
			if !seen[w] {
				t.Fatalf("%s: got %v want %v", name, got, want)
			}
		}
	}
	eq("all", ids(), a.CarID, b.CarID, c.CarID)
	eq("status", ids("--status", "talking"), a.CarID)
	eq("status list", ids("--status", "talking,ready_to_visit"), a.CarID, b.CarID)
	eq("max-price", ids("--max-price", "32 000"), b.CarID, c.CarID)
	eq("max-km", ids("--max-km", "50000"), a.CarID, b.CarID)
	eq("country", ids("--country", "pt"), a.CarID, c.CarID)
	eq("opt", ids("--opt", "pano:yes"), a.CarID)
	eq("verdict", ids("--verdict", "down"), c.CarID)
	eq("verdict none", ids("--verdict", "none"), a.CarID, b.CarID)
	eq("year", ids("--year-min", "2022"), a.CarID, b.CarID)

	out := e.ok("ls", "--status", "ready_to_visit")
	if !strings.Contains(out, "Hyundai Ioniq 5") || !strings.Contains(out, "31 000") || strings.Contains(out, "Kia") {
		t.Fatalf("ls table: %s", out)
	}
}

func TestMergeSplit(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", "https://www.standvirtual.com/carros/anuncio/vw-id4-IDmerge1.html", "--make", "Volkswagen", "--model", "ID.4", "--km", "40000")
	b := e.upsert("--url", "https://www.mobile.de/fahrzeuge/details.html?id=987654", "--make", "Volkswagen", "--model", "ID.4", "--colour", "grey")
	if a.CarID == b.CarID {
		t.Fatalf("cars auto-linked unexpectedly")
	}
	e.ok("msg", "--car", id(b.CarID), "--channel", "email", "--dir", "out", "Hallo, ist das Auto noch da?")

	var merged api.CarDetail
	e.okJSON(&merged, "merge", id(a.CarID), id(b.CarID))
	if merged.ID != a.CarID || len(merged.Listings) != 2 || len(merged.Messages) != 1 {
		t.Fatalf("merge result: id=%d listings=%d messages=%d", merged.ID, len(merged.Listings), len(merged.Messages))
	}
	if merged.Colour == nil || *merged.Colour != "grey" {
		t.Fatalf("empty spec not filled from source: %v", merged.Colour)
	}
	// The source id still resolves, to the target.
	var viaOld api.CarDetail
	e.okJSON(&viaOld, "show", id(b.CarID))
	if viaOld.ID != a.CarID {
		t.Fatalf("merged id resolves to %d, want %d", viaOld.ID, a.CarID)
	}
	var list api.CarList
	e.okJSON(&list, "ls")
	if list.Total != 1 {
		t.Fatalf("merged car still listed: total=%d", list.Total)
	}

	var split api.CarDetail
	e.okJSON(&split, "split", id(a.CarID), "--listing", id(b.ListingID))
	if split.ID == a.CarID || len(split.Listings) != 1 || split.Listings[0].ID != b.ListingID {
		t.Fatalf("split result: %+v", split.Listings)
	}
	var after api.CarDetail
	e.okJSON(&after, "show", id(a.CarID))
	if len(after.Listings) != 1 || after.Listings[0].ID != a.ListingID {
		t.Fatalf("original car after split: %+v", after.Listings)
	}
}

func TestPhotosAndFindListing(t *testing.T) {
	e := newE2E(t)
	p1, p2 := writeJPEG(t, 1), writeJPEG(t, 90)
	var r struct {
		api.UpsertResult
		UploadedPhotos []api.Photo `json:"uploaded_photos"`
	}
	e.okJSON(&r, "upsert", "--url", adURL, "--make", "MINI", "--photo", p1, "--photo", p2)
	if len(r.UploadedPhotos) != 2 || len(r.PhotoErrors) != 0 {
		t.Fatalf("photo upload: %+v", r)
	}
	// Same bytes again: no new photo.
	var added []struct {
		Created bool `json:"created"`
	}
	e.okJSON(&added, "photo", "add", id(r.CarID), p1)
	if len(added) != 1 || added[0].Created {
		t.Fatalf("duplicate photo created: %+v", added)
	}
	dst := filepath.Join(t.TempDir(), "thumb.jpg")
	e.ok("photo", "get", id(r.UploadedPhotos[0].ID), "--size", "thumb", "-o", dst)
	b, err := os.ReadFile(dst)
	if err != nil || len(b) < 4 || b[0] != 0xFF || b[1] != 0xD8 {
		t.Fatalf("photo get did not write a JPEG (%d bytes, err %v)", len(b), err)
	}

	var ls []api.Listing
	e.okJSON(&ls, "find-listing", adURL+"?utm_campaign=z")
	if len(ls) != 1 || ls[0].CarID != r.CarID {
		t.Fatalf("find-listing: %+v", ls)
	}
	nf := e.run("find-listing", "https://www.olx.pt/d/anuncio/nothing-IDnope.html")
	if nf.code != cli.ExitNotFound {
		t.Fatalf("find-listing miss: exit %d, %s", nf.code, nf.stderr)
	}
}

func TestEventsNotesFactsSet(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--make", "MINI", "--km", "31200")
	car := id(r.CarID)
	var ev struct {
		Event   api.Event `json:"event"`
		Created bool      `json:"created"`
	}
	e.okJSON(&ev, "event", car, "--type", "vin_check", "--summary", "no accidents", "--data", `{"source":"carvertical"}`, "--key", "vin-1")
	if !ev.Created {
		t.Fatal("event not created")
	}
	e.okJSON(&ev, "event", car, "--type", "vin_check", "--summary", "no accidents", "--key", "vin-1")
	if ev.Created {
		t.Fatal("event with same key created twice")
	}

	e.ok("set", car, "--vin", "syn11ga0x07p12345", "--km", "32 000", "--summary", "clean car")
	e.ok("set", car, "--clear", "summary")
	e.ok("needs-owner", car, "confirm test drive Saturday 10:00")
	e.ok("alias", car, "C7")
	e.ok("fact", car, "owners=1:ad_spec", "service=at 10:00 on Monday:seller_said")
	var d api.CarDetail
	e.okJSON(&d, "show", "C7")
	if d.VIN == nil || *d.VIN != "SYN11GA0X07P12345" || *d.Km != 32000 || d.Summary != nil || !d.NeedsOwner {
		t.Fatalf("set/needs-owner: vin=%v km=%v summary=%v needs=%v", d.VIN, d.Km, d.Summary, d.NeedsOwner)
	}
	facts := map[string]api.Fact{}
	for _, f := range d.Facts {
		facts[f.Key] = f
	}
	if facts["service"].Value != "at 10:00 on Monday" || facts["service"].Source != "seller_said" || facts["owners"].Value != "1" {
		t.Fatalf("facts: %+v", d.Facts)
	}
	e.ok("needs-owner", car, "--clear")

	var notes []api.Note
	e.okJSON(&notes, "notes", car)
	n0 := len(notes)
	var n api.Note
	e.okJSON(&n, "note", car, "--", "-10% if paid cash")
	e.ok("note-edit", id(n.ID), "−10% if paid cash, confirmed", "--pin")
	e.okJSON(&notes, "notes", car)
	if len(notes) != n0+1 || !notes[0].Pinned || !strings.Contains(notes[0].Text, "confirmed") {
		t.Fatalf("notes: %+v", notes)
	}
	e.ok("note-rm", id(n.ID))
	e.okJSON(&notes, "notes", car)
	if len(notes) != n0 {
		t.Fatalf("note not deleted")
	}
}

func TestFromJSONBatch(t *testing.T) {
	e := newE2E(t)
	batch := `[
	 {"url":"https://www.olx.pt/d/anuncio/a-IDbat1.html","make":"Kia","model":"Niro EV","price":25000,"options":{"heat_pump":{"value":"yes","source":"ad_spec"}}},
	 {"url":"https://www.olx.pt/d/anuncio/b-IDbat2.html","make":"BYD","model":"Atto 3","price":27000},
	 {"make":"no url"}
	]`
	r := e.runStdin(batch, "upsert", "--from-json", "-", "--json")
	if r.code != cli.ExitError {
		t.Fatalf("batch with a bad item: exit %d, stderr %s", r.code, r.stderr)
	}
	var items []struct {
		Index  int               `json:"index"`
		Result *api.UpsertResult `json:"result"`
		Error  string            `json:"error"`
	}
	if err := json.Unmarshal([]byte(r.stdout), &items); err != nil {
		t.Fatalf("batch output: %v\n%s", err, r.stdout)
	}
	if len(items) != 3 || items[0].Result == nil || items[1].Result == nil || items[2].Error == "" {
		t.Fatalf("batch items: %+v", items)
	}
	var s api.Stats
	e.okJSON(&s, "stats")
	if s.Total != 2 || s.Listings != 2 {
		t.Fatalf("stats: %+v", s)
	}
}

func TestErrorsAndExitCodes(t *testing.T) {
	e := newE2E(t)
	if r := e.run("show", "99999"); r.code != cli.ExitNotFound {
		t.Fatalf("show missing: exit %d", r.code)
	}
	r := e.run("show", "99999", "--json")
	var je struct {
		Error    string `json:"error"`
		ExitCode int    `json:"exit_code"`
		Status   int    `json:"status"`
	}
	if r.stdout != "" || json.Unmarshal([]byte(r.stderr), &je) != nil || je.Status != 404 || je.ExitCode != cli.ExitNotFound {
		t.Fatalf("--json error: stdout=%q stderr=%q", r.stdout, r.stderr)
	}
	for _, args := range [][]string{
		{"status", "1", "sold"},
		{"verdict", "1", "great"},
		{"opt", "1", "pano=maybe"},
		{"upsert", "--price", "1"},
		{"msg", "--car", "1", "--dir", "in", "hi"},
		{"note", "1", "two", "words"},
		{"nonsense"},
	} {
		if r := e.run(args...); r.code != cli.ExitUsage {
			t.Errorf("cardb %v: exit %d (want %d), stderr %s", args, r.code, cli.ExitUsage, r.stderr)
		}
	}
	bad := cli.RunWithStdin(context.Background(), []string{"--server", e.url, "--token", "wrong", "stats"}, strings.NewReader(""), &bytes.Buffer{}, &bytes.Buffer{})
	if bad != cli.ExitError {
		t.Fatalf("bad token: exit %d", bad)
	}
	if out := e.ok("health"); !strings.Contains(out, "ok=true") {
		t.Fatalf("health: %s", out)
	}
}

func TestConfigSet(t *testing.T) {
	e := newE2E(t)
	var out bytes.Buffer
	if code := cli.Run(context.Background(), []string{"config", "set", "--url", e.url, "--token", e.token}, &out, &out); code != cli.ExitUsage {
		t.Fatalf("config set --token must be refused: %d %s", code, out.String())
	}
	if code := cli.Run(context.Background(), []string{"config", "set", "--url", e.url + "/"}, &out, &out); code != 0 {
		t.Fatalf("config set: %d %s", code, out.String())
	}
	st, err := os.Stat(os.Getenv("CARDB_CONFIG"))
	if err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("config file mode: %v %v", st, err)
	}
	if b, _ := os.ReadFile(os.Getenv("CARDB_CONFIG")); strings.Contains(string(b), "token") {
		t.Fatal("client config file holds a token")
	}
	// No token anywhere: 401 names where it looked.
	out.Reset()
	if code := cli.Run(context.Background(), []string{"stats"}, &out, &out); code != cli.ExitError || !strings.Contains(out.String(), "cardb init") {
		t.Fatalf("stats without a token: %d %s", code, out.String())
	}
	// The token in the secrets backend (file backend under CARHUNT_HOME): the client works with no flags at all.
	if err := (secrets.File{Dir: filepath.Join(os.Getenv("CARHUNT_HOME"), "secrets")}).Set("cardb_token", e.token); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if code := cli.Run(context.Background(), []string{"config", "show"}, &out, &out); code != 0 || strings.Contains(out.String(), e.token) ||
		!strings.Contains(out.String(), "file:cardb_token") {
		t.Fatalf("config show: %d %s", code, out.String())
	}
	out.Reset()
	if code := cli.Run(context.Background(), []string{"stats", "--json"}, &out, &out); code != 0 {
		t.Fatalf("stats via config file: %d %s", code, out.String())
	}
}

func TestRemovedThenRelisted(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--make", "MINI", "--seen-at", "2026-10-01T10:00:00Z")
	e.upsert("--url", adURL, "--removed", "--seen-at", "2026-10-05T10:00:00Z")
	var l api.Listing
	e.okJSON(&l, "listing", "show", id(r.ListingID))
	if l.Status != "removed" {
		t.Fatalf("after --removed: %s", l.Status)
	}
	// An older sighting does not resurrect it; a newer one relists it.
	if stale := e.upsert("--url", adURL, "--seen-at", "2026-10-03T10:00:00Z"); stale.Relisted {
		t.Fatal("stale sighting reported relisted")
	}
	e.okJSON(&l, "listing", "show", id(r.ListingID))
	if l.Status != "removed" {
		t.Fatalf("stale sighting relisted: %s", l.Status)
	}
	out := e.ok("upsert", "--url", adURL)
	if !strings.Contains(out, "relisted") {
		t.Fatalf("human output lacks relisted:\n%s", out)
	}
	e.okJSON(&l, "listing", "show", id(r.ListingID))
	if l.Status != "live" {
		t.Fatalf("fresh sighting did not relist: %s", l.Status)
	}
	if again := e.upsert("--url", adURL); again.Relisted {
		t.Fatal("already-live listing reported relisted")
	}
}

func TestMsgAttachByPhoneLinksPhoto(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--make", "MINI", "--model", "Countryman E", "--seller-type", "private", "--phone", "+351555010203")
	img := writeJPEG(t, 33)
	args := []string{"msg", "--to", "351555010203", "--channel", "whatsapp", "--dir", "in", "--external-id", "wamid.att", "--attach", img, "Foto do VIN"}
	check := func() api.Message {
		t.Helper()
		var m struct {
			Message api.Message `json:"message"`
		}
		e.okJSON(&m, args...)
		msg := m.Message
		if msg.CarID != r.CarID || len(msg.Attachments) != 1 || msg.Attachments[0].PhotoID == nil || msg.Attachments[0].Kind != "image" {
			t.Fatalf("attachment not linked: %+v", msg)
		}
		return msg
	}
	m1 := check()
	m2 := check() // re-run: same message, same photo, nothing new
	if m2.ID != m1.ID || *m2.Attachments[0].PhotoID != *m1.Attachments[0].PhotoID {
		t.Fatalf("re-run changed message/photo: %+v vs %+v", m2, m1)
	}
	var photos []api.Photo
	e.okJSON(&photos, "photo", "ls", id(r.CarID))
	if len(photos) != 1 || photos[0].ID != *m1.Attachments[0].PhotoID || photos[0].Source != "seller" {
		t.Fatalf("photos: %+v", photos)
	}
	if out := e.ok("show", id(r.CarID)); !strings.Contains(out, "(photo "+id(photos[0].ID)+")") {
		t.Fatalf("show lacks linked photo:\n%s", out)
	}
}

func TestVersionMatchesAPI(t *testing.T) {
	e := newE2E(t)
	var v map[string]string
	e.okJSON(&v, "version")
	var h api.Health
	e.okJSON(&h, "health")
	if v["version"] == "" || v["version"] != h.Version {
		t.Fatalf("cli version %q vs server %q", v["version"], h.Version)
	}
}

// writeJFIF writes JPEG bytes under the .jfif extension WhatsApp uses on save.
func writeJFIF(t *testing.T, seed uint8) string {
	t.Helper()
	src := writeJPEG(t, seed)
	dst := strings.TrimSuffix(src, ".jpg") + ".jfif"
	if err := os.Rename(src, dst); err != nil {
		t.Fatal(err)
	}
	return dst
}

func TestJFIFUploadsAsImage(t *testing.T) {
	e := newE2E(t)
	r := e.upsert("--url", adURL, "--make", "MINI", "--model", "Countryman E", "--seller-type", "private", "--phone", "+351555010203")
	car := id(r.CarID)

	// msg --attach, car resolved by phone: stored as a photo and linked.
	var m struct {
		Message api.Message `json:"message"`
	}
	e.okJSON(&m, "msg", "--to", "351555010203", "--channel", "whatsapp", "--dir", "in", "--attach", writeJFIF(t, 7), "VIN plate")
	if a := m.Message.Attachments; len(a) != 1 || a[0].Kind != "image" || a[0].PhotoID == nil || a[0].Mime == nil || *a[0].Mime != "image/jpeg" {
		t.Fatalf("jfif msg attachment: %+v", m.Message.Attachments)
	}
	// msg --attach with --car: uploaded before the message is posted.
	e.okJSON(&m, "msg", "--car", car, "--channel", "whatsapp", "--dir", "in", "--attach", writeJFIF(t, 8), "interior")
	if a := m.Message.Attachments; len(a) != 1 || a[0].PhotoID == nil {
		t.Fatalf("jfif msg (--car) attachment: %+v", a)
	}
	// photo add and upsert --photo.
	var added []struct {
		Created bool `json:"created"`
	}
	e.okJSON(&added, "photo", "add", car, writeJFIF(t, 9))
	if len(added) != 1 || !added[0].Created {
		t.Fatalf("photo add jfif: %+v", added)
	}
	var u struct {
		UploadedPhotos []api.Photo `json:"uploaded_photos"`
		PhotoErrors    []string    `json:"photo_errors"`
	}
	e.okJSON(&u, "upsert", "--url", adURL, "--photo", writeJFIF(t, 10))
	if len(u.UploadedPhotos) != 1 || len(u.PhotoErrors) != 0 {
		t.Fatalf("upsert --photo jfif: %+v", u)
	}
	var photos []api.Photo
	e.okJSON(&photos, "photo", "ls", car)
	if len(photos) != 4 {
		t.Fatalf("want 4 photos, got %d", len(photos))
	}
}

func heicFixture(t *testing.T) string {
	t.Helper()
	p, err := filepath.Abs("testdata/tiny.heic")
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// iPhone HEIC photos upload as-is (no sips on PATH) and the server decodes them.
func TestHEICUploadsAsIs(t *testing.T) {
	e := newE2E(t)
	t.Setenv("PATH", t.TempDir()) // prove no local conversion is involved
	r := e.upsert("--url", adURL, "--make", "MINI", "--seller-type", "private", "--phone", "+351555010203")
	car := id(r.CarID)
	heic := heicFixture(t)

	var added []struct {
		Photo   api.Photo `json:"photo"`
		Created bool      `json:"created"`
	}
	e.okJSON(&added, "photo", "add", car, heic)
	if len(added) != 1 || !added[0].Created || added[0].Photo.Width != 32 || added[0].Photo.Height != 24 {
		t.Fatalf("photo add heic: %+v", added)
	}
	e.okJSON(&added, "photo", "add", car, heic)
	if added[0].Created {
		t.Fatal("re-adding the same HEIC created a second photo")
	}
	var m struct {
		Message api.Message `json:"message"`
	}
	e.okJSON(&m, "msg", "--to", "351555010203", "--channel", "whatsapp", "--dir", "in", "--attach", heic, "foto")
	if a := m.Message.Attachments; len(a) != 1 || a[0].Kind != "image" || a[0].PhotoID == nil || a[0].Mime == nil || *a[0].Mime != "image/heic" {
		t.Fatalf("msg --attach heic: %+v", a)
	}
	var u struct {
		UploadedPhotos []api.Photo `json:"uploaded_photos"`
		PhotoErrors    []string    `json:"photo_errors"`
	}
	e.okJSON(&u, "upsert", "--url", adURL, "--photo", heic)
	if len(u.UploadedPhotos) != 1 || len(u.PhotoErrors) != 0 {
		t.Fatalf("upsert --photo heic: %+v", u)
	}
	var photos []api.Photo
	e.okJSON(&photos, "photo", "ls", car)
	if len(photos) != 1 {
		t.Fatalf("same HEIC via three paths should be one photo, got %d", len(photos))
	}
	dst := filepath.Join(t.TempDir(), "heic-thumb.jpg")
	e.ok("photo", "get", id(photos[0].ID), "--size", "thumb", "-o", dst)
	if b, err := os.ReadFile(dst); err != nil || len(b) < 2 || b[0] != 0xFF || b[1] != 0xD8 {
		t.Fatalf("HEIC photo not served as JPEG (err %v)", err)
	}
}

// A non-image file is rejected by content, whatever its extension, before anything is written.
func TestNonImageRejected(t *testing.T) {
	e := newE2E(t)
	car := id(e.upsert("--url", adURL, "--make", "MINI").CarID)
	fake := filepath.Join(t.TempDir(), "not-a-photo.jpg")
	os.WriteFile(fake, []byte("hello, I am text"), 0o644)
	if res := e.run("photo", "add", car, fake); res.code != cli.ExitUsage || !strings.Contains(res.stderr, "not an image") {
		t.Fatalf("photo add text file: exit %d stderr %s", res.code, res.stderr)
	}
	if res := e.run("upsert", "--url", adURL, "--photo", fake); res.code != cli.ExitUsage {
		t.Fatalf("upsert --photo text file: exit %d stderr %s", res.code, res.stderr)
	}
	var photos []api.Photo
	e.okJSON(&photos, "photo", "ls", car)
	if len(photos) != 0 {
		t.Fatalf("bad files created photos: %+v", photos)
	}
}

// --key and --dedupe-key are interchangeable on msg and event.
func TestKeyAliases(t *testing.T) {
	e := newE2E(t)
	car := id(e.upsert("--url", adURL, "--make", "MINI").CarID)
	var m struct {
		Message api.Message `json:"message"`
		Created bool        `json:"created"`
	}
	e.okJSON(&m, "msg", "--car", car, "--channel", "phone", "--dir", "out", "--key", "call-1", "called, no answer")
	first := m.Message.ID
	e.okJSON(&m, "msg", "--car", car, "--channel", "phone", "--dir", "out", "--dedupe-key", "call-1", "called, no answer (retry)")
	if m.Created || m.Message.ID != first {
		t.Fatalf("msg --dedupe-key after --key created a new message: %+v", m)
	}
	var ev struct {
		Event   api.Event `json:"event"`
		Created bool      `json:"created"`
	}
	e.okJSON(&ev, "event", car, "--type", "call", "--summary", "no answer", "--dedupe-key", "ev-1")
	e.okJSON(&ev, "event", car, "--type", "call", "--summary", "no answer", "--key", "ev-1")
	if ev.Created {
		t.Fatal("event --key after --dedupe-key created a new event")
	}
}

func TestRmCar(t *testing.T) {
	e := newE2E(t)
	a := e.upsert("--url", adURL, "--make", "MINI", "--model", "Countryman E", "--slug", "doomed", "--photo", writeJPEG(t, 5))
	car := id(a.CarID)
	e.ok("msg", "--car", car, "--channel", "whatsapp", "--dir", "out", "Olá")
	keep := e.upsert("--url", "https://www.olx.pt/d/anuncio/kia-IDkeep.html", "--make", "Kia", "--model", "EV6")
	gone := e.upsert("--url", "https://www.olx.pt/d/anuncio/kia-IDdupe.html", "--make", "Kia", "--model", "EV6", "--colour", "red")
	e.ok("merge", id(keep.CarID), id(gone.CarID))

	// Without --yes: a preview, exit 2, nothing deleted.
	r := e.run("rm", "doomed")
	if r.code != cli.ExitUsage || !strings.Contains(r.stdout, "would delete car "+car) || !strings.Contains(r.stdout, adURL) ||
		!strings.Contains(r.stdout, "1 message") || !strings.Contains(r.stdout, "1 photo") || !strings.Contains(r.stderr, "--yes") {
		t.Fatalf("rm preview: exit %d\nstdout: %s\nstderr: %s", r.code, r.stdout, r.stderr)
	}
	r = e.run("--json", "rm", car)
	var plan struct {
		CarID    int64    `json:"car_id"`
		Listings []string `json:"listings"`
		Deleted  bool     `json:"deleted"`
	}
	if r.code != cli.ExitUsage || json.Unmarshal([]byte(r.stdout), &plan) != nil || plan.CarID != a.CarID || len(plan.Listings) != 1 || plan.Deleted {
		t.Fatalf("rm --json preview: exit %d stdout %s", r.code, r.stdout)
	}
	e.ok("show", car)

	// The old id of a merged car must not delete the merge target.
	if r := e.run("rm", id(gone.CarID), "--yes"); r.code != cli.ExitUsage || !strings.Contains(r.stderr, "merged into car "+id(keep.CarID)) {
		t.Fatalf("rm merged id: exit %d stderr %s", r.code, r.stderr)
	}
	e.ok("show", id(keep.CarID))

	// With --yes (by alias): gone everywhere.
	out := e.ok("rm", "doomed", "--yes")
	if !strings.Contains(out, "deleted car "+car) {
		t.Fatalf("rm output: %s", out)
	}
	if r := e.run("show", car); r.code != cli.ExitNotFound {
		t.Fatalf("show after rm: exit %d", r.code)
	}
	if r := e.run("find-listing", adURL); r.code != cli.ExitNotFound {
		t.Fatalf("listing survived rm: exit %d %s", r.code, r.stdout)
	}
	var list api.CarList
	e.okJSON(&list, "ls")
	if list.Total != 1 || list.Cars[0].ID != keep.CarID {
		t.Fatalf("ls after rm: %+v", list)
	}
	// The URL is free again: upserting it makes a new car.
	if again := e.upsert("--url", adURL); !again.CarCreated || again.CarID == a.CarID {
		t.Fatalf("re-upsert after rm: %+v", again)
	}
	if r := e.run("rm", "99999", "--yes"); r.code != cli.ExitNotFound {
		t.Fatalf("rm missing: exit %d", r.code)
	}
}

// The /cars/112 bug: the history import and a catch-up script logged one dealer message under two keys.
// Now the second `cardb msg` returns the first row; `msg dupes` / `msg rm` clean older pairs.
func TestMsgNearDuplicateAndRm(t *testing.T) {
	e := newE2E(t)
	ad := "https://www.autoscout24.it/annunci/volkswagen-id-4-pro-syn0004a"
	car := id(e.upsert("--url", ad, "--make", "VW", "--model", "ID.4").CarID)
	text := "Buongiorno,\n\nsono interessato alla Sua Volkswagen ID.4.\nSam"
	msg := func(extra ...string) map[string]any {
		var out map[string]any
		args := append([]string{"msg", "--car", car, "--to", ad, "--channel", "autoscout24", "--dir", "out", "--at", "2026-11-01T14:41:00Z", "--text-file", "-"}, extra...)
		r := e.runStdin(text, append([]string{"--json"}, args...)...)
		if r.code != 0 {
			t.Fatalf("msg: exit %d: %s", r.code, r.stderr)
		}
		if err := json.Unmarshal([]byte(r.stdout), &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	first := msg("--dedupe-key", "abroad-history:d42f4a4c")
	second := msg() // catch-up script: no key
	firstID := first["message"].(map[string]any)["id"]
	sm := second["message"].(map[string]any)
	if first["created"] != true || second["created"] != false || sm["id"] != firstID || sm["matched_by"] != "near_duplicate" {
		t.Fatalf("second log = %v (first %v)", second, first)
	}
	r := e.runStdin(text, "msg", "--car", car, "--to", ad, "--channel", "autoscout24", "--dir", "out", "--at", "2026-11-01T14:42:00Z", "--text-file", "-")
	if r.code != 0 || !strings.Contains(r.stdout, "already logged (same text within 5 min") {
		t.Fatalf("human output = %q / %q", r.stdout, r.stderr)
	}
	var log []api.Message
	e.okJSON(&log, "msgs", car)
	if len(log) != 1 {
		t.Fatalf("chat log has %d rows, want 1", len(log))
	}

	// An older double-log (forced here) shows in `msg dupes` and goes with `msg rm`.
	forced := msg("--allow-duplicate")["message"].(map[string]any)
	dropID := id(int64(forced["id"].(float64)))
	var pairs []api.MessageDuplicate
	e.okJSON(&pairs, "msg", "dupes")
	if len(pairs) != 1 || id(pairs[0].Drop.ID) != dropID {
		t.Fatalf("dupes = %+v", pairs)
	}
	out := e.ok("msg", "rm", "#"+dropID, "--reason", "double-logged: dup of #"+id(pairs[0].Keep.ID))
	if !strings.Contains(out, "message "+dropID+" removed from car "+car) {
		t.Fatalf("rm output = %q", out)
	}
	e.okJSON(&log, "msgs", car)
	if len(log) != 1 || id(log[0].ID) != id(int64(firstID.(float64))) {
		t.Fatalf("after rm: %+v", log)
	}
	if out := e.ok("msg", "dupes"); !strings.Contains(out, "no double-logged messages") {
		t.Fatalf("dupes after rm = %q", out)
	}
	if out := e.ok("events", car); !strings.Contains(out, "message_deleted") || !strings.Contains(out, "double-logged") {
		t.Fatalf("timeline = %q", out)
	}
	if r := e.run("msg", "rm", "99999"); r.code != cli.ExitNotFound {
		t.Fatalf("rm unknown: exit %d", r.code)
	}
	e.ok("msg", "restore", dropID)
	if e.okJSON(&log, "msgs", car); len(log) != 2 {
		t.Fatalf("after restore: %d rows", len(log))
	}
}
