// Package client is a typed HTTP client for the ev-listings API (api/openapi.yaml).
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"carhunt/cardb/internal/api"
)

// Client talks to one ev-listings server. Author, when set, is sent as X-Author on every request.
type Client struct {
	BaseURL string // server root, with or without the /api/v1 suffix
	Token   string
	Author  string
	HTTP    *http.Client
}

// New returns a client with a default HTTP timeout (server-side photo fetches can be slow).
func New(baseURL, token, author string) *Client {
	return &Client{BaseURL: baseURL, Token: token, Author: author, HTTP: &http.Client{Timeout: 2 * time.Minute}}
}

// APIError is a non-2xx response.
type APIError struct {
	Status  int
	Message string
	Method  string
	Path    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s (HTTP %d %s %s)", e.Message, e.Status, e.Method, e.Path)
}

// IsNotFound reports whether err is an API 404.
func IsNotFound(err error) bool {
	var ae *APIError
	return errors.As(err, &ae) && ae.Status == http.StatusNotFound
}

func (c *Client) apiRoot() string {
	b := strings.TrimRight(c.BaseURL, "/")
	if !strings.HasSuffix(b, "/api/v1") {
		b += "/api/v1"
	}
	return b
}

func (c *Client) newRequest(ctx context.Context, method, path string, query url.Values, body io.Reader, contentType string) (*http.Request, error) {
	if c.BaseURL == "" {
		return nil, errors.New("no server URL configured (set CARDB_URL or run `cardb config set --url … --token …`)")
	}
	u := c.apiRoot() + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, u, body)
	if err != nil {
		return nil, err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	if c.Author != "" {
		req.Header.Set("X-Author", c.Author)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	req.Header.Set("Accept", "application/json")
	return req, nil
}

func (c *Client) httpClient() *http.Client {
	if c.HTTP != nil {
		return c.HTTP
	}
	return http.DefaultClient
}

// send executes req and decodes a JSON body into out (if non-nil). Returns the HTTP status.
func (c *Client) send(req *http.Request, out any) (int, error) {
	resp, err := c.httpClient().Do(req)
	if err != nil {
		return 0, fmt.Errorf("cannot reach %s: %w", c.BaseURL, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, err
	}
	if resp.StatusCode >= 300 {
		return resp.StatusCode, apiError(req, resp.StatusCode, data)
	}
	if out != nil && len(bytes.TrimSpace(data)) > 0 {
		if err := json.Unmarshal(data, out); err != nil {
			return resp.StatusCode, fmt.Errorf("decode response of %s %s: %w", req.Method, req.URL.Path, err)
		}
	}
	return resp.StatusCode, nil
}

func apiError(req *http.Request, status int, body []byte) error {
	var e api.Error
	msg := ""
	if json.Unmarshal(body, &e) == nil && e.Error != "" {
		msg = e.Error
	} else {
		msg = strings.TrimSpace(string(body))
		if len(msg) > 300 {
			msg = msg[:300] + "…"
		}
		if msg == "" {
			msg = http.StatusText(status)
		}
	}
	return &APIError{Status: status, Message: msg, Method: req.Method, Path: req.URL.Path}
}

func (c *Client) do(ctx context.Context, method, path string, query url.Values, body, out any) (int, error) {
	var r io.Reader
	ct := ""
	if body != nil {
		var buf []byte
		switch b := body.(type) {
		case json.RawMessage:
			buf = b
		case []byte:
			buf = b
		default:
			var err error
			if buf, err = json.Marshal(body); err != nil {
				return 0, err
			}
		}
		r = bytes.NewReader(buf)
		ct = "application/json"
	}
	req, err := c.newRequest(ctx, method, path, query, r, ct)
	if err != nil {
		return 0, err
	}
	return c.send(req, out)
}

func carPath(car string, rest ...string) string {
	p := "/cars/" + url.PathEscape(car)
	for _, r := range rest {
		p += "/" + url.PathEscape(r)
	}
	return p
}

func idPath(prefix string, id int64, rest ...string) string {
	p := prefix + "/" + strconv.FormatInt(id, 10)
	for _, r := range rest {
		p += "/" + r
	}
	return p
}

// ---- meta ----

func (c *Client) Health(ctx context.Context) (api.Health, error) {
	var h api.Health
	_, err := c.do(ctx, "GET", "/health", nil, nil, &h)
	return h, err
}

func (c *Client) Stats(ctx context.Context) (api.Stats, error) {
	var s api.Stats
	_, err := c.do(ctx, "GET", "/stats", nil, nil, &s)
	return s, err
}

func (c *Client) Activity(ctx context.Context, since *time.Time, limit int) ([]api.ActivityItem, error) {
	q := url.Values{}
	if since != nil {
		q.Set("since", since.UTC().Format(time.RFC3339))
	}
	if limit > 0 {
		q.Set("limit", strconv.Itoa(limit))
	}
	var out []api.ActivityItem
	_, err := c.do(ctx, "GET", "/activity", q, nil, &out)
	return out, err
}

// ---- cars ----

// CarFilter mirrors the GET /cars query parameters. Zero values are omitted.
type CarFilter struct {
	Q             string
	Make          string
	Model         string
	HpMin, HpMax  *int
	Drives        []string
	YearMin       int
	YearMax       int
	KmMax         int
	PriceMin      int
	PriceMax      int
	Countries     []string
	DistanceKmMax int
	SellerTypes   []string
	Statuses      []string
	Verdicts      []string // up|maybe|down|none
	Options       []string // key:value
	NeedsOwner    *bool
	HasDuplicates *bool
	GoodDeal      *bool
	ModelFamilies []string // canonical family names or "none"
	Tiers         []int    // "To rate" tiers 1|2|3
	Market        string
	Sort          string
	Order         string
	Limit         int
	Offset        int
}

// Values encodes the filter as query parameters.
func (f CarFilter) Values() url.Values {
	q := url.Values{}
	set := func(k, v string) {
		if v != "" {
			q.Set(k, v)
		}
	}
	setInt := func(k string, v int) {
		if v != 0 {
			q.Set(k, strconv.Itoa(v))
		}
	}
	setBool := func(k string, v *bool) {
		if v != nil {
			q.Set(k, strconv.FormatBool(*v))
		}
	}
	set("q", f.Q)
	set("make", f.Make)
	set("model", f.Model)
	for k, p := range map[string]*int{"hp_min": f.HpMin, "hp_max": f.HpMax} {
		if p != nil {
			q.Set(k, strconv.Itoa(*p))
		}
	}
	for _, v := range f.Drives {
		q.Add("drive", v)
	}
	setInt("year_min", f.YearMin)
	setInt("year_max", f.YearMax)
	setInt("km_max", f.KmMax)
	setInt("price_min", f.PriceMin)
	setInt("price_max", f.PriceMax)
	setInt("distance_km_max", f.DistanceKmMax)
	for _, v := range f.Countries {
		q.Add("country", v)
	}
	for _, v := range f.SellerTypes {
		q.Add("seller_type", v)
	}
	for _, v := range f.Statuses {
		q.Add("status", v)
	}
	for _, v := range f.Verdicts {
		q.Add("verdict", v)
	}
	for _, v := range f.Options {
		q.Add("option", v)
	}
	setBool("needs_owner", f.NeedsOwner)
	setBool("has_duplicates", f.HasDuplicates)
	setBool("good_deal", f.GoodDeal)
	for _, v := range f.ModelFamilies {
		q.Add("model_family", v)
	}
	for _, t := range f.Tiers {
		q.Add("tier", strconv.Itoa(t))
	}
	set("market", f.Market)
	set("sort", f.Sort)
	set("order", f.Order)
	setInt("limit", f.Limit)
	setInt("offset", f.Offset)
	return q
}

func (c *Client) ListCars(ctx context.Context, f CarFilter) (api.CarList, error) {
	var out api.CarList
	_, err := c.do(ctx, "GET", "/cars", f.Values(), nil, &out)
	return out, err
}

func (c *Client) GetCar(ctx context.Context, car string) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "GET", carPath(car), nil, nil, &out)
	return out, err
}

