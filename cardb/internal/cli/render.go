package cli

import (
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
	"unicode"

	"carhunt/cardb/internal/api"
)

func groupThousands(n int) string {
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.Itoa(n)
	var b strings.Builder
	for i, r := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(' ')
		}
		b.WriteRune(r)
	}
	if neg {
		return "-" + b.String()
	}
	return b.String()
}

func fmtPrice(p *int) string {
	if p == nil {
		return "—"
	}
	return groupThousands(*p) + " €"
}

func fmtKm(k *int) string {
	if k == nil {
		return "—"
	}
	return groupThousands(*k) + " km"
}

func fmtFloat(x float64) string { return strconv.FormatFloat(x, 'f', -1, 64) }

func fmtTime(t time.Time) string {
	if t.IsZero() {
		return "—"
	}
	return t.Local().Format("2006-01-02 15:04")
}

func fmtTimePtr(t *time.Time) string {
	if t == nil {
		return "—"
	}
	return fmtTime(*t)
}

func fmtDate(t time.Time) string {
	if t.IsZero() {
		return "—"
	}
	return t.Local().Format("2006-01-02")
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func verdictEmoji(v *api.Verdict) string {
	if v == nil {
		return ""
	}
	switch v.Value {
	case "up":
		return "👍"
	case "maybe":
		return "🤔"
	case "down":
		return "👎"
	}
	return v.Value
}

func optionMark(v string) string {
	switch v {
	case "yes":
		return "✓"
	case "no":
		return "✗"
	}
	return "?"
}

// dispWidth approximates terminal column width (emoji and CJK are 2 wide, marks 0).
func dispWidth(s string) int {
	w := 0
	for _, r := range s {
		switch {
		case r == 0xFE0F || r == 0x200D || unicode.Is(unicode.Mn, r):
		case r >= 0x1F000 && r <= 0x1FAFF, r >= 0x1100 && r <= 0x115F, r >= 0x2E80 && r <= 0xA4CF,
			r >= 0xAC00 && r <= 0xD7A3, r >= 0xF900 && r <= 0xFAFF, r >= 0xFF00 && r <= 0xFF60, r == 0x3000:
			w += 2
		default:
			w++
		}
	}
	return w
}

func truncate(s string, max int) string {
	if dispWidth(s) <= max {
		return s
	}
	var b strings.Builder
	w := 0
	for _, r := range s {
		rw := dispWidth(string(r))
		if w+rw > max-1 {
			break
		}
		b.WriteRune(r)
		w += rw
	}
	return b.String() + "…"
}

// table renders rows with padded columns; rightAlign marks numeric columns.
type table struct {
	header     []string
	rows       [][]string
	rightAlign map[int]bool
}

func (t *table) add(cells ...string) { t.rows = append(t.rows, cells) }

func (t *table) render(w io.Writer) {
	widths := make([]int, len(t.header))
	all := append([][]string{t.header}, t.rows...)
	for _, r := range all {
		for i, c := range r {
			if i < len(widths) && dispWidth(c) > widths[i] {
				widths[i] = dispWidth(c)
			}
		}
	}
	for _, r := range all {
		var b strings.Builder
		for i, c := range r {
			if i >= len(widths) {
				break
			}
			pad := strings.Repeat(" ", widths[i]-dispWidth(c))
			last := i == len(r)-1
			switch {
			case t.rightAlign[i]:
				b.WriteString(pad + c)
			case last:
				b.WriteString(c)
			default:
				b.WriteString(c + pad)
			}
			if !last {
				b.WriteString("  ")
			}
		}
		fmt.Fprintln(w, strings.TrimRight(b.String(), " "))
	}
}

// indent prefixes continuation lines of multi-line text.
func indent(s, prefix string) string {
	return strings.ReplaceAll(strings.TrimRight(s, "\n"), "\n", "\n"+prefix)
}

func plural(n int, one, many string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, one)
	}
	return fmt.Sprintf("%d %s", n, many)
}

func firstLine(s string) string {
	s, _, _ = strings.Cut(s, "\n")
	return s
}

func isNumeric(s string) bool {
	_, err := strconv.ParseInt(s, 10, 64)
	return err == nil
}
