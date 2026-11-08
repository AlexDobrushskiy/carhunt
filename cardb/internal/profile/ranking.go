package profile

import (
	"carhunt/cardb/internal/geo"
)

// Ranking holds the value model's tunables (search.ranking). Keys left out of the config keep these defaults
// (the worked example's values); see the store's rank.go for how each is used.
type Ranking struct {
	Peers      Peers      `yaml:"peers" json:"peers"`
	LandedCost LandedCost `yaml:"landed_cost" json:"landed_cost"`
	VATReserve VATReserve `yaml:"vat_reserve" json:"vat_reserve"`
	Fit        Fit        `yaml:"fit" json:"fit"`
	Risk       Risk       `yaml:"risk" json:"risk"`
}

// Peers: the comparable pool and the fair-price peer ladder.
type Peers struct {
	PowerBandHP float64 `yaml:"power_band_hp" json:"power_band_hp"` // trim = power rounded to this + awd/2wd
	KmBands     []int   `yaml:"km_bands" json:"km_bands"`           // upper bounds; above the last = last band
	MinN        []int   `yaml:"min_n" json:"min_n"`                 // ladder steps: trim+year+km, trim+year, trim, family
	YearEUR     float64 `yaml:"year_eur" json:"year_eur"`           // adjust per model year (wider steps)
	KmEUR       float64 `yaml:"km_eur" json:"km_eur"`               // adjust per km (wider steps)
	OutlierMinN int     `yaml:"outlier_min_n" json:"outlier_min_n"` // family+trim band size before the outlier screen applies
	OutlierLow  float64 `yaml:"outlier_low" json:"outlier_low"`     // drop asks below this × band median
	OutlierHigh float64 `yaml:"outlier_high" json:"outlier_high"`   // … and above this × band median
}

// LandedCost: price + trip + registration (+ VAT reserve) to get a car home. Steps are [max_km, cost] pairs in
// ascending max_km; max_km 0 = any distance.
type LandedCost struct {
	DefaultDistanceKm map[string]int `yaml:"default_distance_km" json:"default_distance_km,omitempty"` // country → km when a car has no distance; "other" = any
	HomeTrip          [][]float64    `yaml:"home_trip" json:"home_trip"`
	Abroad            AbroadTrip     `yaml:"abroad_trip" json:"abroad_trip"`
	RegistrationHome  float64        `yaml:"registration_home" json:"registration_home"`
	RegistrationAbrd  float64        `yaml:"registration_import" json:"registration_import"`
}

// AbroadTrip: fetch a car from another country by driving it home on export plates.
type AbroadTrip struct {
	Travel      [][]float64 `yaml:"travel" json:"travel"`               // one-way ticket out
	Fixed       float64     `yaml:"fixed" json:"fixed"`                 // export plates + insurance
	EnergyPerKm float64     `yaml:"energy_per_km" json:"energy_per_km"` // charging / fuel
	TollsPerKm  float64     `yaml:"tolls_per_km" json:"tolls_per_km"`
	NightCost   float64     `yaml:"night_cost" json:"night_cost"`
	NightFreeKm float64     `yaml:"night_free_km" json:"night_free_km"` // no overnight up to this distance
	KmPerNight  float64     `yaml:"km_per_night" json:"km_per_night"`
	MaxNights   int         `yaml:"max_nights" json:"max_nights"`
	Food        [][]float64 `yaml:"food" json:"food"`
}

// VATReserve: a car bought abroad with km ≤ KmMax or registered within MonthsMax counts as a "new means of
// transport" — VAT is due at home; reserve Pct % of the price (default = home country's standard rate).
type VATReserve struct {
	Enabled   *bool    `yaml:"enabled" json:"enabled"`
	Pct       *float64 `yaml:"pct" json:"pct"`
	KmMax     int      `yaml:"km_max" json:"km_max"`
	MonthsMax int      `yaml:"months_max" json:"months_max"`
}

// On reports whether the reserve applies at all.
func (v VATReserve) On() bool { return (v.Enabled == nil || *v.Enabled) && v.Pct != nil && *v.Pct > 0 }

// Fit: fit = base_fit + weights.fit × Σ terms.
type Fit struct {
	BaseDefault    float64 `yaml:"base_default" json:"base_default"` // family without search.models base_fit
	OptionUnit     float64 `yaml:"option_unit" json:"option_unit"`   // per options_wanted / penalty weight point
	SellerPrivate  float64 `yaml:"seller_private" json:"seller_private"`
	SellerReseller float64 `yaml:"seller_reseller" json:"seller_reseller"`
	HomeMarket     float64 `yaml:"home_market" json:"home_market"`
	AgePerYear     float64 `yaml:"age_per_year" json:"age_per_year"` // × max(0, age_years − age)
	AgeYears       float64 `yaml:"age_years" json:"age_years"`
	Km             float64 `yaml:"km" json:"km"`                     // × (1 − km / km_ref)
	KmRef          int     `yaml:"km_ref" json:"km_ref"`             // 0 = search.km_max, else 50000
	HistoryFact    float64 `yaml:"history_fact" json:"history_fact"` // each: one owner, service history, accident-free
}

