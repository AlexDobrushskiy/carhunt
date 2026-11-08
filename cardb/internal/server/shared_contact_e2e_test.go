package server

import (
	"fmt"
	"testing"

	"carhunt/cardb/internal/api"
)

// A portal call-centre number printed on many dealers' ads (AutoScout24 Spain's WhatsApp) must not merge those
// dealers into one seller.
func TestSharedContactDoesNotMergeSellers(t *testing.T) {
	c := newServer(t)
	const callCentre = "+34 555 37 52 15"
	dealer := func(company, phone string) map[string]any {
		return map[string]any{"company": company, "type": "dealer", "contacts": []map[string]any{
			{"kind": "phone", "value": phone}, {"kind": "whatsapp", "value": callCentre}}}
	}
	up := func(url, model string, seller map[string]any) api.CarDetail {
		r := c.upsert(map[string]any{"url": url, "make": "VW", "model": model, "km": 20000, "seller": seller})
		return c.car(r.CarID)
	}
	a := up("https://www.autoscout24.es/anuncios/vw-id-4-aaaaaaaa-1111-1111-1111-111111111111", "ID.4 Pro", dealer("SYNTH MOTOR NORTE", "+34 555 000 001"))
	b := up("https://www.autoscout24.es/anuncios/vw-id-5-bbbbbbbb-2222-2222-2222-222222222222", "ID.5 Pro", dealer("SYNTH CARS SUR", "+34 555 000 002"))
	d := up("https://www.autoscout24.es/anuncios/vw-id-4-dddddddd-4444-4444-4444-444444444444", "ID.4 GTX", dealer("SYNTH AUTO OESTE", "+34 555 000 004"))

	if a.Seller.ID == b.Seller.ID || a.Seller.ID == d.Seller.ID || b.Seller.ID == d.Seller.ID {
		t.Fatalf("different dealers share a seller through the call-centre number: %d %d %d", a.Seller.ID, b.Seller.ID, d.Seller.ID)
	}
	for _, car := range []api.CarDetail{a, b, d} {
		var s api.Seller
		c.call("GET", fmt.Sprintf("/api/v1/sellers/%d", car.Seller.ID), nil, 200, &s)
		own, shared := 0, 0
		for _, ct := range s.Contacts {
			if ct.Value == "34555375215" {
				if !ct.Shared { // flagged
					t.Fatalf("seller %d (%v): call-centre number not flagged shared: %+v", s.ID, *s.Company, ct)
				}
				shared++
			} else {
				own++
			}
		}
		if own != 1 || shared != 1 {
			t.Fatalf("seller %d (%v) contacts = %+v, want its own phone + the flagged call-centre number", s.ID, *s.Company, s.Contacts)
		}
	}
	var sa api.Seller
	c.call("GET", fmt.Sprintf("/api/v1/sellers/%d", a.Seller.ID), nil, 200, &sa)
	if *sa.Company != "SYNTH MOTOR NORTE" {
		t.Fatalf("first dealer renamed: %v", *sa.Company)
	}

	// A later ad of the same dealer still finds its seller by its own phone.
	a2 := up("https://www.autoscout24.es/anuncios/vw-id-5-eeeeeeee-5555-5555-5555-555555555555", "ID.5 GTX", dealer("SYNTH MOTOR NORTE", "+34 555 000 001"))
	if a2.Seller.ID != a.Seller.ID {
		t.Fatalf("same dealer got a new seller: %d vs %d", a2.Seller.ID, a.Seller.ID)
	}
	// An unnamed ad carrying only the call-centre number joins nobody.
	n := up("https://www.autoscout24.es/anuncios/vw-id-4-ffffffff-6666-6666-6666-666666666666", "ID.4 Pure",
		map[string]any{"type": "dealer", "contacts": []map[string]any{{"kind": "whatsapp", "value": callCentre}}})
	if n.Seller == nil || n.Seller.ID == a.Seller.ID || n.Seller.ID == b.Seller.ID || n.Seller.ID == d.Seller.ID {
		t.Fatalf("unnamed call-centre-only ad seller = %+v", n.Seller)
	}
	// Branches of one group sharing a real number stay one seller (name contains the other).
	g1 := up("https://www.autoscout24.es/anuncios/vw-id-4-99999999-7777-7777-7777-777777777777", "ID.4 Pro", dealer("GRUPO SYNTH AUTOMÓVILES", "+34 555 851 117"))
	g2 := up("https://www.autoscout24.es/anuncios/vw-id-5-99999999-8888-8888-8888-888888888888", "ID.5 Pro",
		map[string]any{"company": "GRUPO SYNTH AUTOMÓVILES- NORTE", "type": "dealer", "contacts": []map[string]any{{"kind": "phone", "value": "+34 555 851 117"}}})
	if g1.Seller.ID != g2.Seller.ID {
		t.Fatalf("one dealer group split into two sellers: %d vs %d", g1.Seller.ID, g2.Seller.ID)
	}

	// A message to the shared number can't be routed to one car.
	c.call("POST", "/api/v1/messages", map[string]any{"to": callCentre, "channel": "whatsapp", "direction": "in", "text": "hola"}, 422, nil)
	// Shared numbers are no duplicate evidence: the two ID.4 Pro ads of different dealers are not proposed on the phone.
	for _, dp := range c.car(a.ID).Duplicates {
		for _, r := range dp.Reasons {
			if r == "same seller phone 34555375215" {
				t.Fatalf("duplicate proposed on the call-centre number: %+v", dp)
			}
		}
	}
}
