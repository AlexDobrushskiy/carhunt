package cli

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

// photo, listing and seller subcommand groups.

// checkImageFile sniffs a local file's content (not its extension); non-images are a usage error.
func checkImageFile(path string) error {
	mt, err := client.SniffFile(path)
	if err != nil {
		return usageErrorf("%v", err)
	}
	if !client.IsImage(mt) {
		return usageErrorf("%s: not an image (content is %s)", path, mt)
	}
	return nil
}

// uploadPhotoFile uploads a local image as-is (the server decodes JPEG/PNG/GIF/WebP/HEIC/AVIF);
// errors name the file.
func uploadPhotoFile(e *env, cl *client.Client, car, path string, meta client.PhotoMeta) (api.Photo, bool, error) {
	ph, created, err := cl.AddPhotoFile(e.ctx, car, path, meta)
	if err != nil && !client.IsNotFound(err) {
		err = fmt.Errorf("%s: %w", path, err)
	}
	return ph, created, err
}

func subUsage(e *env, group, usage string, args []string) (string, []string, error) {
	if len(args) == 0 {
		fmt.Fprintln(e.stderr, usage)
		return "", nil, usageErrorf("%s: missing subcommand", group)
	}
	if args[0] == "-h" || args[0] == "--help" {
		fmt.Fprintln(e.stdout, usage)
		return "", nil, nil
	}
	return args[0], args[1:], nil
}

const photoUsage = `usage:
  cardb photo add CAR FILE|URL… [--caption C] [--source ad|seller|inspection|other] [--source-ref R] [--listing ID] [--position N]
  cardb photo get ID [--size thumb|medium|full] -o FILE   (-o - writes to stdout)
  cardb photo ls CAR
  cardb photo edit ID [--caption C] [--position N] [--cover]
  cardb photo rm ID…`

func cmdPhoto(e *env, args []string) error {
	sub, rest, err := subUsage(e, "photo", photoUsage, args)
	if err != nil || sub == "" {
		return err
	}
	switch sub {
	case "add":
		return photoAdd(e, rest)
	case "get":
		return photoGet(e, rest)
	case "ls", "list":
		return photoLs(e, rest)
	case "edit":
		return photoEdit(e, rest)
	case "rm", "delete":
		return photoRm(e, rest)
	}
	return usageErrorf("photo: unknown subcommand %q (add|get|ls|edit|rm)", sub)
}

