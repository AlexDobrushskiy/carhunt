package store

import (
	"slices"
	"strings"

	"encoding/json"
)

// listOpSets applies PATCH `red_flags_add/_remove` and `open_questions_add/_remove` to the car's current lists
// (read in the same transaction, so concurrent writers never drop each other's items). Items match by exact text
// after trimming; adding an existing item and removing a missing one are no-ops. Removals run before additions.
// Returns the SET clauses for the lists that changed.
func listOpSets(car *carRow, patch map[string]json.RawMessage) ([]string, []any, error) {
	var sets []string
	var args []any
	for _, list := range []string{"red_flags", "open_questions"} {
		addRaw, hasAdd := patch[list+"_add"]
		rmRaw, hasRm := patch[list+"_remove"]
		if !hasAdd && !hasRm {
			continue
		}
		if _, replace := patch[list]; replace {
			return nil, nil, invalidf("%s replaces the whole list; don't combine it with %s_add / %s_remove", list, list, list)
		}
		cur := car.RedFlags
		if list == "open_questions" {
			cur = car.OpenQuestions
		}
		next := slices.Clone(cur)
		if hasRm {
			rm, err := decodeStrList(list+"_remove", rmRaw)
			if err != nil {
				return nil, nil, err
			}
			for _, r := range rm {
				r = strings.TrimSpace(r)
				next = slices.DeleteFunc(next, func(x string) bool { return strings.TrimSpace(x) == r })
			}
		}
		if hasAdd {
			add, err := decodeStrList(list+"_add", addRaw)
			if err != nil {
				return nil, nil, err
			}
			for _, a := range add {
				a = strings.TrimSpace(a)
				if a == "" {
					return nil, nil, invalidf("%s_add: items must not be empty", list)
				}
				if !slices.ContainsFunc(next, func(x string) bool { return strings.TrimSpace(x) == a }) {
					next = append(next, a)
				}
			}
		}
		if slices.Equal(next, cur) {
			continue
		}
		sets = append(sets, list+" = ?")
		args = append(args, jsonList(next))
	}
	return sets, args, nil
}
