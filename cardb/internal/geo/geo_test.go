package geo

import "testing"

func TestNormalizePhone(t *testing.T) {
	for _, c := range []struct{ in, home, want string }{
		{"555 010 203", "PT", "351555010203"}, // national, PT home
		{"+351 555 010 203", "PT", "351555010203"},
		{"00351555010203", "PT", "351555010203"},
		{"351555010203", "PT", "351555010203"}, // stored form stays
		{"351555010203", "", "351555010203"},
		{"555 010 203", "", "555010203"}, // no home: digits only
		{"+34 555 010 203", "PT", "34555010203"},
		{"34555010203", "PT", "34555010203"},
		{"555 010 203", "ES", "34555010203"},
		{"06 12 34 56 78", "FR", "33612345678"},  // trunk 0 dropped
		{"0151 23456789", "DE", "4915123456789"}, // trunk 0, 11-digit NSN
		{"(+49) 555 2345678", "PT", "495552345678"},
		{"333 1234567", "IT", "393331234567"},   // no trunk in IT
		{"02 1234 5678", "IT", "390212345678"},  // IT keeps the leading 0
		{"06 30 123 4567", "HU", "36301234567"}, // HU trunk 06
		{"12345", "PT", "12345"},                // fits nothing: unchanged
	} {
		if got := NormalizePhone(c.in, c.home); got != c.want {
			t.Errorf("NormalizePhone(%q, %q) = %q, want %q", c.in, c.home, got, c.want)
		}
		// Idempotent on the stored form.
		if got := NormalizePhone(c.want, c.home); got != c.want && c.want != "12345" {
			t.Errorf("not idempotent: %q → %q", c.want, got)
		}
	}
}

func TestRegionOf(t *testing.T) {
	codes := []string{"PT-20", "PT-30", "ES-CN", "ES-IB", "IT-82"}
	for city, want := range map[string]string{
		"Funchal (Madeira)": "PT-30", "Las Palmas De Gran Canaria": "ES-CN", "Ponta Delgada": "PT-20", "Santa Cruz De Tenerife": "ES-CN",
		"AÇORES": "PT-20", "Angra do Heroísmo, Azores": "PT-20", "Arrecife, Lanzarote": "ES-CN", "Puerto del Rosario (Fuerteventura)": "ES-CN",
		"Islas Canarias": "ES-CN", "Canary Islands": "ES-CN", "Palma de Mallorca": "ES-IB", "Catania": "IT-82",
		"Porto": "", "Palmela": "", "Las Rozas de Madrid": "", "Madrid": "", "Tenerias": "", "": "", "Funchalinho": "", "Santa Cruz": "",
	} {
		if got := RegionOf("", city, codes); got != want {
			t.Errorf("%q: got %q, want %q", city, got, want)
		}
	}
	if got := RegionOf("PT", "Las Palmas", codes); got != "" {
		t.Errorf("country mismatch matched %q", got)
	}
	if got := RegionOf("ES", "Tenerife", []string{"PT-30"}); got != "" {
		t.Errorf("region not asked for matched %q", got)
	}
}

func TestMentionedCountry(t *testing.T) {
	codes := []string{"PL", "LT", "LV", "EE"}
	for v, want := range map[string]string{
		"Imported from Poland (ad)": "PL", "importado da Polónia": "PL", "aus Polen importiert": "PL", "polnische Erstzulassung": "PL",
		"Polish plates on photo 3": "PL", "importé de Pologne": "PL", "importato dalla Polonia, targa polacca": "PL", "coche polaco": "PL",
		"zarejestrowany w Polska": "PL", "ex Lithuania": "LT", "importado da Lituânia": "LT", "aus Litauen": "LT", "litauische Papiere": "LT",
		"Lietuvos registracija": "LT", "Carfax: registered in Latvija 2023": "LV", "aus Lettland": "LV", "importado de Letonia": "LV",
		"importado da Letónia": "LV", "importée de Lettonie": "LV", "Estonian first registration": "EE", "aus Estland": "EE",
		"importado de Estonia": "EE", "Eesti numbrimärk": "EE", "estnische Zulassung": "EE", "Imported from Germany; earlier in Polen": "PL",
	} {
		if got := MentionedCountry(v, codes); got != want {
			t.Errorf("%q: got %q, want %q", v, got, want)
		}
	}
	for _, v := range []string{"speaks DE/RU/EN/PL", "filtro de polen nuevo", "filtro de pólen trocado", "fresh polish, polished paint",
		"Imported from Germany (ad)", "importado", "yes (leboncoin is_import)", "Estoril", "lettering on tailgate", "establishment",
		"Polanco, Santander", "Estrela", "Latvianism"} {
		if got := MentionedCountry(v, codes); got != "" {
			t.Errorf("%q: got %q, want none", v, got)
		}
	}
	if got := MentionedCountry("Imported from Poland", []string{"LT"}); got != "" {
		t.Errorf("only the asked countries: %q", got)
	}
}

func TestGreatCircle(t *testing.T) {
	// Lisbon → Madrid ≈ 503 km.
	if d := GreatCircleKm(Point{38.72, -9.14}, Point{40.42, -3.70}); d < 495 || d > 510 {
		t.Fatalf("got %v", d)
	}
	for c := range Dialings {
		if _, ok := Centroids[c]; !ok {
			t.Errorf("no centroid for %s", c)
		}
	}
}
