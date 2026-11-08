// Package profile loads the buyer profile cardb ranks and filters with: the `owner`, `search` and `cardb`
// sections of $CARHUNT_HOME/config.yaml. Nothing buyer-specific lives in Go; this is the only input.
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
	City    string  `yaml:"city" json:"city"`
	Country string  `yaml:"country" json:"country"` // ISO-2, upper case
	Lat     float64 `yaml:"lat" json:"lat"`
	Lon     float64 `yaml:"lon" json:"lon"`
}

// Cardb is the server's own config section (secrets are references, never values).
type Cardb struct {
	URL     string `yaml:"url"`
	DataDir string `yaml:"data_dir"`
	Users   []User `yaml:"users"` // viewers (the owner is implicit)
}

// User is one person who can rate cars.
type User struct {
	Name string `yaml:"name" json:"name"`
	Role string `yaml:"role" json:"role"` // owner | viewer
}

// Search is the buyer profile proper: scope, queue tiers, hard filters, weights.
type Search struct {
	Countries            []string           `yaml:"countries" json:"countries"`
	PrivateSellersAbroad *bool              `yaml:"private_sellers_abroad" json:"private_sellers_abroad,omitempty"`
	ExcludeRegions       []string           `yaml:"exclude_regions" json:"exclude_regions,omitempty"` // ISO 3166-2 (PT-20 …)
	ExcludePlaces        []string           `yaml:"exclude_places" json:"exclude_places,omitempty"`   // extra city words
	Price                Price              `yaml:"price" json:"price"`
	YearMin              int                `yaml:"year_min" json:"year_min,omitempty"`
	KmMax                int                `yaml:"km_max" json:"km_max,omitempty"`
	Powertrain           []string           `yaml:"powertrain" json:"powertrain,omitempty"` // allowed fuels (BEV, PHEV, …); empty = any
	Models               []Model            `yaml:"models" json:"models,omitempty"`
	DefaultTier          int                `yaml:"default_tier" json:"default_tier"`
	QueueDefaultTiers    []int              `yaml:"queue_default_tiers" json:"queue_default_tiers"`
	Families             []FamilyRule       `yaml:"families" json:"-"`
	HardFilters          []HardFilter       `yaml:"hard_filters" json:"hard_filters,omitempty"`
	OptionsWanted        map[string]float64 `yaml:"options_wanted" json:"options_wanted,omitempty"`
	MustHave             []string           `yaml:"must_have" json:"must_have,omitempty"`
	OptionKeys           []string           `yaml:"option_keys" json:"option_keys,omitempty"`
	Penalties            []Penalty          `yaml:"penalties" json:"penalties,omitempty"`
	Weights              map[string]float64 `yaml:"weights" json:"weights,omitempty"` // value, fit, risk
	RoadFactor           float64            `yaml:"road_factor" json:"road_factor,omitempty"`
	Ranking              Ranking            `yaml:"ranking" json:"ranking"`
}

// Price scope + sanity bounds (integer currency units, gross).
type Price struct {
	MaxEUR   int    `yaml:"max_eur" json:"max_eur,omitempty"`
	MinEUR   int    `yaml:"min_eur" json:"min_eur,omitempty"`
	CapEUR   int    `yaml:"cap_eur" json:"cap_eur,omitempty"` // sanity: refuse prices above (cardb default 2 000 000)
	Gross    *bool  `yaml:"gross" json:"gross,omitempty"`
	Currency string `yaml:"currency" json:"currency,omitempty"`
}

// Model is one wanted make/model family with its queue tier; `When` narrows it (first match wins).
type Model struct {
	Make    string  `yaml:"make" json:"make"`
	Model   string  `yaml:"model" json:"model"`
	Tier    int     `yaml:"tier" json:"tier"`
	Label   string  `yaml:"label" json:"label,omitempty"`
	BaseFit float64 `yaml:"base_fit" json:"base_fit,omitempty"`
	Risk    float64 `yaml:"risk" json:"risk,omitempty"` // model-specific risk (known weak points)
	When    *When   `yaml:"when" json:"when,omitempty"`
}

// When: every set condition must hold. Unknown car values: see the ranking package doc.
type When struct {
	PowerHP       []float64 `yaml:"power_hp" json:"power_hp,omitempty"`         // [min, max]
	Drive         []string  `yaml:"drive" json:"drive,omitempty"`               // allowed: fwd rwd awd
	VariantAny    []string  `yaml:"variant_any" json:"variant_any,omitempty"`   // a token present in model+variant
	VariantNone   []string  `yaml:"variant_none" json:"variant_none,omitempty"` // none of these tokens
	YearMin       int       `yaml:"year_min" json:"year_min,omitempty"`
	BatteryNetKwh []float64 `yaml:"battery_net_kwh" json:"battery_net_kwh,omitempty"` // [min, max]
	Fuel          []string  `yaml:"fuel" json:"fuel,omitempty"`
}

