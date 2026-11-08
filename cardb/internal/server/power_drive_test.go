package server

import (
	"carhunt/cardb/internal/api"
	"testing"
)

func TestPowerAndDriveFilters(t *testing.T) {
	c := newServer(t)
	add := func(tag string, kw any, drive any) int64 {
		return c.upsert(map[string]any{"url": "https://example.invalid/" + tag, "make": tag, "power_kw": kw, "drive": drive}).CarID
	}
	a := add("rear", 150, "rwd")
	b := add("all", 220, "awd")
	missing := add("missing", nil, nil)
	explicit := add("unknown", 125.4, "unknown")
	empty := add("empty", 100, "")
	check := func(q string, ids ...int64) {
		t.Helper()
		var got api.CarList
		c.call("GET", "/api/v1/cars?sort=model&"+q, nil, 200, &got)
		if got.Total != len(ids) {
			t.Fatalf("%s: total %d, want %d: %+v", q, got.Total, len(ids), got.Cars)
		}
		want := map[int64]bool{}
		for _, id := range ids {
			want[id] = true
		}
		for _, car := range got.Cars {
			if !want[car.ID] {
				t.Fatalf("%s: unexpected car %d", q, car.ID)
			}
		}
	}
	check("hp_min=204&hp_max=204", a)
	check("hp_min=171&hp_max=171", explicit)
	check("hp_max=171", explicit, empty)
	check("hp_min=205", b)
	check("drive=rwd&drive=awd", a, b)
	check("drive=unknown", missing, explicit, empty)
	check("drive=RWD&hp_min=204&hp_max=204", a)
	check("drive=awd&hp_max=204")
	check("hp_min=0", a, b, explicit, empty)
	var got api.CarList
	c.call("GET", "/api/v1/cars?drive=rwd", nil, 200, &got)
	if got.Cars[0].Drive == nil || *got.Cars[0].Drive != "rwd" || *got.Cars[0].PowerKw != 150 {
		t.Fatal("drive and original kW must remain available")
	}
	for _, q := range []string{"hp_min=-1", "hp_max=abc", "hp_min=205&hp_max=204", "drive=4wd", "hp_min=1.5"} {
		c.call("GET", "/api/v1/cars?"+q, nil, 400, nil)
	}
}
