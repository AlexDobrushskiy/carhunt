package store

import "testing"

func TestFamily(t *testing.T) {
	cases := []struct{ make, model, variant, want string }{
		// every make/model pair in the live data
		{"Audi", "Q4", "", "Audi Q4"},
		{"Audi", "Q4 e-tron", "", "Audi Q4"},
		{"Audi", "Q4 e-tron 40", "", "Audi Q4"},
		{"Audi", "Q4 e-tron 45", "", "Audi Q4"},
		{"Audi", "Q4 e-tron 45 quattro", "", "Audi Q4"},
		{"Audi", "Q4 e-tron 50", "", "Audi Q4"},
		{"Audi", "Q4 e-tron 50 quattro", "", "Audi Q4"},
		{"Audi", "Q4 Sportback e-tron", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 40", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 45", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 45 quattro", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 50", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 50 quattro", "", "Audi Q4 Sportback"},
		{"Audi", "Q4 Sportback e-tron 55", "", "Audi Q4 Sportback"},
		{"BMW", "iX1", "", "BMW iX1"},
		{"BMW", "iX1 eDrive20", "", "BMW iX1"},
		{"BMW", "iX1 xDrive30", "", "BMW iX1"},
		{"BMW", "iX2 eDrive20", "", "BMW iX2"},
		{"BMW", "iX3", "", "BMW iX3"},
		{"BYD", "Seal U", "", "BYD Seal U"},
		{"Cupra", "Tavascan", "", "Cupra Tavascan"},
		{"Hyundai", "IONIQ 5", "", "Hyundai Ioniq 5"},
		{"Hyundai", "Ioniq 5", "", "Hyundai Ioniq 5"},
		{"Hyundai", "Kona Electric", "", "Hyundai Kona Electric"},
		{"KGM", "Torres EVX", "", "KGM Torres EVX"},
		{"Kia", "EV6", "", "Kia EV6"},
		{"Kia", "EV6 GT", "", "Kia EV6"},
		{"Kia", "EV6 GT-Line", "", "Kia EV6"},
		{"MINI", "Countryman", "", "MINI Countryman"},
		{"MINI", "Countryman E", "", "MINI Countryman"},
		{"MINI", "Countryman E (Cooper)", "", "MINI Countryman"},
		{"MINI", "Countryman E/SE", "", "MINI Countryman"},
		{"MINI", "Countryman SE", "", "MINI Countryman"},
		{"Mercedes", "EQA", "", "Mercedes EQA"},
		{"Mercedes", "EQA 250", "", "Mercedes EQA"},
		{"Mercedes", "EQA 250+", "", "Mercedes EQA"},
		{"Mercedes", "EQA 300", "", "Mercedes EQA"},
		{"Mercedes", "EQA 350", "", "Mercedes EQA"},
		{"Mercedes", "EQA 350 4Matic", "", "Mercedes EQA"},
		{"Mercedes", "EQB", "", "Mercedes EQB"},
		{"Mercedes", "EQB 250", "", "Mercedes EQB"},
		{"Mercedes", "EQB 250+", "", "Mercedes EQB"},
		{"Mercedes", "EQB 250+ Advanced", "", "Mercedes EQB"},
		{"Mercedes", "EQB 300", "", "Mercedes EQB"},
		{"Mercedes", "EQB 300 4MATIC", "", "Mercedes EQB"},
		{"Mercedes", "EQB 350", "", "Mercedes EQB"},
		{"Mercedes", "EQB 350 4MATIC", "", "Mercedes EQB"},
		{"Mercedes", "EQB 350 4Matic", "", "Mercedes EQB"},
		{"Peugeot", "e-308 SW", "", "Peugeot e-308"},
		{"Skoda", "Enyaq", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq 80", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq 80/85", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq 80x", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq 85", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq 85x", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq RS", "", "Škoda Enyaq"},
		{"Skoda", "Enyaq Coupé 80", "", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq Coupé 80/85", "", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq Coupé 85", "", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq Coupé 85x", "", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq Coupé RS", "", "Škoda Enyaq Coupé"},
		{"Toyota", "bZ4X", "", "Toyota bZ4X"},
		{"VW", "ID.4", "", "VW ID.4"},
		{"VW", "ID.4 GTX", "", "VW ID.4"},
		{"VW", "ID.4 Pro", "", "VW ID.4"},
		{"VW", "ID.4 Pro 4MOTION", "", "VW ID.4"},
		{"VW", "ID.4 Pro Mas", "", "VW ID.4"},
		{"VW", "ID.4 Pro Performance", "", "VW ID.4"},
		{"VW", "ID.4 Pro Power", "", "VW ID.4"},
		{"VW", "ID.4 Pure", "", "VW ID.4"},
		{"VW", "ID.5", "", "VW ID.5"},
		{"VW", "ID.5 GTX", "", "VW ID.5"},
		{"VW", "ID.5 Pro", "", "VW ID.5"},
		{"VW", "ID.5 Pro Performance", "", "VW ID.5"},
		{"XPeng", "G6", "", "XPeng G6"},
		{"Xpeng", "G6", "", "XPeng G6"},
		// body only in the variant
		{"Audi", "Q4 e-tron", "Sportback 45 advanced LED 19 KAMERA PDC VIRTUAL DA", "Audi Q4 Sportback"},
		{"Audi", "Q4", "Sportback 40 e-tron S-Line+Navi+Matrix+Virt C", "Audi Q4 Sportback"},
		{"Audi", "Q4 e-tron", "Q4 SPB 45 e-tron", "Audi Q4 Sportback"},
		{"Audi", "Q4 e-tron", "40 S line ACC/Virtual/LED", "Audi Q4"},
		{"Skoda", "Enyaq", "Coupe 85 Loft PANO AHK WP KAMERA MATRIX", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq", "RS Coupe iV 82 kWh 4x4 MATRIX*ACC*NAVI*LED", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq", "Coupé iV RS Suite", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq Coupé 80", "80 IV COUPE'", "Škoda Enyaq Coupé"},
		{"Skoda", "Enyaq", "iV 80 Loft", "Škoda Enyaq"},
		// make aliases and diacritics
		{"Volkswagen", "ID.4 Pro", "", "VW ID.4"},
		{"VOLKSWAGEN", "ID4", "", "VW ID.4"},
		{"Škoda", "Enyaq iV 80", "", "Škoda Enyaq"},
		{"ŠKODA", "ENYAQ COUPÉ RS", "", "Škoda Enyaq Coupé"},
		{"Mercedes-Benz", "EQA 250+", "", "Mercedes EQA"},
		{"MERCEDES BENZ", "EQB 300 4MATIC", "", "Mercedes EQB"},
		{"SsangYong", "Torres EVX", "", "KGM Torres EVX"},
		{"Mini", "Countryman SE ALL4", "", "MINI Countryman"},
		{"Audi", "Audi Q4 e-tron", "", "Audi Q4"},
		{"BYD", "Sealion 7", "", "BYD Sealion 7"},
		{"BYD", "Seal", "Excellence AWD", "BYD Seal"},
		{"Hyundai", "Ioniq 6", "", "Hyundai Ioniq 6"},
		{"Kia", "EV9", "", "Kia EV9"},
		{"BMW", "iX xDrive40", "", "BMW iX"},
		{"Mercedes", "EQE", "SUV 350 4MATIC", "Mercedes EQE SUV"},
		{"Polestar", "2", "Long Range Dual Motor", "Polestar 2"},
		{"Smart", "#1", "Brabus", "Smart #1"},
		{"Tesla", "Model Y", "Long Range", "Tesla Model Y"},
		{"Ford", "Mustang Mach-E", "", "Ford Mustang Mach-E"},
		{"VW", "ID. Buzz", "", "VW ID. Buzz"},
		{"KGM", "Torres", "EVX Platinum", "KGM Torres EVX"},
		// empty make: a distinctive model token carries its make
		{"", "ID.4 Pro Performance", "", "VW ID.4"},
		{"", "Enyaq Coupé RS", "", "Škoda Enyaq Coupé"},
		{"", "bZ4X", "", "Toyota bZ4X"},
		{"", "Polestar 2", "", "Polestar 2"},
		{"", "VW ID.5 GTX", "", "VW ID.5"},
		{"", "", "ID.4 Pro", "VW ID.4"},
		// negatives
		{"Mercedes", "EQA 250", "like the EQB", "Mercedes EQA"},
		{"VW", "ID.5 Pro", "", "VW ID.5"},
		{"BMW", "iX1 xDrive30", "", "BMW iX1"},
		{"BYD", "Seal U", "DM-i", "BYD Seal U"},
		{"Fiat", "500e", "", ""},
		{"Audi", "A4 Avant", "", ""},
		{"Mercedes", "EQE 300", "", ""},
		{"KGM", "Torres", "1.5 T-GDI", ""},
		{"VW", "Enyaq", "", ""},
		{"", "G6", "", ""},
		{"", "2", "", ""},
		{"Polestar", "Long Range 2", "", ""},
		{"", "", "", ""},
	}
	for _, c := range cases {
		got, mk, ok := Family(c.make, c.model, c.variant)
		if got != c.want || ok != (c.want != "") {
			t.Errorf("Family(%q, %q, %q) = %q, %v; want %q", c.make, c.model, c.variant, got, ok, c.want)
			continue
		}
		if ok {
			if _, wantMake, _ := CanonicalFamily(got); mk != wantMake {
				t.Errorf("Family(%q, %q) make = %q, want %q", c.make, c.model, mk, wantMake)
			}
		}
	}
}

func TestFamilyNames(t *testing.T) {
	names := FamilyNames()
	seen := map[string]bool{}
	for _, n := range names {
		k := normFamilyText(n)
		if seen[k] {
			t.Fatalf("two families normalize to %q", k)
		}
		seen[k] = true
		got, _, ok := CanonicalFamily(n)
		if !ok || got != n {
			t.Fatalf("CanonicalFamily(%q) = %q, %v", n, got, ok)
		}
	}
	for in, want := range map[string]string{"skoda enyaq coupe": "Škoda Enyaq Coupé", "vw id4": "VW ID.4", "AUDI Q4 SPORTBACK": "Audi Q4 Sportback", "mercedes eqa": "Mercedes EQA"} {
		if got, _, ok := CanonicalFamily(in); !ok || got != want {
			t.Errorf("CanonicalFamily(%q) = %q, %v; want %q", in, got, ok, want)
		}
	}
	if _, _, ok := CanonicalFamily("Audi Q5"); ok {
		t.Error("unknown family resolved")
	}
	if names[0] != "Audi Q4" {
		t.Errorf("names not sorted by make then family: %v", names[:3])
	}
}
