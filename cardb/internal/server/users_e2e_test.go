package server

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"slices"
	"testing"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/profile"
	"carhunt/cardb/internal/setup"
	"carhunt/cardb/internal/store"
)

const usersProfile = `
owner: {name: Sam}
cardb:
  users: [{name: Bea, role: viewer}]
`

// newUsersServer: owner Sam + viewer Bea; tokens agents (plain), Sam (hashed), Bea (viewer).
func newUsersServer(t *testing.T) (agents, owner, viewer *client) {
	t.Helper()
	dir := t.TempDir()
	st, err := store.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	p, err := profile.Parse([]byte(usersProfile))
	if err != nil {
		t.Fatal(err)
	}
	if err := st.SetProfile(p); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(NewHandler(st, map[string]string{
		"agents": "tok-agents", "Sam": setup.HashToken("tok-sam"), "Bea": "tok-bea"}))
	t.Cleanup(srv.Close)
	c := &client{t: t, base: srv.URL, token: "tok-agents", dir: dir}
	o, v := *c, *c
	o.token, v.token = "tok-sam", "tok-bea"
	return c, &o, &v
}

func usersCar(c *client, tag string) int64 {
	c.t.Helper()
	return c.upsert(map[string]any{
		"url": "https://example.invalid/users/" + tag, "make": "VW", "model": "ID.4 Pro", "reg_date": "2024-03", "km": 20000,
		"price": 35000, "power_kw": 210, "drive": "rwd", "country": "PT", "city": "Porto",
	}).CarID
}

func usersQueue(c *client, query string) []int64 {
	c.t.Helper()
	var q api.Queue
	c.call("GET", "/api/v1/queue?"+query, nil, 200, &q)
	out := []int64{}
	for _, it := range q.Items {
		out = append(out, it.Car.ID)
	}
	return out
}

func listIDs(l api.CarList) []int64 {
	out := []int64{}
	for _, c := range l.Cars {
		out = append(out, c.ID)
	}
	return out
}

