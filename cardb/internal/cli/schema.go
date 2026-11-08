package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

// putPath sets m[key], or m["powertrain"][sub] for key "powertrain.sub".
func putPath(m map[string]any, key string, v any) {
	if sub, ok := strings.CutPrefix(key, "powertrain."); ok {
		pt, _ := m["powertrain"].(map[string]any)
		if pt == nil {
			pt = map[string]any{}
			m["powertrain"] = pt
		}
		pt[sub] = v
		return
	}
	m[key] = v
}

// hasPath reports whether key (or "powertrain.sub") is already set in m; a whole-powertrain value covers every sub.
func hasPath(m map[string]any, key string) bool {
	if _, ok := m[key]; ok {
		return true
	}
	sub, ok := strings.CutPrefix(key, "powertrain.")
	if !ok {
		return false
	}
	v, ok := m["powertrain"]
	if !ok {
		return false
	}
	pt, isMap := v.(map[string]any)
	if !isMap {
		return true
	}
	_, has := pt[sub]
	return has
}

// parseIfVersion reads --if-version N (nil when not given).
func parseIfVersion(f *flags, raw string) (*int64, error) {
	if !f.isSet("if-version") {
		return nil, nil
	}
	n, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
	if err != nil || n < 0 {
		return nil, usageErrorf("--if-version: want the car's version number, got %q", raw)
	}
	return &n, nil
}

// fmtPowertrain is the one-line powertrain summary for `show` ("" when nothing is known).
func fmtPowertrain(pt *api.Powertrain) string {
	if pt.Empty() {
		return ""
	}
	var parts []string
	if pt.Fuel != nil {
		parts = append(parts, *pt.Fuel)
	}
	if pt.BatteryNetKwh != nil || pt.BatteryGrossKwh != nil {
		b := "battery "
		if pt.BatteryNetKwh != nil {
			b += fmtFloat(*pt.BatteryNetKwh)
		} else {
			b += "?"
		}
		if pt.BatteryGrossKwh != nil {
			b += "/" + fmtFloat(*pt.BatteryGrossKwh)
		}
		parts = append(parts, b+" kWh")
	}
	if pt.EngineCc != nil {
		parts = append(parts, groupThousands(*pt.EngineCc)+" cc")
	}
	if pt.Gearbox != nil {
		parts = append(parts, *pt.Gearbox)
	}
	if pt.WltpRangeKm != nil {
		parts = append(parts, fmt.Sprintf("WLTP %d km", *pt.WltpRangeKm))
	}
	if pt.WltpConsumption != nil {
		unit := "/100 km"
		if pt.Fuel != nil && *pt.Fuel == "bev" {
			unit = " kWh/100 km"
		}
		parts = append(parts, fmtFloat(*pt.WltpConsumption)+unit)
	}
	if pt.Co2GKm != nil {
		parts = append(parts, fmt.Sprintf("CO2 %d g/km", *pt.Co2GKm))
	}
	return strings.Join(parts, " · ")
}

// apiFailure rewrites API errors the CLI explains specially: a 412 version conflict and a 422 price rejection.
// extra = fields added to the --json error object.
func apiFailure(err error) (msg string, extra map[string]any) {
	var ae *client.APIError
	if !errors.As(err, &ae) {
		return "", nil
	}
	var body struct {
		Error    string  `json:"error"`
		Version  *int64  `json:"version"`
		Reason   string  `json:"reason"`
		Price    *int    `json:"price"`
		Expected *string `json:"expected"`
	}
	if json.Unmarshal(ae.Body, &body) != nil {
		return "", nil
	}
	switch {
	case ae.Status == 412 && body.Version != nil:
		return fmt.Sprintf("conflict: car changed (version %d)", *body.Version), map[string]any{"version": *body.Version}
	case ae.Status == 422 && body.Reason != "":
		extra = map[string]any{"reason": body.Reason}
		if body.Expected != nil {
			extra["expected"] = *body.Expected
		}
		return body.Error + " (use --force to store it flagged)", extra
	}
	return "", nil
}

// printPriceFlags adds a "⚠ price flags" line when a listing's price was forced past the sanity check.
func printPriceFlags(w io.Writer, flags []string) {
	if len(flags) > 0 {
		fmt.Fprintf(w, "    ⚠ price forced past sanity check: %s\n", strings.Join(flags, ", "))
	}
}

// parsePriceVat validates --price-vat ("" = not given).
func parsePriceVat(raw string) (string, error) {
	v := strings.ToLower(strings.TrimSpace(raw))
	if v == "" {
		return "", nil
	}
	if !contains(api.PriceVats, v) {
		return "", usageErrorf("--price-vat: want %s", strings.Join(api.PriceVats, "|"))
	}
	return v, nil
}
