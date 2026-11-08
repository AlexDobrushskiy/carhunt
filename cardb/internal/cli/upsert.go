package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

// upsertOutput is UpsertResult plus what the CLI did after it (local photo uploads).
type upsertOutput struct {
	api.UpsertResult
	UploadedPhotos []api.Photo `json:"uploaded_photos,omitempty"`
}

type batchItem struct {
	Index  int           `json:"index"`
	URL    string        `json:"url,omitempty"`
	Result *upsertOutput `json:"result,omitempty"`
	Error  string        `json:"error,omitempty"`
}

func cmdUpsert(e *env, args []string) error {
	f := newFlags(e, "upsert")
	lurl := f.String("url", "", "listing URL (required; the idempotency key)")
	site := f.String("site", "", "site name (derived from the URL if omitted)")
	title := f.String("title", "", "ad title")
	price := f.String("price", "", "asking price, integer euros ('34 600' ok)")
	priceNote := f.String("price-note", "", "price note, e.g. 'IVA dedutível', 'negotiable'")
	specs := addSpecFlags(f)
	seller := addSellerFlags(f)
	var opts, facts, photos, aliases multi
	f.Var(&opts, "opt", "option key=value[:source[:ref]], value yes|no|unknown (repeatable)")
	f.Var(&facts, "fact", "fact key=value[:source[:ref]] (repeatable)")
	f.Var(&photos, "photo", "photo file path or URL (repeatable; files uploaded after the upsert, URLs fetched by the server)")
	f.Var(&aliases, "alias", "car alias (repeatable)")
	source := f.String("source", "", "default evidence source for --opt/--fact without one")
	slug := f.String("slug", "", "stable human car id (becomes an alias)")
	status := f.String("status", "", "car status (applied when the car is created, or with --overwrite)")
	summary := f.String("summary", "", "one-line why interesting / watch-outs")
	car := f.String("car", "", "attach a NEW listing to this car (id/alias)")
	removed := f.Bool("removed", false, "the ad is gone (listing_status=removed)")
	sold := f.Bool("sold", false, "the ad says sold (listing_status=sold)")
	listingStatus := f.String("listing-status", "", "live|removed|sold|unknown")
	seenAt := f.String("seen-at", "", "when the ad was seen (RFC 3339; default now)")
	overwrite := f.Bool("overwrite", false, "overwrite existing car fields instead of fill-if-empty")
	rawJSON := f.String("raw-json", "", "file with the raw scraped payload (JSON), or - for stdin")
	fromJSON := f.String("from-json", "", "file with a ListingUpsert JSON object or array (batch), or - for stdin")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) == 1 && *lurl == "" && isURL(pos[0]) {
		*lurl = pos[0] // tolerate `cardb upsert URL …`
	} else if len(pos) > 0 {
		return usageErrorf("upsert takes no positional arguments (got %q); use --url", pos[0])
	}
	if *fromJSON != "" {
		for name := range f.set {
			if !contains([]string{"from-json", "json", "author", "token", "server"}, name) {
				return usageErrorf("--from-json cannot be combined with --%s (put the field in the JSON)", name)
			}
		}
		cl, err := e.client()
		if err != nil {
			return err
		}
		return upsertFromJSON(e, cl, *fromJSON)
	}

	if *lurl == "" {
		return usageErrorf("upsert: --url is required (or --from-json FILE)")
	}
	in := api.ListingUpsert{URL: strings.TrimSpace(*lurl), Site: *site, Title: *title, PriceNote: *priceNote,
		Car: *car, Slug: *slug, Summary: *summary, Overwrite: *overwrite, Aliases: aliases}
	if f.isSet("price") {
		p, err := parseIntLenient(*price)
		if err != nil {
			return usageErrorf("--price: %v", err)
		}
		in.Price = &p
	}
	specMap, err := specs.collect(f)
	if err != nil {
		return err
	}
	if err := fillSpecs(&in.CarSpecs, specMap); err != nil {
		return err
	}
	if in.Seller, err = seller.build(f); err != nil {
		return err
	}
	if *status != "" {
		if in.Status, err = normalizeStatus(*status); err != nil {
			return err
		}
	}
	switch {
	case *removed && *sold:
		return usageErrorf("--removed and --sold are exclusive")
	case *removed:
		in.ListingStatus = "removed"
	case *sold:
		in.ListingStatus = "sold"
	}
	if *listingStatus != "" {
		if in.ListingStatus != "" {
			return usageErrorf("--listing-status conflicts with --removed/--sold")
		}
		if !contains(api.ListingStatuses, *listingStatus) {
			return usageErrorf("--listing-status: want %s", strings.Join(api.ListingStatuses, "|"))
		}
		in.ListingStatus = *listingStatus
	}
	if *seenAt != "" {
		t, err := parseTime("seen-at", *seenAt)
		if err != nil {
			return err
		}
		in.SeenAt = &t
	}
	for _, o := range opts {
		ev, err := parseOptionArg(e, o, *source)
		if err != nil {
			return err
		}
		if in.Options == nil {
			in.Options = map[string]api.OptionInput{}
		}
		in.Options[ev.Key] = api.OptionInput{Value: ev.Value, Source: ev.Source, SourceRef: ev.Ref}
	}
	for _, fa := range facts {
		ev, err := parseEvidence(fa, *source)
		if err != nil {
			return err
		}
		if in.Facts == nil {
			in.Facts = map[string]api.FactInput{}
		}
		in.Facts[ev.Key] = api.FactInput{Value: ev.Value, Source: ev.Source, SourceRef: ev.Ref}
	}
	if *rawJSON != "" {
		b, err := e.readInput(*rawJSON)
		if err != nil {
			return err
		}
		if !json.Valid(b) {
			return usageErrorf("--raw-json: %s is not valid JSON", *rawJSON)
		}
		in.Raw = bytes.TrimSpace(b)
	}
	var files []string
	for _, p := range photos {
		if isURL(p) {
			in.PhotoURLs = append(in.PhotoURLs, p)
			continue
		}
		if err := checkImageFile(p); err != nil {
			return usageErrorf("--photo %v", err)
		}
		files = append(files, p)
	}

	cl, err := e.client()
	if err != nil {
		return err
	}
	res, err := cl.Upsert(e.ctx, in)
	if err != nil {
		return err
	}
	out := &upsertOutput{UpsertResult: res}
	uploadListingPhotos(e, cl, out, files)
	return e.emit(out, func(w io.Writer) { printUpsert(w, out) })
}

