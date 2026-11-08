package server

import (
	"context"
	"fmt"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/imaging"
	"carhunt/cardb/internal/store"
)

const (
	maxPhotoBytes     = 15 << 20
	photoFetchTimeout = 20 * time.Second
	photoFetchWorkers = 4
)

func tooLarge() error {
	return &store.Error{Kind: store.KindTooLarge, Msg: fmt.Sprintf("photo exceeds %d MB", maxPhotoBytes>>20)}
}

// fetchURL downloads one image (20 s timeout, 15 MB cap).
func (h *handler) fetchURL(ctx context.Context, u string) ([]byte, error) {
	if !strings.HasPrefix(u, "http://") && !strings.HasPrefix(u, "https://") {
		return nil, fmt.Errorf("unsupported photo url %q", u)
	}
	ctx, cancel := context.WithTimeout(ctx, photoFetchTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
	// Only formats we decode; never advertise AVIF/HEIC.
	req.Header.Set("Accept", "image/jpeg,image/png,image/webp;q=0.9,*/*;q=0.5")
	resp, err := h.fetch.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s: %s", u, resp.Status)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxPhotoBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxPhotoBytes {
		return nil, tooLarge()
	}
	return data, nil
}

// fetchPhotos downloads and prepares photo_urls in parallel; failures are reported, not fatal.
func (h *handler) fetchPhotos(ctx context.Context, urls []string) ([]store.UpsertPhoto, []string) {
	type result struct {
		p   *imaging.Prepared
		err error
	}
	results := make([]result, len(urls))
	sem := make(chan struct{}, photoFetchWorkers)
	var wg sync.WaitGroup
	for i, u := range urls {
		wg.Add(1)
		go func() {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			data, err := h.fetchURL(ctx, strings.TrimSpace(u))
			if err != nil {
				results[i].err = err
				return
			}
			results[i].p, results[i].err = imaging.Prepare(data)
		}()
	}
	wg.Wait()
	var photos []store.UpsertPhoto
	errs := []string{}
	seen := map[string]bool{}
	for i, r := range results {
		if r.err != nil {
			errs = append(errs, fmt.Sprintf("%s: %v", urls[i], r.err))
			continue
		}
		if seen[r.p.SHA256] {
			continue
		}
		seen[r.p.SHA256] = true
		photos = append(photos, store.UpsertPhoto{Prepared: r.p, URL: urls[i]})
	}
	return photos, errs
}

func (h *handler) addPhoto(w http.ResponseWriter, r *http.Request) error {
	var data []byte
	var meta store.PhotoMeta
	var bodyAuthor string
	ct, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
	switch ct {
	case "multipart/form-data":
		r.Body = http.MaxBytesReader(w, r.Body, maxPhotoBytes+1<<20)
		// Keep the whole upload in memory: the container has a tiny /tmp.
		if err := r.ParseMultipartForm(maxPhotoBytes + 1<<20); err != nil {
			if strings.Contains(err.Error(), "too large") {
				return tooLarge()
			}
			return badRequest("invalid multipart body: " + err.Error())
		}
		defer r.MultipartForm.RemoveAll()
		f, fh, err := r.FormFile("file")
		if err != nil {
			return invalid("file is required")
		}
		defer f.Close()
		if fh.Size > maxPhotoBytes {
			return tooLarge()
		}
		if data, err = io.ReadAll(io.LimitReader(f, maxPhotoBytes+1)); err != nil {
			return err
		}
		meta.Caption = r.FormValue("caption")
		meta.Source = r.FormValue("source")
		meta.SourceRef = r.FormValue("source_ref")
		bodyAuthor = r.FormValue("author")
		if v := r.FormValue("listing_id"); v != "" {
			n, err := strconv.ParseInt(v, 10, 64)
			if err != nil {
				return invalid("listing_id must be an integer")
			}
			meta.ListingID = &n
		}
		if v := r.FormValue("position"); v != "" {
			n, err := strconv.Atoi(v)
			if err != nil {
				return invalid("position must be an integer")
			}
			meta.Position = &n
		}
	default:
		var in struct {
			api.PhotoURLInput
			Author string `json:"author"`
		}
		if err := decode(w, r, &in); err != nil {
			return err
		}
		if strings.TrimSpace(in.URL) == "" {
			return invalid("file (multipart) or url (JSON) is required")
		}
		// Resolve the car first so an unknown car is a 404, not a wasted download.
		if _, err := h.st.ResolveCar(r.Context(), r.PathValue("car")); err != nil {
			return err
		}
		var err error
		if data, err = h.fetchURL(r.Context(), strings.TrimSpace(in.URL)); err != nil {
			if se, ok := err.(*store.Error); ok {
				return se
			}
			return invalid("fetch photo: " + err.Error())
		}
		meta = store.PhotoMeta{Caption: in.Caption, Source: in.Source, SourceRef: in.SourceRef, ListingID: in.ListingID, Position: in.Position}
		if meta.SourceRef == "" {
			meta.SourceRef = in.URL
		}
		bodyAuthor = in.Author
	}
	if len(data) > maxPhotoBytes {
		return tooLarge()
	}
	p, err := imaging.Prepare(data)
	if err != nil {
		return invalid(err.Error())
	}
	out, created, err := h.st.AddPhoto(r.Context(), r.PathValue("car"), p, meta, author(r, bodyAuthor))
	if err != nil {
		return err
	}
	status := http.StatusOK
	if created {
		status = http.StatusCreated
	}
	writeJSON(w, status, out)
	return nil
}