// TestPerUserVerdicts: owner and viewer rate the same car differently; reads default to the owner's verdict,
// ?user= picks another; viewer tokens are read-only except their own verdict; the queue is per user.
func TestPerUserVerdicts(t *testing.T) {
	agents, owner, viewer := newUsersServer(t)
	both, ownerOnly, none := usersCar(agents, "both"), usersCar(agents, "owner-only"), usersCar(agents, "none")
	vpath := func(id int64) string { return fmt.Sprintf("/api/v1/cars/%d/verdict", id) }

	var v api.Verdict
	agents.call("PUT", vpath(both), map[string]any{"value": "up"}, 200, &v) // agents token → the owner
	if v.User != "Sam" || v.Value != "up" || v.Author != "agents" {
		t.Fatalf("agents verdict = %+v", v)
	}
	viewer.call("PUT", vpath(both), map[string]any{"value": "down", "note": "too big", "author": "Sam"}, 200, &v)
	if v.User != "Bea" || v.Value != "down" || v.Author != "Bea" { // a viewer token always writes as itself
		t.Fatalf("viewer verdict = %+v", v)
	}
	owner.call("PUT", vpath(ownerOnly), map[string]any{"value": "maybe"}, 200, &v) // owner token → the owner
	if v.User != "Sam" || v.Author != "Sam" {
		t.Fatalf("owner-token verdict = %+v", v)
	}

	d := agents.car(both)
	if d.Verdict == nil || d.Verdict.User != "Sam" || d.Verdict.Value != "up" || len(d.Verdicts) != 2 || d.Verdicts["Bea"].Value != "down" {
		t.Fatalf("detail verdicts: %+v %+v", d.Verdict, d.Verdicts)
	}
	var b api.CarDetail
	agents.call("GET", fmt.Sprintf("/api/v1/cars/%d?user=bea", both), nil, 200, &b)
	if b.Verdict == nil || b.Verdict.User != "Bea" || b.Verdict.Value != "down" {
		t.Fatalf("?user=bea verdict: %+v", b.Verdict)
	}
	var u api.CarDetail
	viewer.call("GET", fmt.Sprintf("/api/v1/cars/%d", none), nil, 200, &u)
	if u.Verdict != nil || u.Verdicts == nil || len(u.Verdicts) != 0 {
		t.Fatalf("unrated car: %+v %+v", u.Verdict, u.Verdicts)
	}

	if got := listIDs(agents.list("verdict=down")); len(got) != 0 {
		t.Fatalf("owner's down list = %v", got)
	}
	if got := listIDs(agents.list("verdict=down&user=Bea")); !slices.Equal(got, []int64{both}) {
		t.Fatalf("Bea's down list = %v", got)
	}
	if got := listIDs(agents.list("verdict=none&user=Bea")); len(got) != 2 || slices.Contains(got, both) {
		t.Fatalf("Bea's unrated list = %v", got)
	}
	for _, c := range agents.list("user=Bea").Cars {
		if c.ID == both && (c.Verdict == nil || c.Verdict.User != "Bea" || c.Verdicts["Sam"] == nil) {
			t.Fatalf("list row for Bea: %+v %+v", c.Verdict, c.Verdicts)
		}
	}
	var st api.Stats
	agents.call("GET", "/api/v1/stats", nil, 200, &st)
	if st.ByVerdict["up"] != 1 || st.ByVerdict["maybe"] != 1 || st.ByVerdict["down"] != 0 || st.ByVerdict["none"] != 1 {
		t.Fatalf("owner stats: %v", st.ByVerdict)
	}
	agents.call("GET", "/api/v1/stats?user=Bea", nil, 200, &st)
	if st.ByVerdict["down"] != 1 || st.ByVerdict["none"] != 2 {
		t.Fatalf("Bea stats: %v", st.ByVerdict)
	}

	// Viewer token: read-only except its own verdict.
	viewer.call("PATCH", fmt.Sprintf("/api/v1/cars/%d", both), map[string]any{"km": 1}, 403, nil)
	viewer.call("POST", fmt.Sprintf("/api/v1/cars/%d/notes", both), map[string]any{"text": "hi"}, 403, nil)
	viewer.call("PUT", vpath(none), map[string]any{"value": "up", "user": "Sam"}, 403, nil)
	viewer.call("PUT", vpath(none)+"?user=Sam", map[string]any{"value": "up"}, 403, nil)
	viewer.call("DELETE", vpath(both)+"?user=Sam", nil, 403, nil)
	viewer.call("GET", "/api/v1/queue", nil, 200, nil)
	agents.call("PUT", vpath(none), map[string]any{"value": "up", "user": "nobody"}, 422, nil)
	agents.call("DELETE", vpath(none)+"?user=nobody", nil, 422, nil)
	agents.call("GET", "/api/v1/cars?user=nobody", nil, 400, nil)

	// Queue: eligible = not rated by that user.
	if got := usersQueue(agents, ""); !slices.Equal(got, []int64{none}) {
		t.Fatalf("owner queue = %v", got)
	}
	if got := usersQueue(agents, "user=Bea"); len(got) != 2 || !slices.Contains(got, ownerOnly) || !slices.Contains(got, none) {
		t.Fatalf("Bea's queue = %v (must keep the car only the owner rated)", got)
	}

	// Events carry the user; clearing one user's verdict keeps the other's.
	viewer.call("DELETE", vpath(both), nil, 204, nil)
	d = agents.car(both)
	if d.Verdict == nil || d.Verdict.User != "Sam" || len(d.Verdicts) != 1 {
		t.Fatalf("after Bea cleared: %+v %+v", d.Verdict, d.Verdicts)
	}
	var users []string
	for _, e := range agents.events(both) {
		if e.Type == "verdict" {
			var data map[string]any
			_ = json.Unmarshal(e.Data, &data)
			users = append(users, fmt.Sprint(data["user"]))
		}
	}
	if !slices.Equal(users, []string{"Bea", "Bea", "Sam"}) {
		t.Fatalf("verdict event users (newest first) = %v", users)
	}

	// author_kind: owner / viewer by name (case-insensitive), else agent.
	var n api.Note
	for author, want := range map[string]string{"sam": "owner", "BEA": "viewer", "deal-finder": "agent", "import-x": "import"} {
		agents.call("POST", fmt.Sprintf("/api/v1/cars/%d/notes", none), map[string]any{"text": "n", "author": author}, 201, &n)
		if n.AuthorKind != want {
			t.Errorf("author %s: author_kind %s, want %s", author, n.AuthorKind, want)
		}
	}
	// A wrong token is still 401; a hashed token works.
	bad := *agents
	bad.token = "sha256:" + setup.HashToken("tok-sam")[7:]
	bad.call("GET", "/api/v1/stats", nil, 401, nil)
	owner.call("GET", "/api/v1/stats", nil, 200, nil)
}
