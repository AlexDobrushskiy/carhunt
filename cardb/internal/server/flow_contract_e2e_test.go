package server

import (
	"encoding/json"
	"strconv"
	"testing"

	"carhunt/cardb/internal/api"
)

// What discover, contact and vet rely on (docs/{discover,contact,vetbuy}.md), in one place.
func TestFlowContract(t *testing.T) {
	c := newServer(t)
	sv := "https://www.standvirtual.com/carros/anuncio/syn-car-IDsynMn01.html"
	res := c.upsert(map[string]any{"url": sv, "make": "Volkswagen", "model": "ID.4",
		"seller": map[string]any{"type": "private", "contacts": []map[string]any{{"kind": "phone", "value": "+351555000777"}}}})
	other := c.upsert(map[string]any{"url": "https://www.olx.pt/d/anuncio/syn-other-IDJx7Yz.html", "make": "Skoda"})

	// GET /listings: by URL (any slug), by site_ref (cardb's URL-derived ref); site alone lists the site.
	var ls []api.Listing
	c.call("GET", "/api/v1/listings?url=https://standvirtual.com/carros/anuncio/other-slug-IDsynMn01.html", nil, 200, &ls)
	if len(ls) != 1 || ls[0].CarID != res.CarID {
		t.Fatalf("by url: %+v", ls)
	}
	c.call("GET", "/api/v1/listings?site=StandVirtual&site_ref=IDsynMn01", nil, 200, &ls)
	if len(ls) != 1 || ls[0].CarID != res.CarID {
		t.Fatalf("by site_ref: %+v", ls)
	}
	c.call("GET", "/api/v1/listings?site_ref=IDnope", nil, 200, &ls)
	if len(ls) != 0 {
		t.Fatalf("unknown site_ref matched: %+v", ls)
	}

	// POST /messages: body is the Message, car_id at top level; 201 created, 200 dedupe (same dedupe_key).
	msg := map[string]any{"car": res.CarID, "channel": "whatsapp", "direction": "out", "text": "Olá",
		"counterpart": "+351555000777", "delivery": "sent", "dedupe_key": "snd:1.000:abcd"}
	var m api.Message
	c.call("POST", "/api/v1/messages", msg, 201, &m)
	if m.CarID != res.CarID {
		t.Fatalf("message car_id %d", m.CarID)
	}
	c.call("POST", "/api/v1/messages", msg, 200, &m)
	if m.MatchedBy != "dedupe_key" || m.CarID != res.CarID {
		t.Fatalf("dedupe: %+v", m)
	}
	// the Message shape (car_id) is accepted as input too
	c.call("POST", "/api/v1/messages", map[string]any{"car_id": res.CarID, "channel": "email", "direction": "in",
		"text": "Bom dia", "counterpart": "seller@example.invalid"}, 201, &m)
	if m.CarID != res.CarID {
		t.Fatalf("car_id alias: %d", m.CarID)
	}
	// inbound by counterpart only (the watcher): car resolved from the seller contact
	c.call("POST", "/api/v1/messages", map[string]any{"channel": "whatsapp", "direction": "in", "text": "Sim",
		"counterpart": "+351 555 000 777", "external_id": "wa-1"}, 201, &m)
	if m.CarID != res.CarID {
		t.Fatalf("inbound car_id %d", m.CarID)
	}

	// vet / buy event types are free-form strings; ask ↔ ask_answered carry data.topic / data.ask_event.
	var ask api.Event
	c.call("POST", "/api/v1/cars/"+itoa(res.CarID)+"/events", map[string]any{"type": "ask",
		"summary": "Could you send the VIN?", "data": map[string]any{"topic": "vin"}, "dedupe_key": "ask:1:vin:1"}, 201, &ask)
	for _, typ := range []string{"ask_answered", "vin_check", "contract", "deposit", "pickup", "import", "shutdown"} {
		c.call("POST", "/api/v1/cars/"+itoa(res.CarID)+"/events", map[string]any{"type": typ, "summary": typ,
			"data": map[string]any{"topic": "vin", "ask_event": ask.ID}}, 201, nil)
	}
	evs := c.events(res.CarID)
	if a := eventsOfType(evs, "ask_answered"); len(a) != 1 {
		t.Fatalf("ask_answered: %+v", a)
	} else {
		var d map[string]any
		_ = json.Unmarshal(a[0].Data, &d)
		if d["topic"] != "vin" || d["ask_event"] != float64(ask.ID) {
			t.Fatalf("ask_answered data %v", d)
		}
	}

	// statuses vet/buy use; facts with source owner; battery_soh as a health fact
	for _, st := range []string{"talking", "ready_to_visit", "bought"} {
		c.call("POST", "/api/v1/cars/"+itoa(other.CarID)+"/status", map[string]any{"status": st}, 200, nil)
	}
	c.call("PUT", "/api/v1/cars/"+itoa(res.CarID)+"/facts/battery_soh", map[string]any{"value": "94 % (dealer cert)", "source": "owner"}, 200, nil)
	c.call("PUT", "/api/v1/cars/"+itoa(res.CarID)+"/facts/battery_soh", map[string]any{"value": "x", "source": "Somebody"}, 422, nil)

	// list rows carry version (CarSummary.version is required in the openapi)
	for _, row := range c.list("").Cars {
		if row.Version < 1 {
			t.Fatalf("car %d listed without version", row.ID)
		}
	}
}

func itoa(n int64) string { return strconv.FormatInt(n, 10) }
