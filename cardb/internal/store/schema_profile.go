package store

// migProfile: car location (lat/lon) for the distance estimate from owner.home.
const migProfile = `
ALTER TABLE cars ADD COLUMN lat REAL;
ALTER TABLE cars ADD COLUMN lon REAL;
`
