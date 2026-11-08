package server

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/setup"
	"carhunt/cardb/internal/store"
)

// tokenEntry is one accepted token, kept only as its sha256 (plain legacy entries are hashed at load).
type tokenEntry struct {
	name   string
	digest []byte
}

// tokenEntries converts name → token|"sha256:<hex>" into entries.
func tokenEntries(tokens map[string]string) ([]tokenEntry, error) {
	out := make([]tokenEntry, 0, len(tokens))
	for name, t := range tokens {
		if h, ok := strings.CutPrefix(t, setup.HashPrefix); ok {
			d, err := hex.DecodeString(h)
			if err != nil || len(d) != sha256.Size {
				return nil, fmt.Errorf("token %q: bad %s<64 hex> entry", name, setup.HashPrefix)
			}
			out = append(out, tokenEntry{name, d})
			continue
		}
		sum := sha256.Sum256([]byte(t))
		out = append(out, tokenEntry{name, sum[:]})
	}
	return out, nil
}

// match returns the name of the token tok, "" when none matches. Every entry is compared (constant time).
func matchToken(entries []tokenEntry, tok string) string {
	sum := sha256.Sum256([]byte(tok))
	name := ""
	for _, e := range entries {
		if subtle.ConstantTimeCompare(sum[:], e.digest) == 1 {
			name = e.name
		}
	}
	return name
}

const viewerKey ctxKey = 1

func tokenName(r *http.Request) string {
	name, _ := r.Context().Value(tokenNameKey).(string)
	return name
}

func isViewer(r *http.Request) bool {
	v, _ := r.Context().Value(viewerKey).(bool)
	return v
}

// viewerToken reports whether the token name is a configured viewer (read-only + own verdict).
func (h *handler) viewerToken(name string) bool {
	u, ok := h.st.Profile().User(name)
	return ok && u.Role == "viewer"
}

// viewerAllowed: a viewer token may read anything and set/clear a verdict (whose — checked by the handler).
func viewerAllowed(r *http.Request) bool {
	switch r.Method {
	case http.MethodGet, http.MethodHead:
		return true
	case http.MethodPut, http.MethodDelete:
		p := strings.Split(strings.Trim(r.URL.Path, "/"), "/") // api v1 cars {car} verdict
		return len(p) == 5 && p[0] == "api" && p[1] == "v1" && p[2] == "cars" && p[4] == "verdict"
	}
	return false
}

func forbidden(w http.ResponseWriter, msg string) {
	writeJSON(w, http.StatusForbidden, api.Error{Error: msg})
}

// queryUser canonicalises `?user=` for reads ("" = owner; unknown → 400).
func (h *handler) queryUser(r *http.Request) (string, error) {
	name := strings.TrimSpace(r.URL.Query().Get("user"))
	if name == "" {
		return "", nil
	}
	n, err := h.st.UserName(r.Context(), name)
	if store.IsKind(err, store.KindInvalid) {
		return "", badRequest(err.Error())
	}
	return n, err
}

// verdictUser resolves whose verdict a PUT/DELETE changes: body `user` > `?user=` > the token's user > the owner.
// Unknown user → 422; a viewer token naming someone else → 403 (ok = false, response written).
func (h *handler) verdictUser(w http.ResponseWriter, r *http.Request, body string) (string, bool, error) {
	name := strings.TrimSpace(body)
	if name == "" {
		name = strings.TrimSpace(r.URL.Query().Get("user"))
	}
	if name == "" {
		if u, ok := h.st.Profile().User(tokenName(r)); ok {
			name = u.Name
		}
	}
	canon, err := h.st.UserName(r.Context(), name)
	if err != nil {
		return "", false, err
	}
	if isViewer(r) && !strings.EqualFold(canon, tokenName(r)) {
		forbidden(w, fmt.Sprintf("token %s may only change its own verdict, not %s's", tokenName(r), canon))
		return "", false, nil
	}
	return canon, true, nil
}

func (h *handler) putVerdict(w http.ResponseWriter, r *http.Request) error {
	var in api.VerdictInput
	if err := decode(w, r, &in); err != nil {
		return err
	}
	user, ok, err := h.verdictUser(w, r, in.User)
	if err != nil || !ok {
		return err
	}
	in.User = user
	out, err := h.st.SetVerdict(r.Context(), r.PathValue("car"), in, author(r, in.Author))
	if err != nil {
		return err
	}
	writeJSON(w, http.StatusOK, out)
	return nil
}

func (h *handler) deleteVerdict(w http.ResponseWriter, r *http.Request) error {
	user, ok, err := h.verdictUser(w, r, "")
	if err != nil || !ok {
		return err
	}
	if err := h.st.ClearVerdict(r.Context(), r.PathValue("car"), user, author(r, "")); err != nil {
		return err
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}
