package store

import (
	"encoding/json"
	"slices"
	"strings"

	"carhunt/cardb/internal/api"
)

// Powertrain fields are flat car columns named like their JSON keys inside `powertrain`.
var powertrainCols = []string{"fuel", "battery_net_kwh", "battery_gross_kwh", "engine_cc", "gearbox", "wltp_range_km", "wltp_consumption", "co2_g_km"}

// powertrainOnly: accepted only inside `powertrain` on PATCH. The battery keys stay accepted flat (pre-v2 clients).
var powertrainOnly = map[string]bool{"fuel": true, "engine_cc": true, "gearbox": true, "wltp_range_km": true, "wltp_consumption": true, "co2_g_km": true}

func normEnum(col, v string) (string, error) {
	allowed := map[string][]string{"fuel": api.Fuels, "gearbox": api.Gearboxes, "price_vat": api.PriceVats}[col]
	v = strings.ToLower(strings.TrimSpace(v))
	if !slices.Contains(allowed, v) {
		return "", invalidf("%s must be one of %s", col, strings.Join(allowed, "|"))
	}
	return v, nil
}

// powertrainValues returns the set fields of p as column → raw value (normalized later by normSpec).
func powertrainValues(p *api.Powertrain) map[string]any {
	out := map[string]any{}
	if p == nil {
		return out
	}
	if p.Fuel != nil {
		out["fuel"] = *p.Fuel
	}
	if p.BatteryNetKwh != nil {
		out["battery_net_kwh"] = *p.BatteryNetKwh
	}
	if p.BatteryGrossKwh != nil {
		out["battery_gross_kwh"] = *p.BatteryGrossKwh
	}
	if p.EngineCc != nil {
		out["engine_cc"] = *p.EngineCc
	}
	if p.Gearbox != nil {
		out["gearbox"] = *p.Gearbox
	}
	if p.WltpRangeKm != nil {
		out["wltp_range_km"] = *p.WltpRangeKm
	}
	if p.WltpConsumption != nil {
		out["wltp_consumption"] = *p.WltpConsumption
	}
	if p.Co2GKm != nil {
		out["co2_g_km"] = *p.Co2GKm
	}
	return out
}

// decodePowertrainPatch reads PATCH `powertrain`: only sent fields change, a null field clears it,
// `"powertrain": null` clears every field.
func decodePowertrainPatch(raw json.RawMessage) (map[string]any, error) {
	out := map[string]any{}
	if string(raw) == "null" {
		for _, c := range powertrainCols {
			out[c] = nil
		}
		return out, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, invalidf("powertrain must be an object or null")
	}
	for k, v := range m {
		if !slices.Contains(powertrainCols, k) {
			return nil, invalidf("unknown powertrain field %q (known: %s)", k, strings.Join(powertrainCols, ", "))
		}
		kind, _ := specKind(k)
		nv, err := decodeSpecRaw("powertrain."+k, kind, v)
		if err != nil {
			return nil, err
		}
		if s, ok := nv.(string); ok && (k == "fuel" || k == "gearbox") {
			if nv, err = normEnum(k, s); err != nil {
				return nil, err
			}
		}
		out[k] = nv
	}
	return out, nil
}

// normFuelFilter validates GET /cars `fuel` values (repeatable, comma lists ok, case-insensitive).
func normFuelFilter(vals []string) ([]string, error) {
	var out []string
	for _, v := range vals {
		for _, p := range strings.Split(v, ",") {
			p = strings.ToLower(strings.TrimSpace(p))
			if p == "" {
				continue
			}
			if !slices.Contains(api.Fuels, p) {
				return nil, badRequestf("fuel must be one of %s", strings.Join(api.Fuels, "|"))
			}
			out = append(out, p)
		}
	}
	return out, nil
}

// fuelMatch: a car without a fuel counts as unknown.
func fuelMatch(c *api.CarSummary, fuels []string) bool {
	if len(fuels) == 0 {
		return true
	}
	f := "unknown"
	if c.Powertrain != nil && c.Powertrain.Fuel != nil {
		f = *c.Powertrain.Fuel
	}
	return slices.Contains(fuels, f)
}
