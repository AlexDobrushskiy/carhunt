package store

import (
	"database/sql"
	"strings"
)

// migrations run in order; PRAGMA user_version records how many have been applied.
// Each entry is SQL (string) or a Go step (func(*sql.Tx) error).
var migrations = []any{
	`
CREATE TABLE sellers (
	id         INTEGER PRIMARY KEY,
	name       TEXT,
	type       TEXT NOT NULL DEFAULT 'unknown',
	company    TEXT,
	city       TEXT,
	note       TEXT,
	created_at REAL NOT NULL,
	updated_at REAL NOT NULL
);
CREATE TABLE seller_contacts (
	id        INTEGER PRIMARY KEY,
	seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
	kind      TEXT NOT NULL,
	value     TEXT NOT NULL,
	note      TEXT,
	UNIQUE(kind, value)
);
CREATE INDEX seller_contacts_value ON seller_contacts(value);

CREATE TABLE cars (
	id                INTEGER PRIMARY KEY,
	slug              TEXT UNIQUE COLLATE NOCASE,
	make              TEXT,
	model             TEXT,
	variant           TEXT,
	body              TEXT,
	reg_date          TEXT,
	km                INTEGER,
	battery_net_kwh   REAL,
	battery_gross_kwh REAL,
	power_kw          REAL,
	drive             TEXT,
	seats             INTEGER,
	colour            TEXT,
	interior          TEXT,
	interior_tone     TEXT,
	wheels_in         INTEGER,
	vin               TEXT,
	plate             TEXT,
	country           TEXT,
	city              TEXT,
	distance_km       INTEGER,
	seller_id         INTEGER REFERENCES sellers(id),
	summary           TEXT,
	status            TEXT NOT NULL DEFAULT 'new',
	status_reason     TEXT,
	status_changed_at REAL,
	needs_owner       INTEGER NOT NULL DEFAULT 0,
	needs_owner_reason TEXT,
	red_flags         TEXT NOT NULL DEFAULT '[]',
	open_questions    TEXT NOT NULL DEFAULT '[]',
	merged_into       INTEGER REFERENCES cars(id),
	created_at        REAL NOT NULL,
	updated_at        REAL NOT NULL
);
CREATE INDEX cars_vin ON cars(vin);
CREATE INDEX cars_merged_into ON cars(merged_into);

CREATE TABLE car_aliases (
	alias  TEXT PRIMARY KEY COLLATE NOCASE,
	car_id INTEGER NOT NULL REFERENCES cars(id)
);
CREATE INDEX car_aliases_car ON car_aliases(car_id);

CREATE TABLE listings (
	id            INTEGER PRIMARY KEY,
	car_id        INTEGER NOT NULL REFERENCES cars(id),
	url           TEXT NOT NULL,
	url_key       TEXT NOT NULL UNIQUE,
	site          TEXT NOT NULL,
	site_ref      TEXT,
	title         TEXT,
	status        TEXT NOT NULL DEFAULT 'live',
	price         INTEGER,
	price_note    TEXT,
	seller_id     INTEGER REFERENCES sellers(id),
	first_seen_at REAL NOT NULL,
	last_seen_at  REAL NOT NULL,
	removed_at    REAL,
	raw           TEXT
);
CREATE UNIQUE INDEX listings_site_ref ON listings(site, site_ref) WHERE site_ref IS NOT NULL;
CREATE INDEX listings_car ON listings(car_id);

CREATE TABLE price_points (
	id         INTEGER PRIMARY KEY,
	listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
	price      INTEGER NOT NULL,
	at         REAL NOT NULL,
	note       TEXT
);
CREATE INDEX price_points_listing ON price_points(listing_id, at);

CREATE TABLE options (
	car_id     INTEGER NOT NULL REFERENCES cars(id),
	key        TEXT NOT NULL,
	value      TEXT NOT NULL,
	source     TEXT NOT NULL,
	source_ref TEXT,
	note       TEXT,
	author     TEXT NOT NULL,
	updated_at REAL NOT NULL,
	PRIMARY KEY (car_id, key)
);

CREATE TABLE facts (
	car_id     INTEGER NOT NULL REFERENCES cars(id),
	key        TEXT NOT NULL,
	value      TEXT NOT NULL,
	source     TEXT NOT NULL,
	source_ref TEXT,
	author     TEXT NOT NULL,
	updated_at REAL NOT NULL,
	PRIMARY KEY (car_id, key)
);

CREATE TABLE photos (
	id         INTEGER PRIMARY KEY,
	car_id     INTEGER NOT NULL REFERENCES cars(id),
	listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
	sha256     TEXT NOT NULL,
	phash      INTEGER NOT NULL,
	width      INTEGER NOT NULL,
	height     INTEGER NOT NULL,
	position   INTEGER NOT NULL,
	cover      INTEGER NOT NULL DEFAULT 0,
	caption    TEXT,
	source     TEXT NOT NULL,
	source_ref TEXT,
	created_at REAL NOT NULL,
	UNIQUE(car_id, sha256)
);

CREATE TABLE events (
	id         INTEGER PRIMARY KEY,
	car_id     INTEGER NOT NULL REFERENCES cars(id),
	listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
	type       TEXT NOT NULL,
	at         REAL NOT NULL,
	author     TEXT NOT NULL,
	summary    TEXT NOT NULL,
	data       TEXT,
	dedupe_key TEXT UNIQUE
);
CREATE INDEX events_car ON events(car_id, at);
CREATE INDEX events_at ON events(at);

CREATE TABLE messages (
	id          INTEGER PRIMARY KEY,
	car_id      INTEGER NOT NULL REFERENCES cars(id),
	seller_id   INTEGER REFERENCES sellers(id),
	channel     TEXT NOT NULL,
	direction   TEXT NOT NULL,
	at          REAL NOT NULL,
	sender_kind TEXT NOT NULL,
	sender      TEXT NOT NULL,
	counterpart TEXT,
	text        TEXT NOT NULL,
	attachments TEXT NOT NULL DEFAULT '[]',
	delivery    TEXT NOT NULL,
	error       TEXT,
	external_id TEXT,
	dedupe_key  TEXT NOT NULL UNIQUE,
	author      TEXT NOT NULL,
	UNIQUE(channel, external_id)
);
CREATE INDEX messages_car ON messages(car_id, at);
CREATE INDEX messages_counterpart ON messages(counterpart);
CREATE INDEX messages_at ON messages(at);

CREATE TABLE notes (
	id          INTEGER PRIMARY KEY,
	car_id      INTEGER NOT NULL REFERENCES cars(id),
	author      TEXT NOT NULL,
	author_kind TEXT NOT NULL,
	text        TEXT NOT NULL,
	pinned      INTEGER NOT NULL DEFAULT 0,
	created_at  REAL NOT NULL,
	updated_at  REAL NOT NULL
);
CREATE INDEX notes_car ON notes(car_id);

CREATE TABLE verdicts (
	car_id     INTEGER PRIMARY KEY REFERENCES cars(id),
	value      TEXT NOT NULL,
	note       TEXT,
	author     TEXT NOT NULL,
	updated_at REAL NOT NULL
);

CREATE TABLE duplicates (
	id         INTEGER PRIMARY KEY,
	car_a      INTEGER NOT NULL REFERENCES cars(id),
	car_b      INTEGER NOT NULL REFERENCES cars(id),
	score      REAL NOT NULL,
	reasons    TEXT NOT NULL DEFAULT '[]',
	status     TEXT NOT NULL DEFAULT 'proposed',
	created_at REAL NOT NULL,
	updated_at REAL NOT NULL,
	CHECK (car_a < car_b),
	UNIQUE(car_a, car_b)
);
`,
	// Soft delete for messages: the row keeps its dedupe_key/external_id so re-posts can't resurrect it.
	`
ALTER TABLE messages ADD COLUMN deleted_at REAL;
ALTER TABLE messages ADD COLUMN deleted_by TEXT;
ALTER TABLE messages ADD COLUMN deleted_reason TEXT;
`,
	// Shared contacts: a number on several unrelated sellers' ads (portal call-centre) is stored on each of them with
	// shared = 1 and never identifies a seller. Own contacts (shared = 0) stay unique per kind+value.
	`
CREATE TABLE seller_contacts_v3 (
	id        INTEGER PRIMARY KEY,
	seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
	kind      TEXT NOT NULL,
	value     TEXT NOT NULL,
	note      TEXT,
	shared    INTEGER NOT NULL DEFAULT 0,
	UNIQUE(seller_id, kind, value)
);
INSERT INTO seller_contacts_v3 (id, seller_id, kind, value, note) SELECT id, seller_id, kind, value, note FROM seller_contacts;
DROP TABLE seller_contacts;
ALTER TABLE seller_contacts_v3 RENAME TO seller_contacts;
CREATE INDEX seller_contacts_value ON seller_contacts(value);
CREATE UNIQUE INDEX seller_contacts_own ON seller_contacts(kind, value) WHERE shared = 0;
`,
	// Good-deal flag and the manual model family override (NULL = derived from make/model/variant at read time).
	`
ALTER TABLE cars ADD COLUMN model_family_override TEXT;
ALTER TABLE cars ADD COLUMN good_deal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cars ADD COLUMN good_deal_note TEXT;
ALTER TABLE cars ADD COLUMN good_deal_by TEXT;
ALTER TABLE cars ADD COLUMN good_deal_at REAL;
`,
	// carhunt renames for a database created by the EV-era schema (fresh databases already have the new names).
	renameLegacyColumns,
	migPowertrain, // 6: schema_powertrain.go
	migUsers,      // 7: schema_users.go
	migProfile,    // 8: schema_profile.go
}

// renameLegacyColumns: needs_<person> → needs_owner(_reason), km_to_<home city> → distance_km.
func renameLegacyColumns(tx *sql.Tx) error {
	rows, err := tx.Query("SELECT name FROM pragma_table_info('cars')")
	if err != nil {
		return err
	}
	var cols []string
	for rows.Next() {
		var c string
		if err := rows.Scan(&c); err != nil {
			rows.Close()
			return err
		}
		cols = append(cols, c)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, c := range cols {
		var to string
		switch {
		case strings.HasPrefix(c, "needs_") && strings.HasSuffix(c, "_reason") && c != "needs_owner_reason":
			to = "needs_owner_reason"
		case strings.HasPrefix(c, "needs_") && !strings.HasSuffix(c, "_reason") && c != "needs_owner":
			to = "needs_owner"
		case strings.HasPrefix(c, "km_to_"):
			to = "distance_km"
		default:
			continue
		}
		if _, err := tx.Exec(`ALTER TABLE cars RENAME COLUMN "` + c + `" TO ` + to); err != nil {
			return err
		}
	}
	return nil
}
