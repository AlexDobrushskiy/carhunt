package api

import "strings"

// VerdictOf returns user's verdict on the car (case-insensitive name), nil when that user has not rated it.
func (c *CarSummary) VerdictOf(user string) *Verdict {
	for name, v := range c.Verdicts {
		if strings.EqualFold(name, user) {
			return v
		}
	}
	return nil
}
