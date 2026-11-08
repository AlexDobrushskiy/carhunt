// Package profile loads the buyer profile cardb ranks and filters with: the `owner`, `search` and `cardb` sections
// of $CARHUNT_HOME/config.yaml. Nothing buyer-specific lives in Go; this is the only input. Defaults (Default,
// defaultRanking) are the worked example's values where the value model needs a number.
package profile

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"go.yaml.in/yaml/v3"
)

// Profile is the parsed, defaulted, validated profile. Read-only after Load.
type Profile struct {
	Owner  Owner  `yaml:"owner" json:"owner"`
	Search Search `yaml:"search" json:"search"`
	Cardb  Cardb  `yaml:"cardb" json:"-"`
	Path   string `yaml:"-" json:"-"` // file it came from ("" = built-in default)
	// Warnings: unknown keys and unknown option names (the profile still loads).
	Warnings []string `yaml:"-" json:"warnings,omitempty"`
}

// Owner is the human buyer.
type Owner struct {
	Name      string   `yaml:"name" json:"name"`
	Languages []string `yaml:"languages" json:"languages,omitempty"`
	TZ        string   `yaml:"tz" json:"tz"`
	Home      Home     `yaml:"home" json:"home"`
}

// Home is where cars are brought to (distance, market, phone numbers without a country code).
type Home struct {
	City    string   `yaml:"city" json:"city"`
	Country string   `yaml:"country" json:"country"` // ISO-2, upper case
	Lat     *float64 `yaml:"lat" json:"lat,omitempty"`
	Lon     *float64 `yaml:"lon" json:"lon,omitempty"`
}

// Located reports whether home has coordinates.
func (h Home) Located() bool { return h.Lat != nil && h.Lon != nil }

// Cardb is the server's own config section (secrets are references, never values).
type Cardb struct {
	URL     string `yaml:"url"`
	Token   string `yaml:"token"` // client token reference (secret:<name>); read by package setup, never a value
	DataDir string `yaml:"data_dir"`
	Users   []User `yaml:"users"` // viewers (the owner is implicit)
}

// User is one person who can rate cars.
type User struct {
	Name string `yaml:"name" json:"name"`
	Role string `yaml:"role" json:"role"` // owner | viewer
}

// Search is the buyer profile proper: scope, queue tiers, hard filters, fit, weights, ranking tunables.
type Search struct {
	Countries            []string           `yaml:"countries" json:"countries"`
	PrivateSellersAbroad *bool              `yaml:"private_sellers_abroad" json:"private_sellers_abroad,omitempty"`
	ExcludeRegions       []string           `yaml:"exclude_regions" json:"exclude_regions,omitempty"` // ISO 3166-2 (PT-20 …)
	ExcludePlaces        []string           `yaml:"exclude_places" json:"exclude_places,omitempty"`   // extra city words
	Price                Price              `yaml:"price" json:"price"`
	YearMin              int                `yaml:"year_min" json:"year_min,omitempty"`
	KmMax                int                `yaml:"km_max" json:"km_max,omitempty"`
	Powertrain           []string           `yaml:"powertrain" json:"powertrain,omitempty"` // allowed fuels (bev, phev, …); empty = any
	Models               []Model            `yaml:"models" json:"models,omitempty"`
	DefaultTier          int                `yaml:"default_tier" json:"default_tier"`
	QueueDefaultTiers    []int              `yaml:"queue_default_tiers" json:"queue_default_tiers"`
	TierLabels           map[int]string     `yaml:"tier_labels" json:"tier_labels,omitempty"`
	Families             []FamilyRule       `yaml:"families" json:"-"`
	HardFilters          []HardFilter       `yaml:"hard_filters" json:"hard_filters,omitempty"`
	OptionsWanted        map[string]float64 `yaml:"options_wanted" json:"options_wanted,omitempty"`
	OptionLabels         map[string]string  `yaml:"option_labels" json:"option_labels,omitempty"`
	MustHave             []string           `yaml:"must_have" json:"must_have,omitempty"`
	OptionKeys           []string           `yaml:"option_keys" json:"option_keys,omitempty"`
	Penalties            []Penalty          `yaml:"penalties" json:"penalties,omitempty"`
	Weights              map[string]float64 `yaml:"weights" json:"weights,omitempty"` // value, fit, risk
	RoadFactor           float64            `yaml:"road_factor" json:"road_factor,omitempty"`
	Ranking              Ranking            `yaml:"ranking" json:"ranking"`
}