func (c *Client) CreateCar(ctx context.Context, in api.CarInput) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "POST", "/cars", nil, in, &out)
	return out, err
}

// PatchCar sends patch as-is; a nil map value is sent as JSON null and clears the field.
func (c *Client) PatchCar(ctx context.Context, car string, patch map[string]any) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "PATCH", carPath(car), nil, patch, &out)
	return out, err
}

// DeleteCar hard-deletes a car. confirmID must equal the car's resolved id (server-side guard).
func (c *Client) DeleteCar(ctx context.Context, car string, confirmID int64) error {
	q := url.Values{"confirm": {strconv.FormatInt(confirmID, 10)}}
	_, err := c.do(ctx, "DELETE", carPath(car), q, nil, nil)
	return err
}

func (c *Client) SetStatus(ctx context.Context, car string, in api.StatusInput) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "POST", carPath(car, "status"), nil, in, &out)
	return out, err
}

func (c *Client) PutOption(ctx context.Context, car, key string, in api.OptionInput) (api.Option, error) {
	var out api.Option
	_, err := c.do(ctx, "PUT", carPath(car, "options", key), nil, in, &out)
	return out, err
}

func (c *Client) DeleteOption(ctx context.Context, car, key string) error {
	_, err := c.do(ctx, "DELETE", carPath(car, "options", key), nil, nil, nil)
	return err
}