// fillSpecs copies the collected spec values into a CarSpecs via JSON.
func fillSpecs(dst *api.CarSpecs, m map[string]any) error {
	if len(m) == 0 {
		return nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, dst)
}

func uploadListingPhotos(e *env, cl *client.Client, out *upsertOutput, files []string) {
	car := fmt.Sprint(out.CarID)
	lid := out.ListingID
	for _, p := range files {
		ph, _, err := uploadPhotoFile(e, cl, car, p, client.PhotoMeta{Source: "ad", ListingID: &lid})
		if err != nil {
			out.PhotoErrors = append(out.PhotoErrors, err.Error())
			continue
		}
		out.UploadedPhotos = append(out.UploadedPhotos, ph)
	}
	for _, pe := range out.PhotoErrors {
		e.warnf("photo: %s", pe)
	}
}

func printUpsert(w io.Writer, r *upsertOutput) {
	carState, listState := "existing", "updated"
	if r.CarCreated {
		carState = "new"
	}
	if r.ListingCreated {
		listState = "new"
	}
	fmt.Fprintf(w, "car %d (%s) · listing %d (%s)\n", r.CarID, carState, r.ListingID, listState)
	if r.LinkedBy != nil {
		fmt.Fprintf(w, "linked to existing car by %s\n", *r.LinkedBy)
	}
	if r.Relisted {
		fmt.Fprintln(w, "relisted (ad is live again)")
	}
	if r.PriceChanged {
		fmt.Fprintln(w, "price changed")
	}
	if len(r.UploadedPhotos) > 0 {
		fmt.Fprintf(w, "uploaded %s\n", plural(len(r.UploadedPhotos), "photo", "photos"))
	}
	if len(r.DuplicateCandidates) > 0 {
		fmt.Fprintln(w, "possible duplicates (review: cardb dupes --car "+fmt.Sprint(r.CarID)+"):")
		for _, d := range r.DuplicateCandidates {
			printDupeLine(w, d, r.CarID)
		}
	}
	for _, pe := range r.PhotoErrors {
		fmt.Fprintf(w, "photo error: %s\n", pe)
	}
}

