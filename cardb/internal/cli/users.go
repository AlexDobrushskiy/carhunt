package cli

import (
	"fmt"
	"io"
	"sort"

	"carhunt/cardb/internal/api"
)

// printVerdicts prints the selected user's verdict, then every other user's.
func printVerdicts(w io.Writer, sel *api.Verdict, all map[string]*api.Verdict) {
	line := func(v *api.Verdict) {
		s := fmt.Sprintf("  %s: %s %s", v.User, verdictEmoji(v), v.Value)
		if v.Note != nil && *v.Note != "" {
			s += " — " + *v.Note
		}
		fmt.Fprintf(w, "%s  (%s, %s)\n", s, v.Author, fmtTime(v.UpdatedAt))
	}
	if sel == nil {
		fmt.Fprintln(w, "  — (none yet)")
	} else {
		line(sel)
	}
	names := make([]string, 0, len(all))
	for n := range all {
		if sel == nil || n != sel.User {
			names = append(names, n)
		}
	}
	sort.Strings(names)
	for _, n := range names {
		line(all[n])
	}
}
