package server

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	apispec "carhunt/cardb/api"
	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/store"
)

const maxJSONBody = 8 << 20

type ctxKey int

const tokenNameKey ctxKey = 0

type handler struct {
	st     *store.Store
	tokens map[string]string // name → token
	fetch  *http.Client
}

// NewHandler returns the full HTTP handler (API under /api/v1, plus /healthz). tokens maps name → bearer token.
func NewHandler(st *store.Store, tokens map[string]string) http.Handler {
	h := &handler{st: st, tokens: tokens, fetch: &http.Client{Timeout: photoFetchTimeout}}
	mux := http.NewServeMux()
	route := func(pattern string, fn func(w http.ResponseWriter, r *http.Request) error) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			if err := fn(w, r); err != nil {
				writeError(w, r, err)
			}
		})
	}
	const p = "/api/v1"
	route("GET /healthz", h.health)
	route("GET "+p+"/health", h.health)
	route("GET "+p+"/openapi.yaml", func(w http.ResponseWriter, r *http.Request) error {
		w.Header().Set("Content-Type", "application/yaml")
		_, err := w.Write(apispec.Spec)
		return err
	})
	route("GET "+p+"/profile", h.profile)
	route("GET "+p+"/stats", h.stats)
	route("GET "+p+"/cars", h.listCars)
	route("POST "+p+"/cars", h.createCar)
	route("GET "+p+"/cars/{car}", h.getCar)
	route("PATCH "+p+"/cars/{car}", h.patchCar)
	route("DELETE "+p+"/cars/{car}", h.deleteCar)
	route("POST "+p+"/cars/{car}/status", h.setStatus)
	route("PUT "+p+"/cars/{car}/options/{key}", h.putOption)
	route("DELETE "+p+"/cars/{car}/options/{key}", h.deleteOption)
	route("PUT "+p+"/cars/{car}/facts/{key}", h.putFact)
	route("DELETE "+p+"/cars/{car}/facts/{key}", h.deleteFact)
	route("POST "+p+"/cars/{car}/aliases", h.addAlias)
	route("GET "+p+"/cars/{car}/notes", h.listNotes)
	route("POST "+p+"/cars/{car}/notes", h.addNote)
	route("PATCH "+p+"/notes/{id}", h.patchNote)
	route("DELETE "+p+"/notes/{id}", h.deleteNote)
	route("PUT "+p+"/cars/{car}/verdict", h.putVerdict)
	route("DELETE "+p+"/cars/{car}/verdict", h.deleteVerdict)
	route("PUT "+p+"/cars/{car}/good-deal", h.putGoodDeal)
	route("GET "+p+"/model-families", h.modelFamilies)
	route("GET "+p+"/queue", h.queue)
	route("GET "+p+"/cars/{car}/events", h.listEvents)
	route("POST "+p+"/cars/{car}/events", h.addEvent)
	route("GET "+p+"/cars/{car}/messages", h.listMessages)
	route("POST "+p+"/messages", h.addMessage)
	route("GET "+p+"/messages/duplicates", h.messageDuplicates)
	route("PATCH "+p+"/messages/{id}", h.patchMessage)
	route("DELETE "+p+"/messages/{id}", h.deleteMessage)
	route("POST "+p+"/messages/{id}/restore", h.restoreMessage)
	route("GET "+p+"/cars/{car}/photos", h.listPhotos)
	route("POST "+p+"/cars/{car}/photos", h.addPhoto)
	route("GET "+p+"/photos/{id}", h.getPhoto)
	route("PATCH "+p+"/photos/{id}", h.patchPhoto)
	route("DELETE "+p+"/photos/{id}", h.deletePhoto)
	route("POST "+p+"/listings/upsert", h.upsertListing)
	route("GET "+p+"/listings", h.findListings)
	route("GET "+p+"/listings/{id}", h.getListing)
	route("PATCH "+p+"/listings/{id}", h.patchListing)
	route("GET "+p+"/duplicates", h.listDuplicates)
	route("POST "+p+"/duplicates/{id}/reject", h.rejectDuplicate)
	route("POST "+p+"/cars/{car}/merge", h.merge)
	route("POST "+p+"/cars/{car}/split", h.split)
	route("GET "+p+"/sellers/{id}", h.getSeller)
	route("PATCH "+p+"/sellers/{id}", h.patchSeller)
	route("GET "+p+"/activity", h.activity)
	route("/", func(w http.ResponseWriter, r *http.Request) error {
		return &store.Error{Kind: store.KindNotFound, Msg: "no route " + r.Method + " " + r.URL.Path}
	})
	return logRequests(h.auth(mux))
}

