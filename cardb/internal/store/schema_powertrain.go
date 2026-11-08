package store

// migPowertrain: powertrain columns, car version, listing price VAT + sanity flags.
// Cars with a battery value and no fuel were EVs (the EV-era schema had no fuel column).
const migPowertrain = `
ALTER TABLE cars ADD COLUMN fuel TEXT;
ALTER TABLE cars ADD COLUMN engine_cc INTEGER;
ALTER TABLE cars ADD COLUMN gearbox TEXT;
ALTER TABLE cars ADD COLUMN wltp_range_km INTEGER;
ALTER TABLE cars ADD COLUMN wltp_consumption REAL;
ALTER TABLE cars ADD COLUMN co2_g_km INTEGER;
ALTER TABLE cars ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
UPDATE cars SET fuel = 'bev' WHERE fuel IS NULL AND (battery_net_kwh IS NOT NULL OR battery_gross_kwh IS NOT NULL);

ALTER TABLE listings ADD COLUMN price_vat TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE listings ADD COLUMN price_flags TEXT NOT NULL DEFAULT '[]';
`
