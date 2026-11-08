// Package api holds the JSON wire types shared by the server, the client and the CLI.
// It mirrors api/openapi.yaml; keep both in sync.
package api

import (
	"encoding/json"
	"time"
)

var Statuses = []string{"new", "to_contact", "contacted", "talking", "ready_to_visit", "visited", "closed", "dropped", "bought"}

var (
	SellerTypes     = []string{"private", "dealer", "reseller", "unknown"}
	VerdictValues   = []string{"up", "maybe", "down"}
	ListingStatuses = []string{"live", "removed", "sold", "unknown"}
	OptionValues    = []string{"yes", "no", "unknown"}
	EvidenceSources = []string{"ad_text", "ad_spec", "photo", "vin_pr_code", "vin_decoder", "seller_said", "inspection", "agent_inference", "owner"}
	PhotoSources    = []string{"ad", "seller", "inspection", "other"}
	Fuels           = []string{"bev", "phev", "hev", "mhev", "petrol", "diesel", "lpg", "cng", "hydrogen", "unknown"}
	Gearboxes       = []string{"manual", "automatic", "unknown"}
	PriceVats       = []string{"gross", "net", "margin", "unknown"} // gross = incl. VAT (what cardb stores)
	PriceFlags      = []string{"price_x100", "price_lease", "price_net", "price_range"}
	OptionKeys      = []string{"pano", "pano_opening", "power_tailgate", "electric_seats", "memory_seats", "heated_seats", "ventilated_seats", "premium_audio", "hud", "camera_360", "adaptive_cruise", "heat_pump", "towbar", "matrix_led", "keyless", "massage_seats", "rear_recline", "air_suspension", "adaptive_dampers"}
)

type Error struct {
	Error string `json:"error"`
}

type Health struct {
	OK      bool   `json:"ok"`
	Version string `json:"version"`
}

type Stats struct {
	Total              int            `json:"total"`
	ByStatus           map[string]int `json:"by_status"`
	ByVerdict          map[string]int `json:"by_verdict"`
	NeedsOwner         int            `json:"needs_owner"`
	DuplicateProposals int            `json:"duplicate_proposals"`
	Listings           int            `json:"listings"`
	Messages           int            `json:"messages"`
}

// CarSpecs are the canonical vehicle fields. Pointers: nil = unknown / not sent.
// Powertrain: fuel/drive-train facts, every field optional (nil = unknown). Stored as flat car columns.
// PATCH merges it field by field (a raw `"powertrain": {"engine_cc": null}` clears one field).
type Powertrain struct {
	Fuel            *string  `json:"fuel,omitempty"` // bev phev hev mhev petrol diesel lpg cng hydrogen unknown
	BatteryNetKwh   *float64 `json:"battery_net_kwh,omitempty"`
	BatteryGrossKwh *float64 `json:"battery_gross_kwh,omitempty"`
	EngineCc        *int     `json:"engine_cc,omitempty"`
	Gearbox         *string  `json:"gearbox,omitempty"` // manual automatic unknown
	WltpRangeKm     *int     `json:"wltp_range_km,omitempty"`
	WltpConsumption *float64 `json:"wltp_consumption,omitempty"`
	Co2GKm          *int     `json:"co2_g_km,omitempty"`
}

// Empty reports whether no field is set.
func (p *Powertrain) Empty() bool {
	return p == nil || (p.Fuel == nil && p.BatteryNetKwh == nil && p.BatteryGrossKwh == nil && p.EngineCc == nil &&
		p.Gearbox == nil && p.WltpRangeKm == nil && p.WltpConsumption == nil && p.Co2GKm == nil)
}