// Price: max_eur = queue hard filter; min_eur / cap_eur = write-time price sanity bounds (integer units, gross).
type Price struct {
	MaxEUR   int    `yaml:"max_eur" json:"max_eur,omitempty"`
	MinEUR   int    `yaml:"min_eur" json:"min_eur,omitempty"` // sanity floor only (price write check; cardb default 1500), not a queue filter
	CapEUR   int    `yaml:"cap_eur" json:"cap_eur,omitempty"` // sanity: refuse prices above (cardb default 2 000 000)
	Gross    *bool  `yaml:"gross" json:"gross,omitempty"`
	Currency string `yaml:"currency" json:"currency,omitempty"`
}

// Model is one wanted make/model family with its queue tier; `When` narrows it (first match wins).
// Model "" = every family of the make.
type Model struct {
	Make    string   `yaml:"make" json:"make"`
	Model   string   `yaml:"model" json:"model"`
	Tier    int      `yaml:"tier" json:"tier"`
	Label   string   `yaml:"label" json:"label,omitempty"`
	BaseFit *float64 `yaml:"base_fit" json:"base_fit,omitempty"` // default ranking.fit.base_default
	Risk    float64  `yaml:"risk" json:"risk,omitempty"`         // model-specific risk (known weak points)
	When    *When    `yaml:"when" json:"when,omitempty"`
}

// When: every set condition must hold; an unknown car value passes, except as below.
// Measured ranges (power_hp, battery_net_kwh): a known value must be in range; an unknown one is decided by
// variant_any (the trim marker) when set, else passes. Without a measured range variant_any must hold outright.
// Tokens/phrases are matched as whole words in model + variant (folded; "85x" also reads as "85 x").
// Drive: awd tokens in the text (quattro, 4motion, …) count as awd.
type When struct {
	PowerHP       []float64 `yaml:"power_hp" json:"power_hp,omitempty"` // [min, max] metric hp
	Drive         []string  `yaml:"drive" json:"drive,omitempty"`       // allowed: fwd rwd awd
	VariantAny    []string  `yaml:"variant_any" json:"variant_any,omitempty"`
	VariantNone   []string  `yaml:"variant_none" json:"variant_none,omitempty"` // none of these, always
	YearMin       int       `yaml:"year_min" json:"year_min,omitempty"`
	YearMax       int       `yaml:"year_max" json:"year_max,omitempty"`
	BatteryNetKwh []float64 `yaml:"battery_net_kwh" json:"battery_net_kwh,omitempty"` // [min, max]
	Fuel          []string  `yaml:"fuel" json:"fuel,omitempty"`
}

// FamilyRule adds or overrides a model-family recognition rule (same make + name = override; see store families.yaml).
type FamilyRule struct {
	Make        string   `yaml:"make"`
	MakeAliases []string `yaml:"make_aliases"` // other spellings of the make ("vw", "volkswagen")
	Name        string   `yaml:"name"`
	Match       []string `yaml:"match"` // word sequences, any one matches
	With        []string `yaml:"with"`  // words that must also appear in model + variant
	Lead        bool     `yaml:"lead"`  // the sequence must start the model
	Bare        bool     `yaml:"bare"`  // matches when the make is empty or unknown
	Body        []string `yaml:"body"`  // a body word in model + variant selects body_name
	BodyName    string   `yaml:"body_name"`
}

