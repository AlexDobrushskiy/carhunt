package store

import (
	"database/sql"
	"time"
)

// migUsers: users + per-user verdicts. The owner is the one row with role 'owner' (named 'owner' until SetProfile
// renames it), so the owner's verdicts survive a change of owner.name. Existing single verdicts become the owner's.
func migUsers(tx *sql.Tx) error {
	now := ts(time.Now())
	if _, err := tx.Exec(`
CREATE TABLE users (
	id         INTEGER PRIMARY KEY,
	name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
	role       TEXT NOT NULL,
	active     INTEGER NOT NULL DEFAULT 1,
	created_at REAL NOT NULL,
	updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX users_one_owner ON users(role) WHERE role = 'owner';`); err != nil {
		return err
	}
	if _, err := tx.Exec("INSERT INTO users (id, name, role, created_at, updated_at) VALUES (1, 'owner', 'owner', ?, ?)", now, now); err != nil {
		return err
	}
	_, err := tx.Exec(`
CREATE TABLE verdicts_v7 (
	car_id     INTEGER NOT NULL REFERENCES cars(id),
	user_id    INTEGER NOT NULL REFERENCES users(id),
	value      TEXT NOT NULL,
	note       TEXT,
	author     TEXT NOT NULL,
	updated_at REAL NOT NULL,
	PRIMARY KEY (car_id, user_id)
);
INSERT INTO verdicts_v7 (car_id, user_id, value, note, author, updated_at)
	SELECT car_id, 1, value, note, author, updated_at FROM verdicts;
DROP TABLE verdicts;
ALTER TABLE verdicts_v7 RENAME TO verdicts;
CREATE INDEX verdicts_user ON verdicts(user_id);
`)
	return err
}