type CarSpecs struct {
	Make         *string     `json:"make,omitempty"`
	Model        *string     `json:"model,omitempty"`
	Variant      *string     `json:"variant,omitempty"`
	Body         *string     `json:"body,omitempty"`
	RegDate      *string     `json:"reg_date,omitempty"`
	Year         *int        `json:"year,omitempty"` // read-only, derived from reg_date
	Km           *int        `json:"km,omitempty"`
	Powertrain   *Powertrain `json:"powertrain,omitempty"`
	PowerKw      *float64    `json:"power_kw,omitempty"`
	Drive        *string     `json:"drive,omitempty"`
	Seats        *int        `json:"seats,omitempty"`
	Colour       *string     `json:"colour,omitempty"`
	Interior     *string     `json:"interior,omitempty"`
	InteriorTone *string     `json:"interior_tone,omitempty"`
	WheelsIn     *int        `json:"wheels_in,omitempty"`
	VIN          *string     `json:"vin,omitempty"`
	Plate        *string     `json:"plate,omitempty"`
	Country      *string     `json:"country,omitempty"`
	City         *string     `json:"city,omitempty"`
	DistanceKm   *int        `json:"distance_km,omitempty"`
	Market       *string     `json:"market,omitempty"` // read-only
}

type CarInput struct {
	CarSpecs
	Slug             *string      `json:"slug,omitempty"`
	Aliases          []string     `json:"aliases,omitempty"`
	Summary          *string      `json:"summary,omitempty"`
	Status           *string      `json:"status,omitempty"`
	StatusReason     *string      `json:"status_reason,omitempty"`
	NeedsOwner       *bool        `json:"needs_owner,omitempty"`
	NeedsOwnerReason *string      `json:"needs_owner_reason,omitempty"`
	Seller           *SellerInput `json:"seller,omitempty"`
	RedFlags         []string     `json:"red_flags,omitempty"`
	OpenQuestions    []string     `json:"open_questions,omitempty"`
	Author           string       `json:"author,omitempty"`
}

// CarPatch is sent as raw JSON; the server reads it as a map so that explicit nulls clear fields.
// This struct is the client-side convenience form (no way to send null from it).
type CarPatch struct {
	CarInput
	SellerID    *int64     `json:"seller_id,omitempty"`
	ModelFamily *string    `json:"model_family,omitempty"` // manual override; send null in a raw patch to go back to auto
	At          *time.Time `json:"at,omitempty"`           // event/updated time; default now (imports pass the original time)
	// Exact-text list edits, applied atomically against the current lists (can't be combined with a full replace).
	RedFlagsAdd         []string `json:"red_flags_add,omitempty"`
	RedFlagsRemove      []string `json:"red_flags_remove,omitempty"`
	OpenQuestionsAdd    []string `json:"open_questions_add,omitempty"`
	OpenQuestionsRemove []string `json:"open_questions_remove,omitempty"`
	Version             *int64   `json:"version,omitempty"` // same as If-Match: stale → 412
}

