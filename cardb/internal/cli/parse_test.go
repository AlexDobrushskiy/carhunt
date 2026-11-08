package cli

import "testing"

func TestParseEvidence(t *testing.T) {
	cases := []struct{ in, key, val, src, ref string }{
		{"pano=yes:ad_text:Teto: panorâmico", "pano", "yes", "ad_text", "Teto: panorâmico"},
		{"warranty=to 2028-11:seller_said", "warranty", "to 2028-11", "seller_said", ""},
		{"service=at 10:00 Monday:seller_said:msg 3", "service", "at 10:00 Monday", "seller_said", "msg 3"},
		{"note=ratio 1:2", "note", "ratio 1:2", "", ""},
		{"power-tailgate=y", "power_tailgate", "y", "", ""},
	}
	for _, c := range cases {
		ev, err := parseEvidence(c.in, "")
		if err != nil || ev.Key != c.key || ev.Value != c.val || ev.Source != c.src || ev.Ref != c.ref {
			t.Errorf("%q → %+v, %v", c.in, ev, err)
		}
	}
}

func TestInterspersedFlags(t *testing.T) {
	e := &env{}
	f := newFlags(e, "note")
	pin := f.Bool("pin", false, "")
	pos, err := f.parse([]string{"12", "--pin", "text", "--json", "--", "--not-a-flag"})
	if err != nil || !*pin || !e.json || len(pos) != 3 || pos[2] != "--not-a-flag" {
		t.Fatalf("pos=%v pin=%v json=%v err=%v", pos, *pin, e.json, err)
	}
}

func TestLenientValues(t *testing.T) {
	for in, want := range map[string]int{"34 600 €": 34600, "31.200 km": 31200, "€29,500": 29500} {
		if n, err := parseIntLenient(in); err != nil || n != want {
			t.Errorf("%q → %d %v", in, n, err)
		}
	}
	for in, want := range map[string]string{"07/2023": "2023-07", "2024-05": "2024-05", "3.5.2022": "2022-05-03"} {
		if s, err := normalizeRegDate(in); err != nil || s != want {
			t.Errorf("%q → %q %v", in, s, err)
		}
	}
}
