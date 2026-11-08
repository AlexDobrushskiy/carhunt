package api

// Profile is GET /profile: the effective buyer profile (defaults applied), no secrets.
type Profile struct {
	Owner             ProfileOwner       `json:"owner"`
	Users             []ProfileUser      `json:"users"`
	Tiers             []ProfileTier      `json:"tiers"`
	DefaultTier       int                `json:"default_tier"`
	QueueDefaultTiers []int              `json:"queue_default_tiers"`
	OptionKeys        []string           `json:"option_keys"`
	OptionsWanted     map[string]float64 `json:"options_wanted"`
	MustHave          []string           `json:"must_have"`
	HardFilters       []string           `json:"hard_filters"`
	Countries         []string           `json:"countries"`
	Currency          string             `json:"currency"`
	Weights           map[string]float64 `json:"weights"`
	Families          []string           `json:"families"`
	Ranking           any                `json:"ranking"`
	Warnings          []string           `json:"warnings"`
}

type ProfileOwner struct {
	Name string      `json:"name"`
	TZ   string      `json:"tz"`
	Home ProfileHome `json:"home"`
}

type ProfileHome struct {
	City    string   `json:"city"`
	Country string   `json:"country"`
	Lat     *float64 `json:"lat"`
	Lon     *float64 `json:"lon"`
}

type ProfileUser struct {
	Name string `json:"name"`
	Role string `json:"role"`
}

// ProfileTier: one queue tier with the human-readable rule lines that select it.
type ProfileTier struct {
	Tier  int      `json:"tier"`
	Label string   `json:"label"`
	Rules []string `json:"rules"`
}
