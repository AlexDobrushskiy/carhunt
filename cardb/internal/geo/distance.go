package geo

import "math"

// Point is a WGS84 position in degrees.
type Point struct{ Lat, Lon float64 }

// Centroids: rough population-weighted country centres (EU + EEA + CH + UK), for a distance guess when a car has no
// location beyond its country.
var Centroids = map[string]Point{
	"AT": {47.6, 14.1}, "BE": {50.7, 4.6}, "BG": {42.7, 25.2}, "HR": {45.3, 16.1}, "CY": {35.1, 33.3}, "CZ": {49.8, 15.4},
	"DK": {55.9, 10.6}, "EE": {58.9, 25.3}, "FI": {61.9, 25.0}, "FR": {46.8, 2.4}, "DE": {51.0, 9.9}, "GR": {38.6, 22.9},
	"HU": {47.2, 19.4}, "IE": {53.3, -7.8}, "IT": {42.9, 12.5}, "LV": {56.9, 24.6}, "LT": {55.3, 23.9}, "LU": {49.7, 6.1},
	"MT": {35.9, 14.4}, "NL": {52.2, 5.5}, "PL": {52.0, 19.4}, "PT": {39.6, -8.3}, "RO": {45.9, 25.0}, "SK": {48.7, 19.5},
	"SI": {46.1, 14.8}, "ES": {40.2, -3.6}, "SE": {59.5, 16.0}, "CH": {46.8, 8.2}, "NO": {60.5, 9.0}, "IS": {64.5, -21.0},
	"LI": {47.1, 9.55}, "GB": {52.5, -1.5},
}

// VATRates: standard VAT rate (%) per EU country, for the VAT reserve on cars bought abroad as "new means of transport".
var VATRates = map[string]float64{
	"AT": 20, "BE": 21, "BG": 20, "HR": 25, "CY": 19, "CZ": 21, "DK": 25, "EE": 24, "FI": 25.5, "FR": 20, "DE": 19, "GR": 24,
	"HU": 27, "IE": 23, "IT": 22, "LV": 21, "LT": 21, "LU": 17, "MT": 18, "NL": 21, "PL": 23, "PT": 23, "RO": 21, "SK": 23,
	"SI": 22, "ES": 21, "SE": 25,
}

// GreatCircleKm is the haversine distance in km.
func GreatCircleKm(a, b Point) float64 {
	const r = 6371.0
	rad := func(d float64) float64 { return d * math.Pi / 180 }
	dLat, dLon := rad(b.Lat-a.Lat), rad(b.Lon-a.Lon)
	h := math.Sin(dLat/2)*math.Sin(dLat/2) + math.Cos(rad(a.Lat))*math.Cos(rad(b.Lat))*math.Sin(dLon/2)*math.Sin(dLon/2)
	return 2 * r * math.Asin(math.Min(1, math.Sqrt(h)))
}