func (c *Client) PutFact(ctx context.Context, car, key string, in api.FactInput) (api.Fact, error) {
	var out api.Fact
	_, err := c.do(ctx, "PUT", carPath(car, "facts", key), nil, in, &out)
	return out, err
}

func (c *Client) DeleteFact(ctx context.Context, car, key string) error {
	_, err := c.do(ctx, "DELETE", carPath(car, "facts", key), nil, nil, nil)
	return err
}

func (c *Client) AddAlias(ctx context.Context, car, alias string) error {
	_, err := c.do(ctx, "POST", carPath(car, "aliases"), nil, api.AliasInput{Alias: alias}, nil)
	return err
}

func (c *Client) Merge(ctx context.Context, target string, in api.MergeInput) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "POST", carPath(target, "merge"), nil, in, &out)
	return out, err
}

func (c *Client) Split(ctx context.Context, car string, in api.SplitInput) (api.CarDetail, error) {
	var out api.CarDetail
	_, err := c.do(ctx, "POST", carPath(car, "split"), nil, in, &out)
	return out, err
}

// ---- notes ----

func (c *Client) ListNotes(ctx context.Context, car string) ([]api.Note, error) {
	var out []api.Note
	_, err := c.do(ctx, "GET", carPath(car, "notes"), nil, nil, &out)
	return out, err
}

func (c *Client) AddNote(ctx context.Context, car string, in api.NoteInput) (api.Note, error) {
	var out api.Note
	_, err := c.do(ctx, "POST", carPath(car, "notes"), nil, in, &out)
	return out, err
}

func (c *Client) PatchNote(ctx context.Context, id int64, in api.NotePatch) (api.Note, error) {
	var out api.Note
	_, err := c.do(ctx, "PATCH", idPath("/notes", id), nil, in, &out)
	return out, err
}

func (c *Client) DeleteNote(ctx context.Context, id int64) error {
	_, err := c.do(ctx, "DELETE", idPath("/notes", id), nil, nil, nil)
	return err
}

// ---- verdict ----

func (c *Client) PutVerdict(ctx context.Context, car string, in api.VerdictInput) (api.Verdict, error) {
	var out api.Verdict
	_, err := c.do(ctx, "PUT", carPath(car, "verdict"), nil, in, &out)
	return out, err
}

func (c *Client) DeleteVerdict(ctx context.Context, car string) error {
	_, err := c.do(ctx, "DELETE", carPath(car, "verdict"), nil, nil, nil)
	return err
}

// ---- good deal & model families ----

func (c *Client) PutGoodDeal(ctx context.Context, car string, in api.GoodDealInput) (api.GoodDeal, error) {
	var out api.GoodDeal
	_, err := c.do(ctx, "PUT", carPath(car, "good-deal"), nil, in, &out)
	return out, err
}

func (c *Client) ModelFamilies(ctx context.Context) (api.ModelFamilies, error) {
	var out api.ModelFamilies
	_, err := c.do(ctx, "GET", "/model-families", nil, nil, &out)
	return out, err
}

// Queue fetches the "To rate" queue; empty tiers = server default (1,2); spec "" | confirmed | unknown.
func (c *Client) Queue(ctx context.Context, tiers []int, spec string, limit, offset int) (api.Queue, error) {
	q := url.Values{}
	if spec != "" {
		q.Set("spec", spec)
	}
	for _, t := range tiers {
		q.Add("tier", strconv.Itoa(t))
	}
	if limit > 0 {
		q.Set("limit", strconv.Itoa(limit))
	}
	if offset > 0 {
		q.Set("offset", strconv.Itoa(offset))
	}
	var out api.Queue
	_, err := c.do(ctx, "GET", "/queue", q, nil, &out)
	return out, err
}

// ---- events & messages ----

func (c *Client) ListEvents(ctx context.Context, car string) ([]api.Event, error) {
	var out []api.Event
	_, err := c.do(ctx, "GET", carPath(car, "events"), nil, nil, &out)
	return out, err
}

// AddEvent returns created=false when an event with the same dedupe_key already existed.
func (c *Client) AddEvent(ctx context.Context, car string, in api.EventInput) (api.Event, bool, error) {
	var out api.Event
	st, err := c.do(ctx, "POST", carPath(car, "events"), nil, in, &out)
	return out, st == http.StatusCreated, err
}