// HardFilter is one queue exclusion rule. Exactly one of Field / Fact(s) / Flag is set.
//   - field + min/max: car field out of range → excluded (missing passes).
//   - fact(s) + min/max: numeric fact out of range; + words: a folded whole word/phrase present; + mentions_country:
//     a value names one of the countries; neither: the fact is truthy.
//   - flag: a truthy fact of that name or a price flag of the car's price listing.
type HardFilter struct {
	Field           string   `yaml:"field" json:"field,omitempty"`
	Min             *float64 `yaml:"min" json:"min,omitempty"`
	Max             *float64 `yaml:"max" json:"max,omitempty"`
	Fact            string   `yaml:"fact" json:"fact,omitempty"`
	Facts           []string `yaml:"facts" json:"facts,omitempty"`
	Words           []string `yaml:"words" json:"words,omitempty"`
	MentionsCountry []string `yaml:"mentions_country" json:"mentions_country,omitempty"` // ISO-2
	Flag            string   `yaml:"flag" json:"flag,omitempty"`
	Label           string   `yaml:"label" json:"label,omitempty"`
}

// FactKeys is the fact list of a fact rule (fact + facts).
func (h HardFilter) FactKeys() []string {
	if h.Fact != "" {
		return append([]string{h.Fact}, h.Facts...)
	}
	return h.Facts
}

// Penalty: a numeric car field at/above Min (or at/below Max) lowers fit by weight × fit.option_unit and the trim
// score by weight. Label may contain {v} for the value ('{v}" wheels').
type Penalty struct {
	Field  string   `yaml:"field" json:"field"`
	Min    *float64 `yaml:"min" json:"min,omitempty"`
	Max    *float64 `yaml:"max" json:"max,omitempty"`
	Weight float64  `yaml:"weight" json:"weight"`
	Label  string   `yaml:"label" json:"label,omitempty"`
}

// Default is the neutral profile used when no config file exists: no filters, one tier, no home.
func Default() *Profile {
	p := &Profile{}
	p.Search.Ranking = defaultRanking()
	p.applyDefaults()
	return p
}

// Resolve returns the config path: $CARHUNT_CONFIG, else $CARHUNT_HOME/config.yaml, else ~/.carhunt/config.yaml.
func Resolve() string {
	if v := os.Getenv("CARHUNT_CONFIG"); v != "" {
		return v
	}
	home := os.Getenv("CARHUNT_HOME")
	if home == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		home = filepath.Join(h, ".carhunt")
	}
	return filepath.Join(home, "config.yaml")
}

// LoadDefault loads Resolve(); a missing file gives Default() (cardb runs without carhunt).
func LoadDefault() (*Profile, error) {
	path := Resolve()
	if path == "" {
		return Default(), nil
	}
	p, err := Load(path)
	if errors.Is(err, os.ErrNotExist) {
		return Default(), nil
	}
	return p, err
}