// --- middleware ------------------------------------------------------------------

func publicPath(r *http.Request) bool {
	switch r.URL.Path {
	case "/healthz", "/api/v1/health", "/api/v1/openapi.yaml":
		return true
	}
	return false
}

func (h *handler) auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if publicPath(r) {
			next.ServeHTTP(w, r)
			return
		}
		tok, _ := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
		tok = strings.TrimSpace(tok)
		name := ""
		if tok != "" {
			for n, t := range h.tokens {
				if subtle.ConstantTimeCompare([]byte(tok), []byte(t)) == 1 {
					name = n
				}
			}
		}
		if name == "" {
			w.Header().Set("WWW-Authenticate", `Bearer realm="ev-listings"`)
			writeJSON(w, http.StatusUnauthorized, api.Error{Error: "missing or invalid bearer token"})
			return
		}
		if lw, ok := w.(*logWriter); ok {
			lw.token = name
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), tokenNameKey, name)))
	})
}

type logWriter struct {
	http.ResponseWriter
	status int
	token  string
}

func (l *logWriter) WriteHeader(code int) {
	if l.status == 0 {
		l.status = code
	}
	l.ResponseWriter.WriteHeader(code)
}

func (l *logWriter) Write(b []byte) (int, error) {
	if l.status == 0 {
		l.status = http.StatusOK
	}
	return l.ResponseWriter.Write(b)
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		lw := &logWriter{ResponseWriter: w}
		next.ServeHTTP(lw, r)
		if lw.status == 0 {
			lw.status = http.StatusOK
		}
		if r.URL.Path == "/healthz" && lw.status == http.StatusOK {
			return
		}
		slog.Info("http", "method", r.Method, "path", r.URL.Path, "status", lw.status,
			"ms", time.Since(start).Milliseconds(), "token", lw.token)
	})
}

// --- helpers ---------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func writeError(w http.ResponseWriter, r *http.Request, err error) {
	var se *store.Error
	if errors.As(err, &se) {
		status := map[store.Kind]int{
			store.KindInvalid:    http.StatusUnprocessableEntity,
			store.KindBadRequest: http.StatusBadRequest,
			store.KindNotFound:   http.StatusNotFound,
			store.KindConflict:   http.StatusConflict,
			store.KindTooLarge:   http.StatusRequestEntityTooLarge,
		}[se.Kind]
		writeJSON(w, status, api.Error{Error: se.Msg})
		return
	}
	var mbe *http.MaxBytesError
	if errors.As(err, &mbe) {
		writeJSON(w, http.StatusRequestEntityTooLarge, api.Error{Error: "request body too large"})
		return
	}
	slog.Error("request failed", "method", r.Method, "path", r.URL.Path, "err", err)
	writeJSON(w, http.StatusInternalServerError, api.Error{Error: "internal error: " + err.Error()})
}

func badRequest(msg string) error { return &store.Error{Kind: store.KindBadRequest, Msg: msg} }
func invalid(msg string) error    { return &store.Error{Kind: store.KindInvalid, Msg: msg} }

// decode reads a JSON body into v; malformed JSON is a 400.
func decode(w http.ResponseWriter, r *http.Request, v any) error {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxJSONBody))
	if err != nil {
		return err
	}
	if len(strings.TrimSpace(string(body))) == 0 {
		return badRequest("request body is required")
	}
	if err := json.Unmarshal(body, v); err != nil {
		return badRequest("invalid JSON: " + err.Error())
	}
	return nil
}

// author picks body author → X-Author header → token name.
func author(r *http.Request, body string) string {
	if a := strings.TrimSpace(body); a != "" {
		return a
	}
	if a := strings.TrimSpace(r.Header.Get("X-Author")); a != "" {
		return a
	}
	name, _ := r.Context().Value(tokenNameKey).(string)
	return name
}

