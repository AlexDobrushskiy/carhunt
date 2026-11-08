package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"carhunt/cardb/internal/api"
)

// TestProdSmoke checks the deployed server after an import, through the real CLI and the
// real client config: the MINI Countryman (StandVirtual IDsynMn01) must show its listing,
// the owner's verdict and the full seller chat in both directions.
// Run: CARDB_SMOKE=1 go test ./internal/cli -run TestProdSmoke -v
func TestProdSmoke(t *testing.T) {
	if os.Getenv("CARDB_SMOKE") == "" {
		t.Skip("set CARDB_SMOKE=1 to run against the configured server")
	}
	var out, errb bytes.Buffer
	if code := Run(context.Background(), []string{"show", "pt-testcar-lisbon", "--json"}, &out, &errb); code != ExitOK {
		t.Fatalf("show exit %d: %s", code, errb.String())
	}
	var car api.CarDetail
	if err := json.Unmarshal(out.Bytes(), &car); err != nil {
		t.Fatalf("decode: %v", err)
	}
	var listing *api.Listing
	for i := range car.Listings {
		if car.Listings[i].SiteRef != nil && *car.Listings[i].SiteRef == "IDsynMn01" {
			listing = &car.Listings[i]
		}
	}
	if listing == nil {
		t.Fatalf("no StandVirtual IDsynMn01 listing on car %d", car.ID)
	}
	if car.Verdict == nil || car.Verdict.Value == "" {
		t.Fatalf("car %d has no verdict", car.ID)
	}
	in, outMsgs := 0, 0
	for _, m := range car.Messages {
		if m.Direction == "in" {
			in++
		} else {
			outMsgs++
		}
	}
	if in < 3 || outMsgs < 3 {
		t.Fatalf("chat incomplete: %d in, %d out", in, outMsgs)
	}
	if !strings.Contains(strings.ToLower(car.Title), "countryman") {
		t.Fatalf("unexpected car title %q", car.Title)
	}
	t.Logf("car %d %q: listing %s, verdict %s, %d in / %d out messages, %d photos",
		car.ID, car.Title, listing.URL, car.Verdict.Value, in, outMsgs, len(car.Photos))
}