// Load parses one config file (other sections are ignored) and validates it.
func Load(path string) (*Profile, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	p, err := Parse(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	p.Path = path
	return p, nil
}

// Parse parses YAML bytes into a defaulted, validated profile. Unknown keys in owner/search/cardb are warnings
// (other tools extend those sections); type errors and invalid values are errors.
func Parse(b []byte) (*Profile, error) {
	p := Profile{}
	p.Search.Ranking = defaultRanking()
	dec := yaml.NewDecoder(bytes.NewReader(b))
	dec.KnownFields(true)
	var doc struct {
		Owner  *Owner               `yaml:"owner"`
		Search *Search              `yaml:"search"`
		Cardb  *Cardb               `yaml:"cardb"`
		Rest   map[string]yaml.Node `yaml:",inline"`
	}
	doc.Owner, doc.Search, doc.Cardb = &p.Owner, &p.Search, &p.Cardb
	if err := dec.Decode(&doc); err != nil && !errors.Is(err, io.EOF) {
		var te *yaml.TypeError
		if !errors.As(err, &te) {
			return nil, err
		}
		var fatal []string
		for _, e := range te.Errors {
			if strings.Contains(e, "not found in type") {
				p.Warnings = append(p.Warnings, "unknown key: "+e)
			} else {
				fatal = append(fatal, e)
			}
		}
		if len(fatal) > 0 {
			return nil, errors.New("profile: " + strings.Join(fatal, "; "))
		}
	}
	p.applyDefaults()
	if err := p.Validate(); err != nil {
		return nil, err
	}
	return &p, nil
}

func (p *Profile) applyDefaults() {
	if strings.TrimSpace(p.Owner.Name) == "" {
		p.Owner.Name = "owner"
	}
	p.Owner.Name = strings.TrimSpace(p.Owner.Name)
	p.Owner.Home.Country = strings.ToUpper(strings.TrimSpace(p.Owner.Home.Country))
	s := &p.Search
	upper := func(xs []string) {
		for i, x := range xs {
			xs[i] = strings.ToUpper(strings.TrimSpace(x))
		}
	}
	lower := func(xs []string) {
		for i, x := range xs {
			xs[i] = strings.ToLower(strings.TrimSpace(x))
		}
	}
	upper(s.Countries)
	upper(s.ExcludeRegions)
	lower(s.Powertrain)
	for i := range s.HardFilters {
		upper(s.HardFilters[i].MentionsCountry)
	}
	for i := range s.Models {
		if w := s.Models[i].When; w != nil {
			lower(w.Drive)
			lower(w.Fuel)
		}
	}
	if s.DefaultTier <= 0 {
		maxTier := 0
		for _, m := range s.Models {
			maxTier = max(maxTier, m.Tier)
		}
		s.DefaultTier = maxTier + 1
	}
	if len(s.QueueDefaultTiers) == 0 {
		for t := 1; t < s.DefaultTier; t++ {
			s.QueueDefaultTiers = append(s.QueueDefaultTiers, t)
		}
		if len(s.QueueDefaultTiers) == 0 {
			s.QueueDefaultTiers = []int{s.DefaultTier}
		}
	}
	if s.RoadFactor <= 0 {
		s.RoadFactor = 1.3
	}
	if s.Weights == nil {
		s.Weights = map[string]float64{}
	}
	for _, k := range []string{"value", "fit", "risk"} {
		if _, ok := s.Weights[k]; !ok {
			s.Weights[k] = 1
		}
	}
	if s.Price.Currency == "" {
		s.Price.Currency = "EUR"
	}
	p.Search.Ranking.applyDefaults(p)
}

// Users is the owner followed by the configured viewers.
func (p *Profile) Users() []User {
	out := []User{{Name: p.Owner.Name, Role: "owner"}}
	for _, u := range p.Cardb.Users {
		out = append(out, User{Name: strings.TrimSpace(u.Name), Role: "viewer"})
	}
	return out
}

// User finds a user by name (case-insensitive).
func (p *Profile) User(name string) (User, bool) {
	for _, u := range p.Users() {
		if strings.EqualFold(u.Name, strings.TrimSpace(name)) {
			return u, true
		}
	}
	return User{}, false
}

// Tiers lists every tier the profile defines (1…DefaultTier).
func (p *Profile) Tiers() []int {
	out := make([]int, 0, p.Search.DefaultTier)
	for t := 1; t <= p.Search.DefaultTier; t++ {
		out = append(out, t)
	}
	return out
}

// Weight returns search.weights[name] (value, fit, risk).
func (p *Profile) Weight(name string) float64 { return p.Search.Weights[name] }

// HomeMarket reports whether an ISO-2 country is the owner's home country (false when either is unknown).
func (p *Profile) HomeMarket(country string) bool {
	return p.Owner.Home.Country != "" && strings.EqualFold(country, p.Owner.Home.Country)
}