// FamilyRule adds or overrides a model-family recognition rule (see store.Family).
type FamilyRule struct {
	Make     string   `yaml:"make"`
	Name     string   `yaml:"name"`
	Match    []string `yaml:"match"`
	With     []string `yaml:"with"`
	Lead     bool     `yaml:"lead"`
	Bare     bool     `yaml:"bare"`
	Body     []string `yaml:"body"`
	BodyName string   `yaml:"body_name"`
}

// HardFilter is one queue exclusion rule. Exactly one of Field / Fact(s) / Flag is set.
type HardFilter struct {
	Field           string   `yaml:"field" json:"field,omitempty"` // car field, e.g. powertrain.battery_net_kwh, wheels_in
	Min             *float64 `yaml:"min" json:"min,omitempty"`
	Max             *float64 `yaml:"max" json:"max,omitempty"`
	Fact            string   `yaml:"fact" json:"fact,omitempty"`
	Facts           []string `yaml:"facts" json:"facts,omitempty"`
	Words           []string `yaml:"words" json:"words,omitempty"`                       // folded whole words
	MentionsCountry []string `yaml:"mentions_country" json:"mentions_country,omitempty"` // ISO-2, names in EU languages
	Flag            string   `yaml:"flag" json:"flag,omitempty"`
	Label           string   `yaml:"label" json:"label,omitempty"`
}

// Penalty lowers the trim score / fit when a numeric field is at or above Min (or at/below Max).
type Penalty struct {
	Field  string   `yaml:"field" json:"field"`
	Min    *float64 `yaml:"min" json:"min,omitempty"`
	Max    *float64 `yaml:"max" json:"max,omitempty"`
	Weight float64  `yaml:"weight" json:"weight"`
	Label  string   `yaml:"label" json:"label,omitempty"`
}

// Ranking holds the value model's tunables (landed cost, fit, risk). Zero values get defaults in applyDefaults.
type Ranking struct {
	LandedCost map[string]any `yaml:"landed_cost" json:"landed_cost,omitempty"`
	Fit        map[string]any `yaml:"fit" json:"fit,omitempty"`
	Risk       map[string]any `yaml:"risk" json:"risk,omitempty"`
	Peers      map[string]any `yaml:"peers" json:"peers,omitempty"`
}

// Default is the neutral profile used when no config file exists: no filters, one tier.
func Default() *Profile {
	p := &Profile{}
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

// Parse parses YAML bytes into a defaulted, validated profile.
func Parse(b []byte) (*Profile, error) {
	var p Profile
	dec := yaml.NewDecoder(bytes.NewReader(b))
	if err := dec.Decode(&p); err != nil && !errors.Is(err, io.EOF) {
		return nil, err
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
	for i, c := range p.Search.Countries {
		p.Search.Countries[i] = strings.ToUpper(strings.TrimSpace(c))
	}
	if p.Search.DefaultTier <= 0 {
		maxTier := 0
		for _, m := range p.Search.Models {
			maxTier = max(maxTier, m.Tier)
		}
		p.Search.DefaultTier = maxTier + 1
	}
	if len(p.Search.QueueDefaultTiers) == 0 {
		for t := 1; t < p.Search.DefaultTier; t++ {
			p.Search.QueueDefaultTiers = append(p.Search.QueueDefaultTiers, t)
		}
		if len(p.Search.QueueDefaultTiers) == 0 {
			p.Search.QueueDefaultTiers = []int{p.Search.DefaultTier}
		}
	}
	if p.Search.RoadFactor <= 0 {
		p.Search.RoadFactor = 1.3
	}
	if p.Search.Weights == nil {
		p.Search.Weights = map[string]float64{}
	}
	for _, k := range []string{"value", "fit", "risk"} {
		if _, ok := p.Search.Weights[k]; !ok {
			p.Search.Weights[k] = 1
		}
	}
	if p.Search.Price.Currency == "" {
		p.Search.Price.Currency = "EUR"
	}
}

// Validate rejects a profile cardb cannot apply (with the offending key in the message).
func (p *Profile) Validate() error {
	var errs []string
	seen := map[string]bool{strings.ToLower(p.Owner.Name): true}
	for _, u := range p.Cardb.Users {
		n := strings.ToLower(strings.TrimSpace(u.Name))
		switch {
		case n == "":
			errs = append(errs, "cardb.users: empty name")
		case seen[n]:
			errs = append(errs, fmt.Sprintf("cardb.users: duplicate name %q", u.Name))
		case u.Role != "" && u.Role != "viewer":
			errs = append(errs, fmt.Sprintf("cardb.users[%s].role: want viewer (the owner is owner.name)", u.Name))
		}
		seen[n] = true
	}
	for i, m := range p.Search.Models {
		if m.Tier < 1 {
			errs = append(errs, fmt.Sprintf("search.models[%d] (%s %s): tier must be ≥ 1", i, m.Make, m.Model))
		}
		if m.Tier >= p.Search.DefaultTier {
			errs = append(errs, fmt.Sprintf("search.models[%d]: tier %d ≥ default_tier %d", i, m.Tier, p.Search.DefaultTier))
		}
	}
	if len(errs) > 0 {
		return errors.New("profile: " + strings.Join(errs, "; "))
	}
	return nil
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