func pathID(r *http.Request, name string) (int64, error) {
	id, err := strconv.ParseInt(r.PathValue(name), 10, 64)
	if err != nil || id <= 0 {
		return 0, &store.Error{Kind: store.KindNotFound, Msg: name + " must be a positive integer"}
	}
	return id, nil
}

// --- handlers --------------------------------------------------------------------

func (h *handler) health(w http.ResponseWriter, r *http.Request) error {
	if err := h.st.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "version": api.Version, "error": err.Error()})
		return nil
	}
	writeJSON(w, http.StatusOK, api.Health{OK: true, Version: api.Version})
	return nil
}

func (h *handler) stats(w http.ResponseWriter, r *http.Request) error {
	st, err := h.st.Stats(r.Context())
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, st)
	return nil
}

func parseCarFilter(r *http.Request) (store.CarFilter, error) {
	q := r.URL.Query()
	f := store.CarFilter{
		Q: q.Get("q"), Make: q.Get("make"), Model: q.Get("model"), Market: q.Get("market"),
		Sort: q.Get("sort"), Order: q.Get("order"),
		Drive: q["drive"], Country: q["country"], SellerType: q["seller_type"], Status: q["status"], Verdict: q["verdict"],
		ModelFamily: q["model_family"], Tier: q["tier"],
	}
	intp := func(name string, dst **int) error {
		v := q.Get(name)
		if v == "" {
			return nil
		}
		n, err := strconv.Atoi(v)
		if err != nil {
			return badRequest(name + " must be an integer")
		}
		*dst = &n
		return nil
	}
	for name, dst := range map[string]**int{
		"hp_min": &f.HpMin, "hp_max": &f.HpMax, "year_min": &f.YearMin, "year_max": &f.YearMax, "km_max": &f.KmMax, "price_min": &f.PriceMin,
		"price_max": &f.PriceMax, "distance_km_max": &f.DistanceKmMax,
	} {
		if err := intp(name, dst); err != nil {
			return f, err
		}
	}
	boolp := func(name string) (*bool, error) {
		v := q.Get(name)
		if v == "" {
			return nil, nil
		}
		b, err := strconv.ParseBool(v)
		if err != nil {
			return nil, badRequest(name + " must be true|false")
		}
		return &b, nil
	}
	var err error
	if f.NeedsOwner, err = boolp("needs_owner"); err != nil {
		return f, err
	}
	if f.HasDuplicates, err = boolp("has_duplicates"); err != nil {
		return f, err
	}
	if f.GoodDeal, err = boolp("good_deal"); err != nil {
		return f, err
	}
	for _, name := range []string{"limit", "offset"} {
		if v := q.Get(name); v != "" {
			n, err := strconv.Atoi(v)
			if err != nil || n < 0 {
				return f, badRequest(name + " must be a non-negative integer")
			}
			if name == "limit" {
				f.Limit = n
			} else {
				f.Offset = n
			}
		}
	}
	for _, o := range q["option"] {
		of, err := store.ParseOptionFilter(o)
		if err != nil {
			return f, err
		}
		f.Options = append(f.Options, of)
	}
	return f, nil
}

func (h *handler) listCars(w http.ResponseWriter, r *http.Request) error {
	f, err := parseCarFilter(r)
	if err != nil {
		return err
	}
	out, err := h.st.ListCars(r.Context(), f)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) createCar(w http.ResponseWriter, r *http.Request) error {
	var in api.CarInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.CreateCar(r.Context(), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusCreated, out)
	return nil
}