// Risk: points added for missing evidence and warning signs (each key = points).
type Risk struct {
	UnknownOption    float64             `yaml:"unknown_option" json:"unknown_option"`         // each must_have / top wanted option not yes/no
	UnknownOptionTop int                 `yaml:"unknown_option_top" json:"unknown_option_top"` // how many options_wanted (by weight) count
	NoVIN            float64             `yaml:"no_vin" json:"no_vin"`
	NoServiceHistory float64             `yaml:"no_service_history" json:"no_service_history"`
	NoOwners         float64             `yaml:"no_owners" json:"no_owners"`
	NoAccidents      float64             `yaml:"no_accidents" json:"no_accidents"`
	NoHealth         float64             `yaml:"no_health" json:"no_health"`
	HealthFacts      map[string][]string `yaml:"health_facts" json:"health_facts"` // fuel → fact keys, any one present = known
	DistanceUnknown  float64             `yaml:"distance_unknown" json:"distance_unknown"`
	Reseller         float64             `yaml:"reseller" json:"reseller"`
	VATReserve       float64             `yaml:"vat_reserve" json:"vat_reserve"`
	ThinPeers        float64             `yaml:"thin_peers" json:"thin_peers"`
	ThinPeersN       int                 `yaml:"thin_peers_n" json:"thin_peers_n"`
	Spread           float64             `yaml:"spread" json:"spread"`
	SpreadMax        float64             `yaml:"spread_max" json:"spread_max"` // (IQR75 − IQR25) / fair_landed
	RedFlag          float64             `yaml:"red_flag" json:"red_flag"`     // each red_flags item
	PriceForced      float64             `yaml:"price_forced" json:"price_forced"`
	ReasonsMax       int                 `yaml:"reasons_max" json:"reasons_max"`
}

func defaultRanking() Ranking {
	return Ranking{
		Peers: Peers{PowerBandHP: 25, KmBands: []int{15000, 30000}, MinN: []int{8, 6, 3, 3}, YearEUR: 2000, KmEUR: 0.06,
			OutlierMinN: 8, OutlierLow: 0.67, OutlierHigh: 1.65},
		LandedCost: LandedCost{
			HomeTrip: [][]float64{{100, 50}, {500, 100}, {0, 200}},
			Abroad: AbroadTrip{Travel: [][]float64{{700, 50}, {0, 100}}, Fixed: 250, EnergyPerKm: 0.10, TollsPerKm: 0.035,
				NightCost: 100, NightFreeKm: 700, KmPerNight: 1300, MaxNights: 2, Food: [][]float64{{700, 30}, {0, 60}}},
			RegistrationHome: 65, RegistrationAbrd: 250,
		},
		VATReserve: VATReserve{KmMax: 6000, MonthsMax: 6},
		Fit: Fit{BaseDefault: 0.40, OptionUnit: 0.03, SellerPrivate: 0.06, SellerReseller: -0.12, HomeMarket: 0.04,
			AgePerYear: 0.005, AgeYears: 8, Km: 0.03, HistoryFact: 0.015},
		Risk: Risk{UnknownOption: 0.8, UnknownOptionTop: 4, NoVIN: 0.8, NoServiceHistory: 0.8, NoOwners: 0.5, NoAccidents: 0.8,
			NoHealth: 1, DistanceUnknown: 0.5, Reseller: 4, VATReserve: 4, ThinPeers: 3, ThinPeersN: 8, Spread: 3, SpreadMax: 0.15,
			RedFlag: 3, PriceForced: 0.5, ReasonsMax: 5},
	}
}

// applyDefaults fills what depends on the rest of the profile (VAT rate of the home country, health fact keys).
func (r *Ranking) applyDefaults(p *Profile) {
	if r.VATReserve.Pct == nil {
		if v, ok := geo.VATRates[p.Owner.Home.Country]; ok {
			r.VATReserve.Pct = &v
		}
	}
	if r.Risk.HealthFacts == nil {
		battery := []string{"battery_soh", "soh", "battery_health", "battery_report", "battery_cert", "battery_test"}
		r.Risk.HealthFacts = map[string][]string{"bev": battery, "phev": battery}
	}
	if r.Fit.KmRef <= 0 {
		r.Fit.KmRef = p.Search.KmMax
		if r.Fit.KmRef <= 0 {
			r.Fit.KmRef = 50000
		}
	}
}

// Step returns the cost of the first [max_km, cost] step that covers km (max_km 0 = any); 0 when none does.
func Step(steps [][]float64, km float64) float64 {
	for _, s := range steps {
		if len(s) == 2 && (s[0] <= 0 || km <= s[0]) {
			return s[1]
		}
	}
	return 0
}