type CarSummary struct {
	ID                      int64             `json:"id"`
	Slug                    *string           `json:"slug"`
	Title                   string            `json:"title"`
	Make                    *string           `json:"make"`
	Model                   *string           `json:"model"`
	Variant                 *string           `json:"variant"`
	Year                    *int              `json:"year"`
	RegDate                 *string           `json:"reg_date"`
	Km                      *int              `json:"km"`
	Powertrain              *Powertrain       `json:"powertrain,omitempty"`
	PowerKw                 *float64          `json:"power_kw"`
	Drive                   *string           `json:"drive"`
	Country                 *string           `json:"country"`
	City                    *string           `json:"city"`
	DistanceKm              *int              `json:"distance_km"`
	Market                  *string           `json:"market"`
	Interior                *string           `json:"interior"`
	InteriorTone            *string           `json:"interior_tone"`
	WheelsIn                *int              `json:"wheels_in"`
	SellerType              string            `json:"seller_type"`
	SellerName              *string           `json:"seller_name"`
	Price                   *int              `json:"price"`
	PriceNote               *string           `json:"price_note"`
	PriceDrop               *int              `json:"price_drop"`
	ListingCount            int               `json:"listing_count"`
	LiveListingCount        int               `json:"live_listing_count"`
	Sites                   []string          `json:"sites"`
	PrimaryURL              *string           `json:"primary_url"`
	CoverPhotoID            *int64            `json:"cover_photo_id"`
	PhotoCount              int               `json:"photo_count"`
	Options                 map[string]string `json:"options"`
	OptionSources           map[string]string `json:"option_sources"`
	Status                  string            `json:"status"`
	StatusReason            *string           `json:"status_reason"`
	Verdict                 *Verdict          `json:"verdict"`
	NeedsOwner              bool              `json:"needs_owner"`
	NeedsOwnerReason        *string           `json:"needs_owner_reason"`
	Summary                 *string           `json:"summary"`
	MessageCount            int               `json:"message_count"`
	LastMessageAt           *time.Time        `json:"last_message_at"`
	LastMessageDirection    *string           `json:"last_message_direction"`
	LastActivityAt          time.Time         `json:"last_activity_at"`
	DuplicateCandidateCount int               `json:"duplicate_candidate_count"`
	CreatedAt               time.Time         `json:"created_at"`
	// Model family: canonical "<Make> <Family>" (see GET /model-families); manual = set by PATCH model_family.
	ModelFamily       *string `json:"model_family"`
	ModelFamilyManual bool    `json:"model_family_manual"`
	// Good deal flag (PUT /cars/{car}/good-deal); by/at = last change. DealRank = the deal_rank fact.
	GoodDeal     bool       `json:"good_deal"`
	GoodDealNote *string    `json:"good_deal_note"`
	GoodDealBy   *string    `json:"good_deal_by"`
	GoodDealAt   *time.Time `json:"good_deal_at"`
	DealRank     *string    `json:"deal_rank"`
	// RemovedListingCount = listings with status removed. Tier = "To rate" tier 1|2|3 (see GET /queue).
	RemovedListingCount int `json:"removed_listing_count"`
	Tier                int `json:"tier"`
	// Version increments on every car write (ETag / If-Match). PriceFlags = flags of the listing that gives Price.
	Version    int64    `json:"version"`
	PriceFlags []string `json:"price_flags,omitempty"`

	// Verdicts = every user's verdict by user name; Verdict above = the selected user's (?user=, default owner).
	Verdicts map[string]*Verdict `json:"verdicts"`
}

type CarList struct {
	Total int          `json:"total"`
	Cars  []CarSummary `json:"cars"`
}

// CarDetail embeds CarSpecs; on the wire spec fields sit at the top level.
type CarDetail struct {
	CarSpecs
	ID               int64                `json:"id"`
	Slug             *string              `json:"slug"`
	Title            string               `json:"title"`
	Aliases          []string             `json:"aliases"`
	Summary          *string              `json:"summary"`
	Status           string               `json:"status"`
	StatusReason     *string              `json:"status_reason"`
	StatusChangedAt  *time.Time           `json:"status_changed_at"`
	NeedsOwner       bool                 `json:"needs_owner"`
	NeedsOwnerReason *string              `json:"needs_owner_reason"`
	RedFlags         []string             `json:"red_flags"`
	OpenQuestions    []string             `json:"open_questions"`
	Price            *int                 `json:"price"`
	PriceNote        *string              `json:"price_note"`
	Seller           *Seller              `json:"seller"`
	Listings         []Listing            `json:"listings"`
	Options          []Option             `json:"options"`
	Facts            []Fact               `json:"facts"`
	Photos           []Photo              `json:"photos"`
	Events           []Event              `json:"events"`
	Messages         []Message            `json:"messages"`
	Notes            []Note               `json:"notes"`
	Verdict          *Verdict             `json:"verdict"`
	Duplicates       []DuplicateCandidate `json:"duplicates"`
	MergedFrom       []int64              `json:"merged_from"`
	CreatedAt        time.Time            `json:"created_at"`
	UpdatedAt        time.Time            `json:"updated_at"`
	// Model family: canonical "<Make> <Family>" (see GET /model-families); manual = set by PATCH model_family.
	ModelFamily       *string `json:"model_family"`
	ModelFamilyManual bool    `json:"model_family_manual"`
	// Good deal flag (PUT /cars/{car}/good-deal); by/at = last change. DealRank = the deal_rank fact.
	GoodDeal     bool       `json:"good_deal"`
	GoodDealNote *string    `json:"good_deal_note"`
	GoodDealBy   *string    `json:"good_deal_by"`
	GoodDealAt   *time.Time `json:"good_deal_at"`
	DealRank     *string    `json:"deal_rank"`
	Version      int64      `json:"version"` // increments on every car write; ETag / If-Match
	// Verdicts = every user's verdict by user name; Verdict = the selected user's (?user=, default owner).
	Verdicts map[string]*Verdict `json:"verdicts"`
}

