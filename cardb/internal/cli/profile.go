package cli

import (
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
)

func cmdProfile(e *env, args []string) error {
	f := newFlags(e, "profile")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) > 0 {
		return usageErrorf("usage: cardb profile [--json]")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	p, err := cl.Profile(e.ctx)
	if err != nil {
		return err
	}
	return e.emit(p, func(w io.Writer) { printProfile(w, p) })
}

func printProfile(w io.Writer, p api.Profile) {
	h := p.Owner.Home
	home := strings.TrimSpace(h.City + " " + h.Country)
	if home == "" {
		home = "(not set: no market/distance/landed cost)"
	}
	fmt.Fprintf(w, "owner: %s · home %s\n", p.Owner.Name, home)
	var users []string
	for _, u := range p.Users {
		users = append(users, u.Name+" ("+u.Role+")")
	}
	fmt.Fprintf(w, "users: %s\n", strings.Join(users, ", "))
	if len(p.Countries) > 0 {
		fmt.Fprintf(w, "countries: %s\n", strings.Join(p.Countries, " "))
	}
	fmt.Fprintf(w, "\ntiers (queue default %s):\n", joinTiers(p.QueueDefaultTiers))
	for _, t := range p.Tiers {
		fmt.Fprintf(w, "  T%d %s\n", t.Tier, t.Label)
		for _, r := range t.Rules {
			fmt.Fprintf(w, "     - %s\n", r)
		}
	}
	fmt.Fprintln(w, "\nhard filters:")
	for _, l := range p.HardFilters {
		fmt.Fprintf(w, "  - %s\n", l)
	}
	if len(p.OptionsWanted) > 0 {
		keys := make([]string, 0, len(p.OptionsWanted))
		for k := range p.OptionsWanted {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool {
			if p.OptionsWanted[keys[i]] != p.OptionsWanted[keys[j]] {
				return p.OptionsWanted[keys[i]] > p.OptionsWanted[keys[j]]
			}
			return keys[i] < keys[j]
		})
		var parts []string
		for _, k := range keys {
			parts = append(parts, k+" "+strconv.FormatFloat(p.OptionsWanted[k], 'f', -1, 64))
		}
		fmt.Fprintf(w, "\noptions wanted: %s\n", strings.Join(parts, ", "))
	}
	if len(p.MustHave) > 0 {
		fmt.Fprintf(w, "must have: %s\n", strings.Join(p.MustHave, ", "))
	}
	fmt.Fprintf(w, "weights: value %g · fit %g · risk %g\n", p.Weights["value"], p.Weights["fit"], p.Weights["risk"])
	for _, warn := range p.Warnings {
		fmt.Fprintf(w, "warning: %s\n", warn)
	}
}

func joinTiers(ts []int) string {
	parts := make([]string, len(ts))
	for i, t := range ts {
		parts[i] = strconv.Itoa(t)
	}
	return strings.Join(parts, ",")
}