func (h *handler) getCar(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.GetCar(r.Context(), r.PathValue("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) patchCar(w http.ResponseWriter, r *http.Request) error {
	var patch map[string]json.RawMessage
	if err := decode(w, r, &patch); err != nil {
		return err
	}
	var bodyAuthor string
	if raw, ok := patch["author"]; ok {
		_ = json.Unmarshal(raw, &bodyAuthor)
	}
	out, err := h.st.PatchCar(r.Context(), r.PathValue("car"), patch, author(r, bodyAuthor))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteCar(w http.ResponseWriter, r *http.Request) error {
	if err := h.st.DeleteCar(r.Context(), r.PathValue("car"), r.URL.Query().Get("confirm")); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) setStatus(w http.ResponseWriter, r *http.Request) error {
	var in api.StatusInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.SetStatus(r.Context(), r.PathValue("car"), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) putOption(w http.ResponseWriter, r *http.Request) error {
	var in api.OptionInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	in.Author = author(r, in.Author)
	out, err := h.st.SetOption(r.Context(), r.PathValue("car"), r.PathValue("key"), in)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteOption(w http.ResponseWriter, r *http.Request) error {
	if err := h.st.DeleteOption(r.Context(), r.PathValue("car"), r.PathValue("key"), author(r, "")); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) putFact(w http.ResponseWriter, r *http.Request) error {
	var in api.FactInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	in.Author = author(r, in.Author)
	out, err := h.st.SetFact(r.Context(), r.PathValue("car"), r.PathValue("key"), in)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteFact(w http.ResponseWriter, r *http.Request) error {
	if err := h.st.DeleteFact(r.Context(), r.PathValue("car"), r.PathValue("key"), author(r, "")); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) addAlias(w http.ResponseWriter, r *http.Request) error {
	var in api.AliasInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	id, err := h.st.AddAlias(r.Context(), r.PathValue("car"), in.Alias)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, map[string]any{"car_id": id, "alias": strings.TrimSpace(in.Alias)})
	return nil
}

func (h *handler) listNotes(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.ListNotes(r.Context(), r.PathValue("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) addNote(w http.ResponseWriter, r *http.Request) error {
	var in api.NoteInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.AddNote(r.Context(), r.PathValue("car"), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusCreated, out)
	return nil
}

func (h *handler) patchNote(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	var in api.NotePatch
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.PatchNote(r.Context(), id, in)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteNote(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	if err := h.st.DeleteNote(r.Context(), id); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) putVerdict(w http.ResponseWriter, r *http.Request) error {
	var in api.VerdictInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.SetVerdict(r.Context(), r.PathValue("car"), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteVerdict(w http.ResponseWriter, r *http.Request) error {
	if err := h.st.ClearVerdict(r.Context(), r.PathValue("car"), author(r, "")); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) putGoodDeal(w http.ResponseWriter, r *http.Request) error {
	// note: absent = keep (while staying on), "" or null = clear.
	var in struct {
		GoodDeal *bool           `json:"good_deal"`
		Note     json.RawMessage `json:"note"`
		Author   string          `json:"author"`
		At       *time.Time      `json:"at"`
	}
	if err := decode(w, r, &in); err != nil {
		return err
	}
	if in.GoodDeal == nil {
		return invalid("good_deal (boolean) is required")
	}
	var note *string
	if len(in.Note) > 0 {
		n := ""
		if string(in.Note) != "null" {
			if err := json.Unmarshal(in.Note, &n); err != nil {
				return invalid("note must be a string or null")
			}
		}
		note = &n
	}
	out, err := h.st.SetGoodDeal(r.Context(), r.PathValue("car"), *in.GoodDeal, note, author(r, in.Author), in.At)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) queue(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	f := store.QueueFilter{Tier: q["tier"], Spec: q.Get("spec"), User: q.Get("user")}
	for name, dst := range map[string]*int{"limit": &f.Limit, "offset": &f.Offset} {
		if v := q.Get(name); v != "" {
			n, err := strconv.Atoi(v)
			if err != nil || n < 0 {
				return badRequest(name + " must be a non-negative integer")
			}
			*dst = n
		}
	}
	out, err := h.st.Queue(r.Context(), f)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) modelFamilies(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.ModelFamilies(r.Context())
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) listEvents(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.ListEvents(r.Context(), r.PathValue("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) addEvent(w http.ResponseWriter, r *http.Request) error {
	var in api.EventInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, created, err := h.st.AddEvent(r.Context(), r.PathValue("car"), in, author(r, in.Author))
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

func (h *handler) listMessages(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.ListMessages(r.Context(), r.PathValue("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) addMessage(w http.ResponseWriter, r *http.Request) error {
	var in api.MessageInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, created, err := h.st.AddMessage(r.Context(), in, author(r, in.Author))
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

func (h *handler) patchMessage(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	var in api.MessagePatch
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.PatchMessage(r.Context(), id, in)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

// deleteMessage soft-deletes; reason from ?reason= (or a JSON body {"reason": …}).
func (h *handler) deleteMessage(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	reason := r.URL.Query().Get("reason")
	if r.ContentLength > 0 {
		var body struct {
			Reason string `json:"reason"`
		}
		if err := decode(w, r, &body); err != nil {
			return err
		}
		if body.Reason != "" {
			reason = body.Reason
		}
	}
	out, err := h.st.DeleteMessage(r.Context(), id, reason, author(r, ""))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) restoreMessage(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	out, err := h.st.RestoreMessage(r.Context(), id, author(r, ""))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) messageDuplicates(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.MessageDuplicates(r.Context())
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) upsertListing(w http.ResponseWriter, r *http.Request) error {
	var in api.ListingUpsert
	if err := decode(w, r, &in); err != nil {
		return err
	}
	if strings.TrimSpace(in.URL) == "" {
		return invalid("url is required")
	}
	photos, photoErrs := h.fetchPhotos(r.Context(), in.PhotoURLs)
	out, err := h.st.UpsertListing(r.Context(), in, photos, author(r, in.Author))
	if err != nil {
		return err
	}
	out.PhotoErrors = append(out.PhotoErrors, photoErrs...)
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) findListings(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	out, err := h.st.FindListings(r.Context(), q.Get("url"), q.Get("site"), q.Get("status"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) getListing(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	out, err := h.st.GetListing(r.Context(), id)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) patchListing(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	var in api.ListingPatch
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.PatchListing(r.Context(), id, in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) listDuplicates(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	out, err := h.st.ListDuplicates(r.Context(), q.Get("status"), q.Get("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) rejectDuplicate(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	out, err := h.st.RejectDuplicate(r.Context(), id)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) merge(w http.ResponseWriter, r *http.Request) error {
	var in api.MergeInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.Merge(r.Context(), r.PathValue("car"), in.From, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) split(w http.ResponseWriter, r *http.Request) error {
	var in api.SplitInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.Split(r.Context(), r.PathValue("car"), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) getSeller(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	out, err := h.st.GetSeller(r.Context(), id)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) patchSeller(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	var in api.SellerInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.PatchSeller(r.Context(), id, in, author(r, ""))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) activity(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	var since *time.Time
	if v := q.Get("since"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			return badRequest("since must be an RFC 3339 timestamp")
		}
		since = &t
	}
	limit := 100
	if v := q.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n <= 0 {
			return badRequest("limit must be a positive integer")
		}
		limit = n
	}
	out, err := h.st.Activity(r.Context(), since, limit)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

// --- photos --------------------------------------------------------------------

func (h *handler) listPhotos(w http.ResponseWriter, r *http.Request) error {
	out, err := h.st.ListPhotos(r.Context(), r.PathValue("car"))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) getPhoto(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	size := r.URL.Query().Get("size")
	if size == "" {
		size = "full"
	}
	path, sha, err := h.st.PhotoFile(r.Context(), id, size)
	if err != nil {
		return err
	}
	etag := `"` + sha + "-" + size + `"`
	w.Header().Set("ETag", etag)
	w.Header().Set("Cache-Control", "private, max-age=31536000, immutable")
	if match := r.Header.Get("If-None-Match"); match != "" && strings.Contains(match, etag) {
		w.WriteHeader(http.StatusNotModified)
		return nil
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w.Header().Set("Content-Type", "image/jpeg")
	if fi, err := f.Stat(); err == nil {
		w.Header().Set("Content-Length", strconv.FormatInt(fi.Size(), 10))
	}
	w.WriteHeader(http.StatusOK)
	_, err = io.Copy(w, f)
	if err != nil {
		slog.Warn("photo write failed", "id", id, "err", err)
	}
	return nil
}

func (h *handler) patchPhoto(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	var in api.PhotoPatch
	if err := decode(w, r, &in); err != nil {
		return err
	}
	out, err := h.st.PatchPhoto(r.Context(), id, in)
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deletePhoto(w http.ResponseWriter, r *http.Request) error {
	id, err := pathID(r, "id")
	if err != nil {
		return err
	}
	if err := h.st.DeletePhoto(r.Context(), id); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func (h *handler) profile(w http.ResponseWriter, r *http.Request) error {
	writeJSON(w, http.StatusOK, h.st.ProfileView())
	return nil
}