func (c *Client) ListMessages(ctx context.Context, car string) ([]api.Message, error) {
	var out []api.Message
	_, err := c.do(ctx, "GET", carPath(car, "messages"), nil, nil, &out)
	return out, err
}

// AddMessage returns created=false when the message was already logged (external_id / dedupe_key /
// near duplicate: see Message.MatchedBy).
func (c *Client) AddMessage(ctx context.Context, in api.MessageInput) (api.Message, bool, error) {
	var out api.Message
	st, err := c.do(ctx, "POST", "/messages", nil, in, &out)
	return out, st == http.StatusCreated, err
}

// PatchMessage edits text/attachments/delivery/error; attachments replace the whole list.
func (c *Client) PatchMessage(ctx context.Context, id int64, in api.MessagePatch) (api.Message, error) {
	var out api.Message
	_, err := c.do(ctx, "PATCH", idPath("/messages", id), nil, in, &out)
	return out, err
}

// DeleteMessage soft-deletes a message (hidden from every read; its keys stay reserved).
func (c *Client) DeleteMessage(ctx context.Context, id int64, reason string) (api.Message, error) {
	var out api.Message
	var q url.Values
	if reason != "" {
		q = url.Values{"reason": {reason}}
	}
	_, err := c.do(ctx, "DELETE", idPath("/messages", id), q, nil, &out)
	return out, err
}

// RestoreMessage undoes DeleteMessage.
func (c *Client) RestoreMessage(ctx context.Context, id int64) (api.Message, error) {
	var out api.Message
	_, err := c.do(ctx, "POST", idPath("/messages", id)+"/restore", nil, nil, &out)
	return out, err
}

// MessageDuplicates lists live message pairs that look like one message logged twice.
func (c *Client) MessageDuplicates(ctx context.Context) ([]api.MessageDuplicate, error) {
	var out []api.MessageDuplicate
	_, err := c.do(ctx, "GET", "/messages/duplicates", nil, nil, &out)
	return out, err
}

// ---- photos ----

func (c *Client) ListPhotos(ctx context.Context, car string) ([]api.Photo, error) {
	var out []api.Photo
	_, err := c.do(ctx, "GET", carPath(car, "photos"), nil, nil, &out)
	return out, err
}

// AddPhotoURL asks the server to fetch a photo. created=false: same bytes already on this car.
func (c *Client) AddPhotoURL(ctx context.Context, car string, in api.PhotoURLInput) (api.Photo, bool, error) {
	var out api.Photo
	st, err := c.do(ctx, "POST", carPath(car, "photos"), nil, in, &out)
	return out, st == http.StatusCreated, err
}

// PhotoMeta are the optional multipart fields of a photo upload.
type PhotoMeta struct {
	Caption   string
	Source    string
	SourceRef string
	ListingID *int64
	Position  *int
}

// AddPhotoFile uploads a local image as multipart. created=false: same bytes already on this car.
func (c *Client) AddPhotoFile(ctx context.Context, car, path string, meta PhotoMeta) (api.Photo, bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return api.Photo{}, false, err
	}
	defer f.Close()
	return c.AddPhotoReader(ctx, car, filepath.Base(path), f, meta)
}