type Listing struct {
	ID           int64           `json:"id"`
	CarID        int64           `json:"car_id"`
	URL          string          `json:"url"`
	Site         string          `json:"site"`
	SiteRef      *string         `json:"site_ref"`
	Title        *string         `json:"title"`
	Status       string          `json:"status"`
	Price        *int            `json:"price"`
	PriceNote    *string         `json:"price_note"`
	PriceVat     string          `json:"price_vat"`   // gross|net|margin|unknown
	PriceFlags   []string        `json:"price_flags"` // set when the price was forced past the sanity check
	PriceHistory []PricePoint    `json:"price_history"`
	SellerID     *int64          `json:"seller_id"`
	FirstSeenAt  time.Time       `json:"first_seen_at"`
	LastSeenAt   time.Time       `json:"last_seen_at"`
	RemovedAt    *time.Time      `json:"removed_at"`
	Raw          json.RawMessage `json:"raw"`
}

type PricePoint struct {
	Price int       `json:"price"`
	At    time.Time `json:"at"`
	Note  *string   `json:"note"`
}

type ListingUpsert struct {
	CarSpecs
	URL           string                 `json:"url"`
	Site          string                 `json:"site,omitempty"`
	Title         string                 `json:"title,omitempty"`
	Price         *int                   `json:"price,omitempty"`
	PriceNote     string                 `json:"price_note,omitempty"`
	PriceVat      string                 `json:"price_vat,omitempty"` // gross|net|margin|unknown
	Force         bool                   `json:"force,omitempty"`     // store a price that fails the sanity check (flagged)
	ListingStatus string                 `json:"listing_status,omitempty"`
	SeenAt        *time.Time             `json:"seen_at,omitempty"`
	Car           string                 `json:"car,omitempty"`
	Slug          string                 `json:"slug,omitempty"`
	Aliases       []string               `json:"aliases,omitempty"`
	Summary       string                 `json:"summary,omitempty"`
	Status        string                 `json:"status,omitempty"`
	Seller        *SellerInput           `json:"seller,omitempty"`
	Options       map[string]OptionInput `json:"options,omitempty"`
	Facts         map[string]FactInput   `json:"facts,omitempty"`
	PhotoURLs     []string               `json:"photo_urls,omitempty"`
	Overwrite     bool                   `json:"overwrite,omitempty"`
	Raw           json.RawMessage        `json:"raw,omitempty"`
	Author        string                 `json:"author,omitempty"`
}

type UpsertResult struct {
	CarID               int64                `json:"car_id"`
	ListingID           int64                `json:"listing_id"`
	ListingCreated      bool                 `json:"listing_created"`
	CarCreated          bool                 `json:"car_created"`
	LinkedBy            *string              `json:"linked_by"`
	PriceChanged        bool                 `json:"price_changed"`
	Relisted            bool                 `json:"relisted"` // a removed/sold listing went back to live
	DuplicateCandidates []DuplicateCandidate `json:"duplicate_candidates"`
	PhotoErrors         []string             `json:"photo_errors"`
}

type ListingPatch struct {
	Status    string `json:"status,omitempty"`
	Price     *int   `json:"price,omitempty"`
	PriceNote string `json:"price_note,omitempty"`
	PriceVat  string `json:"price_vat,omitempty"`
	Force     bool   `json:"force,omitempty"`
	Author    string `json:"author,omitempty"`
}

