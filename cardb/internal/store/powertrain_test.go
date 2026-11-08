package store

import (
	"context"
	"encoding/json"
	"testing"

	"carhunt/cardb/internal/api"
)

// A database written before migration #6 (battery columns only, no fuel/version/price flags) opens with the
// full store: battery-only cars become fuel=bev with the battery inside powertrain, others stay unknown.
func TestPowertrainMigration(t *testing.T) {
	dir := t.TempDir()
	full := migrations
	migrations = full[:5]
	old, err := Open(dir)
	if err != nil {
		migrations = full
		t.Fatal(err)
	}
	for _, q := range []string{
		`INSERT INTO cars (id, make, model, battery_net_kwh, battery_gross_kwh, created_at, updated_at) VALUES (1, 'SYNTH', 'EV One', 77, 82, 1, 1)`,
		`INSERT INTO cars (id, make, model, battery_gross_kwh, created_at, updated_at) VALUES (2, 'SYNTH', 'EV Two', 64.5, 1, 1)`,
		`INSERT INTO cars (id, make, model, km, created_at, updated_at) VALUES (3, 'SYNTH', 'Petrol', 50000, 1, 1)`,
		`INSERT INTO listings (id, car_id, url, url_key, site, status, price, first_seen_at, last_seen_at)
			VALUES (1, 1, 'https://example.invalid/a', 'example.invalid/a', 'example.invalid', 'live', 30000, 1, 1)`,
	} {
		if _, err := old.db.Exec(q); err != nil {
			migrations = full
			t.Fatal(err)
		}
	}
	old.Close()
	migrations = full

	st, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	ctx := context.Background()
	get := func(id string) *api.CarDetail {
		t.Helper()
		d, err := st.GetCar(ctx, id)
		if err != nil {
			t.Fatal(err)
		}
		return d
	}

	c1 := get("1")
	pt := c1.Powertrain
	if pt == nil || pt.Fuel == nil || *pt.Fuel != "bev" || pt.BatteryNetKwh == nil || *pt.BatteryNetKwh != 77 ||
		pt.BatteryGrossKwh == nil || *pt.BatteryGrossKwh != 82 {
		t.Fatalf("car 1 powertrain: %s", mustJSON(pt))
	}
	if pt.EngineCc != nil || pt.Gearbox != nil || pt.WltpRangeKm != nil || pt.WltpConsumption != nil || pt.Co2GKm != nil {
		t.Fatalf("car 1: unexpected powertrain fields %s", mustJSON(pt))
	}
	if c1.Version != 1 {
		t.Fatalf("car 1 version %d, want 1 after migration", c1.Version)
	}
	if l := c1.Listings[0]; l.PriceVat != "unknown" || len(l.PriceFlags) != 0 {
		t.Fatalf("listing defaults: vat %q flags %v", l.PriceVat, l.PriceFlags)
	}
	if c2 := get("2"); c2.Powertrain == nil || *c2.Powertrain.Fuel != "bev" || c2.Powertrain.BatteryNetKwh != nil {
		t.Fatalf("car 2 powertrain: %s", mustJSON(c2.Powertrain))
	}
	if c3 := get("3"); c3.Powertrain != nil {
		t.Fatalf("car 3 (no battery) powertrain: %s", mustJSON(c3.Powertrain))
	}

	// Writes after the migration raise the version (triggers installed on open), and reopening keeps them working.
	if _, err := st.PatchCar(ctx, "3", map[string]json.RawMessage{"powertrain": json.RawMessage(`{"fuel":"Petrol","engine_cc":1498}`)}, "t"); err != nil {
		t.Fatal(err)
	}
	c3 := get("3")
	if c3.Version <= 1 || *c3.Powertrain.Fuel != "petrol" || *c3.Powertrain.EngineCc != 1498 {
		t.Fatalf("car 3 after patch: version %d powertrain %s", c3.Version, mustJSON(c3.Powertrain))
	}
	st.Close()
	st, err = Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.PatchCar(ctx, "3", map[string]json.RawMessage{"km": json.RawMessage(`51000`)}, "t"); err != nil {
		t.Fatal(err)
	}
	if v := get("3").Version; v <= c3.Version {
		t.Fatalf("car 3 version after reopen + patch: %d, want > %d", v, c3.Version)
	}
}

func TestPriceWording(t *testing.T) {
	monthly := []string{"Renting 450 €/mês", "desde 299€/mes", "399 € per month", "prestação mensal", "mtl. 349 €",
		"Leasingrate monatlich", "LOA 290 €/mois", "noleggio 450 al mese", "€ 399 per maand", "cuota mensual"}
	for _, s := range monthly {
		if !reMonthly.MatchString(s) && !reLease.MatchString(s) {
			t.Errorf("%q: want monthly/lease wording", s)
		}
	}
	net := []string{"35 000 € + IVA", "35.000 € +IVA", "excl. VAT", "zzgl. MwSt.", "Netto-Preis netto", "excl. BTW",
		"prix hors taxes", "sin IVA", "IVA não incluído", "IVA esclusa"}
	for _, s := range net {
		if !reNet.MatchString(s) {
			t.Errorf("%q: want net wording", s)
		}
	}
	if !reNetHT.MatchString("29 900 € HT") || reNetHT.MatchString("HTML export") {
		t.Error("HT detection")
	}
	for _, s := range []string{"Brutto 30.000, netto 25.210", "IVA incluído", "inkl. MwSt.", "IVA dedutível", "TTC"} {
		if !reGross.MatchString(s) {
			t.Errorf("%q: want gross wording", s)
		}
	}
	for _, s := range []string{"VW ID.4 Pro Performance", "Tesla Model 3 Long Range AWD", "garantia 24 meses", "Mercedes EQA 250"} {
		if reMonthly.MatchString(s) || reLease.MatchString(s) || reNet.MatchString(s) || reNetHT.MatchString(s) {
			t.Errorf("%q: false positive", s)
		}
	}
}