func photoAdd(e *env, args []string) error {
	f := newFlags(e, "photo add")
	caption := f.String("caption", "", "caption")
	source := f.String("source", "", "ad|seller|inspection|other")
	sourceRef := f.String("source-ref", "", "ad photo #, chat message id, …")
	listing := f.String("listing", "", "listing id the photo belongs to")
	position := f.String("position", "", "display position (first file; later files follow)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("photo add", pos, 2, -1, "CAR FILE|URL…"); err != nil {
		return err
	}
	meta := client.PhotoMeta{Caption: *caption, Source: *source, SourceRef: *sourceRef}
	if *source != "" && !contains(api.PhotoSources, *source) {
		return usageErrorf("--source: want %s", strings.Join(api.PhotoSources, "|"))
	}
	if *listing != "" {
		id, err := parseID("--listing", *listing)
		if err != nil {
			return err
		}
		meta.ListingID = &id
	}
	startPos := -1
	if *position != "" {
		n, err := strconv.Atoi(*position)
		if err != nil {
			return usageErrorf("--position: want an integer")
		}
		startPos = n
	}
	for _, p := range pos[1:] {
		if !isURL(p) {
			if err := checkImageFile(p); err != nil {
				return err
			}
		}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	type added struct {
		Input   string     `json:"input"`
		Photo   *api.Photo `json:"photo,omitempty"`
		Created bool       `json:"created"`
		Error   string     `json:"error,omitempty"`
	}
	var out []added
	var failures []string
	for i, p := range pos[1:] {
		m := meta
		if startPos >= 0 {
			n := startPos + i
			m.Position = &n
		}
		var ph api.Photo
		var created bool
		if isURL(p) {
			ph, created, err = cl.AddPhotoURL(e.ctx, pos[0], api.PhotoURLInput{URL: p, Caption: m.Caption, Source: m.Source,
				SourceRef: m.SourceRef, ListingID: m.ListingID, Position: m.Position})
		} else {
			ph, created, err = uploadPhotoFile(e, cl, pos[0], p, m)
		}
		if err != nil {
			if client.IsNotFound(err) {
				return err // the car itself is missing; no point continuing
			}
			out = append(out, added{Input: p, Error: err.Error()})
			failures = append(failures, err.Error())
			continue
		}
		out = append(out, added{Input: p, Photo: &ph, Created: created})
	}
	if err := e.emit(out, func(w io.Writer) {
		for _, a := range out {
			switch {
			case a.Error != "":
				fmt.Fprintf(w, "ERROR %s\n", a.Error) // already names the file
			case a.Created:
				fmt.Fprintf(w, "photo %d added (%s)\n", a.Photo.ID, a.Input)
			default:
				fmt.Fprintf(w, "photo %d already on the car (%s)\n", a.Photo.ID, a.Input)
			}
		}
	}); err != nil {
		return err
	}
	if len(failures) > 0 {
		return fmt.Errorf("%d of %d photos failed: %s", len(failures), len(out), strings.Join(failures, "; "))
	}
	return nil
}

func photoGet(e *env, args []string) error {
	f := newFlags(e, "photo get")
	size := f.String("size", "", "thumb|medium|full (default full)")
	outPath := f.String("o", "", "output file (- = stdout)")
	f.StringVar(outPath, "out", "", "alias of -o")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("photo get", pos, 1, 1, "ID [--size thumb] -o FILE"); err != nil {
		return err
	}
	id, err := parseID("photo id", pos[0])
	if err != nil {
		return err
	}
	if *size != "" && !contains([]string{"thumb", "medium", "full"}, *size) {
		return usageErrorf("--size: want thumb|medium|full")
	}
	if *outPath == "" {
		*outPath = fmt.Sprintf("photo-%d.jpg", id)
		if *size != "" && *size != "full" {
			*outPath = fmt.Sprintf("photo-%d-%s.jpg", id, *size)
		}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	body, err := cl.GetPhoto(e.ctx, id, *size)
	if err != nil {
		return err
	}
	defer body.Close()
	if *outPath == "-" {
		_, err := io.Copy(e.stdout, body)
		return err
	}
	tmp := *outPath + ".part"
	fh, err := os.Create(tmp)
	if err != nil {
		return err
	}
	n, err := io.Copy(fh, body)
	if cerr := fh.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, *outPath); err != nil {
		return err
	}
	return e.emit(map[string]any{"id": id, "path": *outPath, "bytes": n}, func(w io.Writer) {
		fmt.Fprintf(w, "wrote %s (%d bytes)\n", *outPath, n)
	})
}

func photoLs(e *env, args []string) error {
	f := newFlags(e, "photo ls")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("photo ls", pos, 1, 1, "CAR"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ps, err := cl.ListPhotos(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return e.emit(ps, func(w io.Writer) {
		if len(ps) == 0 {
			fmt.Fprintln(w, "no photos")
			return
		}
		t := &table{header: []string{"ID", "POS", "COVER", "SIZE", "SOURCE", "LISTING", "CAPTION"}, rightAlign: map[int]bool{0: true, 1: true}}
		for _, p := range ps {
			cover := ""
			if p.Cover {
				cover = "★"
			}
			listing := ""
			if p.ListingID != nil {
				listing = strconv.FormatInt(*p.ListingID, 10)
			}
			t.add(strconv.FormatInt(p.ID, 10), strconv.Itoa(p.Position), cover, fmt.Sprintf("%dx%d", p.Width, p.Height), p.Source, listing, deref(p.Caption))
		}
		t.render(w)
	})
}

func photoEdit(e *env, args []string) error {
	f := newFlags(e, "photo edit")
	caption := f.String("caption", "", "caption")
	position := f.String("position", "", "display position")
	cover := f.Bool("cover", false, "make this the cover photo")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("photo edit", pos, 1, 1, "ID [--caption C] [--position N] [--cover]"); err != nil {
		return err
	}
	id, err := parseID("photo id", pos[0])
	if err != nil {
		return err
	}
	var p api.PhotoPatch
	if f.isSet("caption") {
		p.Caption = caption
	}
	if f.isSet("position") {
		n, err := strconv.Atoi(*position)
		if err != nil {
			return usageErrorf("--position: want an integer")
		}
		p.Position = &n
	}
	if f.isSet("cover") {
		p.Cover = cover
	}
	if p.Caption == nil && p.Position == nil && p.Cover == nil {
		return usageErrorf("photo edit: nothing to change")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ph, err := cl.PatchPhoto(e.ctx, id, p)
	if err != nil {
		return err
	}
	return e.emit(ph, func(w io.Writer) { fmt.Fprintf(w, "photo %d updated\n", ph.ID) })
}

func photoRm(e *env, args []string) error {
	f := newFlags(e, "photo rm")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("photo rm", pos, 1, -1, "ID…"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var ids []int64
	for _, s := range pos {
		id, err := parseID("photo id", s)
		if err != nil {
			return err
		}
		if err := cl.DeletePhoto(e.ctx, id); err != nil {
			return fmt.Errorf("photo %d: %w", id, err)
		}
		ids = append(ids, id)
	}
	return e.emit(map[string]any{"deleted": ids}, func(w io.Writer) { fmt.Fprintf(w, "deleted photo %v\n", ids) })
}

// ---- listing ----

const listingUsage = `usage:
  cardb listing show ID
  cardb listing set ID [--status live|removed|sold|unknown] [--price N] [--price-note T]`

func cmdListing(e *env, args []string) error {
	sub, rest, err := subUsage(e, "listing", listingUsage, args)
	if err != nil || sub == "" {
		return err
	}
	switch sub {
	case "show", "get":
		f := newFlags(e, "listing show")
		pos, err := f.parse(rest)
		if err != nil {
			return err
		}
		if err := needArgs("listing show", pos, 1, 1, "ID"); err != nil {
			return err
		}
		id, err := parseID("listing id", pos[0])
		if err != nil {
			return err
		}
		cl, err := e.client()
		if err != nil {
			return err
		}
		l, err := cl.GetListing(e.ctx, id)
		if err != nil {
			return err
		}
		return e.emit(l, func(w io.Writer) { printListing(w, l) })
	case "set":
		f := newFlags(e, "listing set")
		status := f.String("status", "", "live|removed|sold|unknown")
		price := f.String("price", "", "price, integer euros")
		priceNote := f.String("price-note", "", "price note")
		pos, err := f.parse(rest)
		if err != nil {
			return err
		}
		if err := needArgs("listing set", pos, 1, 1, "ID [--status S] [--price N]"); err != nil {
			return err
		}
		id, err := parseID("listing id", pos[0])
		if err != nil {
			return err
		}
		p := api.ListingPatch{Status: *status, PriceNote: *priceNote}
		if *status != "" && !contains(api.ListingStatuses, *status) {
			return usageErrorf("--status: want %s", strings.Join(api.ListingStatuses, "|"))
		}
		if f.isSet("price") {
			n, err := parseIntLenient(*price)
			if err != nil {
				return usageErrorf("--price: %v", err)
			}
			p.Price = &n
		}
		if p.Status == "" && p.Price == nil && p.PriceNote == "" {
			return usageErrorf("listing set: nothing to change")
		}
		cl, err := e.client()
		if err != nil {
			return err
		}
		l, err := cl.PatchListing(e.ctx, id, p)
		if err != nil {
			return err
		}
		return e.emit(l, func(w io.Writer) {
			fmt.Fprintf(w, "listing %d (car %d): %s %s\n", l.ID, l.CarID, l.Status, fmtPrice(l.Price))
		})
	}
	return usageErrorf("listing: unknown subcommand %q (show|set)", sub)
}

// ---- seller ----

const sellerUsage = `usage:
  cardb seller show ID
  cardb seller set ID [--seller-name N] [--seller-type T] [--seller-company C] [--seller-city C] [--seller-note N] [--phone P…] [--whatsapp P…] [--email E…] [--contact KIND:VALUE…]`

func cmdSeller(e *env, args []string) error {
	sub, rest, err := subUsage(e, "seller", sellerUsage, args)
	if err != nil || sub == "" {
		return err
	}
	f := newFlags(e, "seller "+sub)
	var sv *sellerVals
	if sub == "set" {
		sv = addSellerFlags(f)
	}
	pos, err := f.parse(rest)
	if err != nil {
		return err
	}
	if err := needArgs("seller "+sub, pos, 1, 1, "ID"); err != nil {
		return err
	}
	id, err := parseID("seller id", pos[0])
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var s api.Seller
	switch sub {
	case "show", "get":
		s, err = cl.GetSeller(e.ctx, id)
	case "set":
		in, berr := sv.build(f)
		if berr != nil {
			return berr
		}
		if in == nil {
			return usageErrorf("seller set: nothing to change")
		}
		s, err = cl.PatchSeller(e.ctx, id, *in)
	default:
		return usageErrorf("seller: unknown subcommand %q (show|set)", sub)
	}
	if err != nil {
		return err
	}
	return e.emit(s, func(w io.Writer) {
		printSeller(w, &s)
		if len(s.CarIDs) > 0 {
			fmt.Fprintf(w, "  cars: %s\n", joinIDs(s.CarIDs))
		}
	})
}

func joinIDs(ids []int64) string {
	parts := make([]string, len(ids))
	for i, id := range ids {
		parts[i] = strconv.FormatInt(id, 10)
	}
	return strings.Join(parts, ", ")
}