type Option struct {
	Key       string    `json:"key"`
	Value     string    `json:"value"`
	Source    string    `json:"source"`
	SourceRef *string   `json:"source_ref"`
	Note      *string   `json:"note"`
	Author    string    `json:"author"`
	UpdatedAt time.Time `json:"updated_at"`
}

type OptionInput struct {
	Value     string     `json:"value"`
	Source    string     `json:"source,omitempty"`
	SourceRef string     `json:"source_ref,omitempty"`
	Note      string     `json:"note,omitempty"`
	Author    string     `json:"author,omitempty"`
	At        *time.Time `json:"at,omitempty"`
}

type Fact struct {
	Key       string    `json:"key"`
	Value     string    `json:"value"`
	Source    string    `json:"source"`
	SourceRef *string   `json:"source_ref"`
	Author    string    `json:"author"`
	UpdatedAt time.Time `json:"updated_at"`
}

type FactInput struct {
	Value     string     `json:"value"`
	Source    string     `json:"source,omitempty"`
	SourceRef string     `json:"source_ref,omitempty"`
	Author    string     `json:"author,omitempty"`
	At        *time.Time `json:"at,omitempty"`
}

type Photo struct {
	ID        int64     `json:"id"`
	CarID     int64     `json:"car_id"`
	ListingID *int64    `json:"listing_id"`
	Position  int       `json:"position"`
	Cover     bool      `json:"cover"`
	Caption   *string   `json:"caption"`
	Source    string    `json:"source"`
	SourceRef *string   `json:"source_ref"`
	Width     int       `json:"width"`
	Height    int       `json:"height"`
	PHash     string    `json:"phash"`
	URL       string    `json:"url"`
	CreatedAt time.Time `json:"created_at"`
}

type PhotoURLInput struct {
	URL       string `json:"url"`
	Caption   string `json:"caption,omitempty"`
	Source    string `json:"source,omitempty"`
	SourceRef string `json:"source_ref,omitempty"`
	ListingID *int64 `json:"listing_id,omitempty"`
	Position  *int   `json:"position,omitempty"`
}

type PhotoPatch struct {
	Caption  *string `json:"caption,omitempty"`
	Position *int    `json:"position,omitempty"`
	Cover    *bool   `json:"cover,omitempty"`
}

type Event struct {
	ID        int64           `json:"id"`
	CarID     int64           `json:"car_id"`
	ListingID *int64          `json:"listing_id"`
	Type      string          `json:"type"`
	At        time.Time       `json:"at"`
	Author    string          `json:"author"`
	Summary   string          `json:"summary"`
	Data      json.RawMessage `json:"data"`
}

type EventInput struct {
	Type      string          `json:"type"`
	Summary   string          `json:"summary"`
	At        *time.Time      `json:"at,omitempty"`
	Data      json.RawMessage `json:"data,omitempty"`
	ListingID *int64          `json:"listing_id,omitempty"`
	DedupeKey string          `json:"dedupe_key,omitempty"`
	Author    string          `json:"author,omitempty"`
}

type Message struct {
	ID          int64        `json:"id"`
	CarID       int64        `json:"car_id"`
	Channel     string       `json:"channel"`
	Direction   string       `json:"direction"`
	At          time.Time    `json:"at"`
	SenderKind  string       `json:"sender_kind"`
	Sender      string       `json:"sender"`
	Counterpart *string      `json:"counterpart"`
	Text        string       `json:"text"`
	Attachments []Attachment `json:"attachments"`
	Delivery    string       `json:"delivery"`
	Error       *string      `json:"error"`
	ExternalID  *string      `json:"external_id"`
	DedupeKey   *string      `json:"dedupe_key"` // read-only; server-derived keys start with "auto:" / "ext:"
	// Soft delete: deleted rows are hidden from every read; POST /messages may still return one by its key.
	DeletedAt     *time.Time `json:"deleted_at,omitempty"`
	DeletedBy     *string    `json:"deleted_by,omitempty"`
	DeletedReason *string    `json:"deleted_reason,omitempty"`
	// POST /messages only, when nothing was inserted: external_id | dedupe_key | near_duplicate.
	MatchedBy string `json:"matched_by,omitempty"`
}