func printDupeLine(w io.Writer, d api.DuplicateCandidate, self int64) {
	other := d.OtherCarID
	if other == 0 {
		other = d.CarA
		if other == self {
			other = d.CarB
		}
	}
	title := ""
	if d.OtherTitle != "" {
		title = fmt.Sprintf(" %q", d.OtherTitle)
	}
	fmt.Fprintf(w, "  dupe #%d: car %d%s score %.2f — %s\n", d.ID, other, title, d.Score, strings.Join(d.Reasons, "; "))
}

// upsertFromJSON posts one object or an array of ListingUpsert objects. Entries of photo_urls
// that are local paths are removed from the body and uploaded after the upsert.
func upsertFromJSON(e *env, cl *client.Client, path string) error {
	data, err := e.readInput(path)
	if err != nil {
		return err
	}
	data = bytes.TrimSpace(data)
	var items []json.RawMessage
	single := len(data) > 0 && data[0] == '{'
	if single {
		items = []json.RawMessage{data}
	} else if err := json.Unmarshal(data, &items); err != nil {
		return usageErrorf("--from-json: want a JSON object or array: %v", err)
	}
	results := make([]batchItem, 0, len(items))
	failed := 0
	for i, raw := range items {
		bi := batchItem{Index: i}
		out, u, err := upsertOneRaw(e, cl, raw)
		bi.URL = u
		if err != nil {
			bi.Error = err.Error()
			failed++
			if single {
				return err
			}
		} else {
			bi.Result = out
		}
		results = append(results, bi)
	}
	if single {
		return e.emit(results[0].Result, func(w io.Writer) { printUpsert(w, results[0].Result) })
	}
	if err := e.emit(results, func(w io.Writer) {
		for _, r := range results {
			if r.Error != "" {
				fmt.Fprintf(w, "[%d] ERROR %s: %s\n", r.Index, r.URL, r.Error)
				continue
			}
			fmt.Fprintf(w, "[%d] ", r.Index)
			printUpsert(w, r.Result)
		}
		fmt.Fprintf(w, "%d upserted, %d failed\n", len(results)-failed, failed)
	}); err != nil {
		return err
	}
	if failed > 0 {
		return fmt.Errorf("%d of %d upserts failed", failed, len(results))
	}
	return nil
}

func upsertOneRaw(e *env, cl *client.Client, raw json.RawMessage) (*upsertOutput, string, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, "", usageErrorf("not a JSON object: %v", err)
	}
	var u string
	_ = json.Unmarshal(m["url"], &u)
	if strings.TrimSpace(u) == "" {
		return nil, "", usageErrorf("missing \"url\"")
	}
	var files []string
	if pu, ok := m["photo_urls"]; ok {
		var urls, remote []string
		if err := json.Unmarshal(pu, &urls); err != nil {
			return nil, u, usageErrorf("photo_urls: %v", err)
		}
		for _, p := range urls {
			if isURL(p) {
				remote = append(remote, p)
				continue
			}
			if err := checkImageFile(p); err != nil {
				return nil, u, usageErrorf("photo_urls: %v", err)
			}
			files = append(files, p)
		}
		if len(files) > 0 {
			if len(remote) == 0 {
				delete(m, "photo_urls")
			} else {
				m["photo_urls"], _ = json.Marshal(remote)
			}
			var err error
			if raw, err = json.Marshal(m); err != nil {
				return nil, u, err
			}
		}
	}
	res, err := cl.UpsertRaw(e.ctx, raw)
	if err != nil {
		return nil, u, err
	}
	out := &upsertOutput{UpsertResult: res}
	uploadListingPhotos(e, cl, out, files)
	return out, u, nil
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