func (c *Client) AddPhotoReader(ctx context.Context, car, filename string, r io.Reader, meta PhotoMeta) (api.Photo, bool, error) {
	// The part's Content-Type comes from the bytes, not the file name (WhatsApp saves JPEGs as .jfif).
	head := make([]byte, 512)
	n, err := io.ReadFull(r, head)
	if err != nil && err != io.ErrUnexpectedEOF && err != io.EOF {
		return api.Photo{}, false, err
	}
	head = head[:n]
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	h := make(textproto.MIMEHeader)
	h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename=%q`, filename))
	h.Set("Content-Type", SniffType(head))
	fw, err := mw.CreatePart(h)
	if err != nil {
		return api.Photo{}, false, err
	}
	if _, err := io.Copy(fw, io.MultiReader(bytes.NewReader(head), r)); err != nil {
		return api.Photo{}, false, err
	}
	fields := map[string]string{"caption": meta.Caption, "source": meta.Source, "source_ref": meta.SourceRef}
	if meta.ListingID != nil {
		fields["listing_id"] = strconv.FormatInt(*meta.ListingID, 10)
	}
	if meta.Position != nil {
		fields["position"] = strconv.Itoa(*meta.Position)
	}
	for k, v := range fields {
		if v != "" {
			if err := mw.WriteField(k, v); err != nil {
				return api.Photo{}, false, err
			}
		}
	}
	if err := mw.Close(); err != nil {
		return api.Photo{}, false, err
	}
	req, err := c.newRequest(ctx, "POST", carPath(car, "photos"), nil, &buf, mw.FormDataContentType())
	if err != nil {
		return api.Photo{}, false, err
	}
	var out api.Photo
	st, err := c.send(req, &out)
	return out, st == http.StatusCreated, err
}

// GetPhoto returns the JPEG bytes; size is "", "thumb", "medium" or "full". Caller closes the body.
func (c *Client) GetPhoto(ctx context.Context, id int64, size string) (io.ReadCloser, error) {
	q := url.Values{}
	if size != "" {
		q.Set("size", size)
	}
	req, err := c.newRequest(ctx, "GET", idPath("/photos", id), q, nil, "")
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "image/jpeg")
	resp, err := c.httpClient().Do(req)
	if err != nil {
		return nil, fmt.Errorf("cannot reach %s: %w", c.BaseURL, err)
	}
	if resp.StatusCode >= 300 {
		defer resp.Body.Close()
		data, _ := io.ReadAll(resp.Body)
		return nil, apiError(req, resp.StatusCode, data)
	}
	return resp.Body, nil
}

func (c *Client) PatchPhoto(ctx context.Context, id int64, in api.PhotoPatch) (api.Photo, error) {
	var out api.Photo
	_, err := c.do(ctx, "PATCH", idPath("/photos", id), nil, in, &out)
	return out, err
}

func (c *Client) DeletePhoto(ctx context.Context, id int64) error {
	_, err := c.do(ctx, "DELETE", idPath("/photos", id), nil, nil, nil)
	return err
}

// ---- listings ----

func (c *Client) Upsert(ctx context.Context, in api.ListingUpsert) (api.UpsertResult, error) {
	var out api.UpsertResult
	_, err := c.do(ctx, "POST", "/listings/upsert", nil, in, &out)
	return out, err
}

// UpsertRaw posts an already-encoded ListingUpsert JSON object (keeps fields the typed struct doesn't know).
func (c *Client) UpsertRaw(ctx context.Context, body json.RawMessage) (api.UpsertResult, error) {
	var out api.UpsertResult
	_, err := c.do(ctx, "POST", "/listings/upsert", nil, body, &out)
	return out, err
}

// FindListings queries GET /listings; empty arguments are omitted.
func (c *Client) FindListings(ctx context.Context, listingURL, site, status string) ([]api.Listing, error) {
	q := url.Values{}
	if listingURL != "" {
		q.Set("url", listingURL)
	}
	if site != "" {
		q.Set("site", site)
	}
	if status != "" {
		q.Set("status", status)
	}
	var out []api.Listing
	_, err := c.do(ctx, "GET", "/listings", q, nil, &out)
	return out, err
}

func (c *Client) GetListing(ctx context.Context, id int64) (api.Listing, error) {
	var out api.Listing
	_, err := c.do(ctx, "GET", idPath("/listings", id), nil, nil, &out)
	return out, err
}

func (c *Client) PatchListing(ctx context.Context, id int64, in api.ListingPatch) (api.Listing, error) {
	var out api.Listing
	_, err := c.do(ctx, "PATCH", idPath("/listings", id), nil, in, &out)
	return out, err
}

// ---- duplicates ----

// ListDuplicates: status "" = server default (proposed); car "" = all cars.
func (c *Client) ListDuplicates(ctx context.Context, status, car string) ([]api.DuplicateCandidate, error) {
	q := url.Values{}
	if status != "" {
		q.Set("status", status)
	}
	if car != "" {
		q.Set("car", car)
	}
	var out []api.DuplicateCandidate
	_, err := c.do(ctx, "GET", "/duplicates", q, nil, &out)
	return out, err
}

func (c *Client) RejectDuplicate(ctx context.Context, id int64) (api.DuplicateCandidate, error) {
	var out api.DuplicateCandidate
	_, err := c.do(ctx, "POST", idPath("/duplicates", id, "reject"), nil, nil, &out)
	return out, err
}

// ---- sellers ----

func (c *Client) GetSeller(ctx context.Context, id int64) (api.Seller, error) {
	var out api.Seller
	_, err := c.do(ctx, "GET", idPath("/sellers", id), nil, nil, &out)
	return out, err
}

func (c *Client) PatchSeller(ctx context.Context, id int64, in api.SellerInput) (api.Seller, error) {
	var out api.Seller
	_, err := c.do(ctx, "PATCH", idPath("/sellers", id), nil, in, &out)
	return out, err
}