// MessageDuplicate is a pair of live rows that look like one message logged twice (GET /messages/duplicates).
type MessageDuplicate struct {
	CarID   int64   `json:"car_id"`
	Keep    Message `json:"keep"`
	Drop    Message `json:"drop"`
	Seconds float64 `json:"seconds"` // time between the two
}

type MessageInput struct {
	Car         string       `json:"car,omitempty"`
	ListingURL  string       `json:"listing_url,omitempty"`
	Counterpart string       `json:"counterpart,omitempty"`
	Channel     string       `json:"channel"`
	Direction   string       `json:"direction"`
	At          *time.Time   `json:"at,omitempty"`
	SenderKind  string       `json:"sender_kind,omitempty"`
	Sender      string       `json:"sender,omitempty"`
	Text        string       `json:"text"`
	Attachments []Attachment `json:"attachments,omitempty"`
	Delivery    string       `json:"delivery,omitempty"`
	Error       string       `json:"error,omitempty"`
	ExternalID  string       `json:"external_id,omitempty"`
	DedupeKey   string       `json:"dedupe_key,omitempty"`
	Author      string       `json:"author,omitempty"`
	// AllowDuplicate skips the near-duplicate check (an intentional repeat of the same text).
	AllowDuplicate bool `json:"allow_duplicate,omitempty"`
}

// MessagePatch edits a logged message (PATCH /messages/{id}). Sent fields replace; error "" clears it.
type MessagePatch struct {
	Text        *string       `json:"text,omitempty"`
	Attachments *[]Attachment `json:"attachments,omitempty"`
	Delivery    *string       `json:"delivery,omitempty"`
	Error       *string       `json:"error,omitempty"`
}

type Attachment struct {
	Kind    string  `json:"kind"`
	Name    *string `json:"name,omitempty"`
	Mime    *string `json:"mime,omitempty"`
	PhotoID *int64  `json:"photo_id,omitempty"`
	URL     *string `json:"url,omitempty"`
}

type Note struct {
	ID         int64     `json:"id"`
	CarID      int64     `json:"car_id"`
	Author     string    `json:"author"`
	AuthorKind string    `json:"author_kind"`
	Text       string    `json:"text"`
	Pinned     bool      `json:"pinned"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

type NoteInput struct {
	Text   string     `json:"text"`
	Pinned bool       `json:"pinned,omitempty"`
	Author string     `json:"author,omitempty"`
	At     *time.Time `json:"at,omitempty"`
}

type NotePatch struct {
	Text   *string `json:"text,omitempty"`
	Pinned *bool   `json:"pinned,omitempty"`
}

type Verdict struct {
	User      string    `json:"user"`
	Value     string    `json:"value"`
	Note      *string   `json:"note"`
	Author    string    `json:"author"`
	UpdatedAt time.Time `json:"updated_at"`
}

type VerdictInput struct {
	Value  string     `json:"value"`
	Note   string     `json:"note,omitempty"`
	User   string     `json:"user,omitempty"`
	Author string     `json:"author,omitempty"`
	At     *time.Time `json:"at,omitempty"`
}

// GoodDeal is a car's good-deal flag (PUT /cars/{car}/good-deal). By/At = who last changed it and when.
type GoodDeal struct {
	GoodDeal bool       `json:"good_deal"`
	Note     *string    `json:"note"`
	By       *string    `json:"by"`
	At       *time.Time `json:"at"`
}

// GoodDealInput: Note nil = keep the current note while staying on; "" (or JSON null) clears it. Off always clears.
type GoodDealInput struct {
	GoodDeal *bool      `json:"good_deal"`
	Note     *string    `json:"note,omitempty"`
	Author   string     `json:"author,omitempty"`
	At       *time.Time `json:"at,omitempty"`
}

// ModelFamilies is GET /model-families: families present among live cars with counts, plus every known name.
type ModelFamilies struct {
	Families []ModelFamilyCount `json:"families"`
	Unmapped int                `json:"unmapped"`
	Known    []string           `json:"known"`
}

type ModelFamilyCount struct {
	Family string `json:"family"`
	Make   string `json:"make"`
	Count  int    `json:"count"`
}

// Queue is GET /queue: eligible unrated cars in "To rate" order. Counts = eligible per tier ("1","2","3"), ignoring the tier param.
type Queue struct {
	Total  int            `json:"total"`
	Counts map[string]int `json:"counts"`
	Items  []QueueItem    `json:"items"`
}

// QueueItem: Position is 1-based within the selected tiers. TrimScoreSource = fact | options.
// Fair price = median price of live cars in the same model family + year (n ≥ 3), else the family (n ≥ 3), else none.
type QueueItem struct {
	Position        int        `json:"position"`
	Tier            int        `json:"tier"`
	Car             CarSummary `json:"car"`
	TrimScore       float64    `json:"trim_score"`
	TrimScoreSource string     `json:"trim_score_source"`
	FairPrice       *int       `json:"fair_price"`
	FairN           int        `json:"fair_n"`
	FairBasis       *string    `json:"fair_basis"`
	PriceGapPct     *float64   `json:"price_gap_pct"`
	Why             string     `json:"why"`
}

type StatusInput struct {
	Status  string     `json:"status"`
	Reason  string     `json:"reason,omitempty"`
	Version *int64     `json:"version,omitempty"` // same as If-Match: stale → 412
	Author  string     `json:"author,omitempty"`
	At      *time.Time `json:"at,omitempty"`
}

type Seller struct {
	ID       int64     `json:"id"`
	Name     *string   `json:"name"`
	Type     string    `json:"type"`
	Company  *string   `json:"company"`
	City     *string   `json:"city"`
	Note     *string   `json:"note"`
	Contacts []Contact `json:"contacts"`
	CarIDs   []int64   `json:"car_ids"`
}

type SellerInput struct {
	Name     *string   `json:"name,omitempty"`
	Type     *string   `json:"type,omitempty"`
	Company  *string   `json:"company,omitempty"`
	City     *string   `json:"city,omitempty"`
	Note     *string   `json:"note,omitempty"`
	Contacts []Contact `json:"contacts,omitempty"`
}

type Contact struct {
	Kind  string  `json:"kind"`
	Value string  `json:"value"`
	Note  *string `json:"note,omitempty"`
	// Shared: the number also appears on other sellers' ads (portal call-centre, group switchboard). It never
	// identifies a seller, routes a message or counts as duplicate evidence.
	Shared bool `json:"shared,omitempty"`
}

type DuplicateCandidate struct {
	ID         int64     `json:"id"`
	CarA       int64     `json:"car_a"`
	CarB       int64     `json:"car_b"`
	OtherCarID int64     `json:"other_car_id,omitempty"`
	OtherTitle string    `json:"other_title,omitempty"`
	Score      float64   `json:"score"`
	Reasons    []string  `json:"reasons"`
	Status     string    `json:"status"`
	CreatedAt  time.Time `json:"created_at"`
}

type MergeInput struct {
	From   []string `json:"from"`
	Author string   `json:"author,omitempty"`
}

type SplitInput struct {
	ListingIDs   []int64 `json:"listing_ids"`
	MoveMessages bool    `json:"move_messages,omitempty"`
	MovePhotos   *bool   `json:"move_photos,omitempty"`
	Author       string  `json:"author,omitempty"`
}

type AliasInput struct {
	Alias string `json:"alias"`
}

type ActivityItem struct {
	Kind     string    `json:"kind"`
	CarID    int64     `json:"car_id"`
	CarTitle string    `json:"car_title"`
	At       time.Time `json:"at"`
	Event    *Event    `json:"event,omitempty"`
	Message  *Message  `json:"message,omitempty"`
}
