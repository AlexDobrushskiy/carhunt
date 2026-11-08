package cli

import (
	"fmt"
	"io"
	"sort"
	"strings"

	"carhunt/cardb/internal/api"
)

// Commands that change one car: set, status, needs-owner, verdict, opt, fact, alias.

func cmdStatus(e *env, args []string) error {
	f := newFlags(e, "status")
	reason := f.String("reason", "", "why (stored as status_reason + on the status_change event)")
	ifVersion := f.String("if-version", "", "only if the car is still at this version (from show/--json); else exit 1 with a conflict")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("status", pos, 2, 2, "CAR STATUS [--reason R] [--if-version N]"); err != nil {
		return err
	}
	st, err := normalizeStatus(pos[1])
	if err != nil {
		return err
	}
	in := api.StatusInput{Status: st, Reason: *reason}
	if in.Version, err = parseIfVersion(f, *ifVersion); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.SetStatus(e.ctx, pos[0], in)
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) {
		fmt.Fprintf(w, "car %d %s: status %s", car.ID, car.Title, car.Status)
		if car.StatusReason != nil && *car.StatusReason != "" {
			fmt.Fprintf(w, " (%s)", *car.StatusReason)
		}
		fmt.Fprintln(w)
	})
}

func cmdNeedsOwner(e *env, args []string) error {
	f := newFlags(e, "needs-owner")
	clear := f.Bool("clear", false, "remove the flag")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	var patch map[string]any
	if *clear {
		if err := needArgs("needs-owner", pos, 1, 1, "CAR --clear"); err != nil {
			return err
		}
		patch = map[string]any{"needs_owner": false, "needs_owner_reason": nil}
	} else {
		if err := needArgs("needs-owner", pos, 2, 2, "CAR REASON"); err != nil {
			return err
		}
		if strings.TrimSpace(pos[1]) == "" {
			return usageErrorf("needs-owner: REASON must not be empty")
		}
		patch = map[string]any{"needs_owner": true, "needs_owner_reason": pos[1]}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.PatchCar(e.ctx, pos[0], patch)
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) {
		if car.NeedsOwner {
			fmt.Fprintf(w, "car %d %s: needs owner — %s\n", car.ID, car.Title, deref(car.NeedsOwnerReason))
		} else {
			fmt.Fprintf(w, "car %d %s: needs-owner flag cleared\n", car.ID, car.Title)
		}
	})
}

func cmdVerdict(e *env, args []string) error {
	f := newFlags(e, "verdict")
	note := f.String("note", "", "why")
	clear := f.Bool("clear", false, "remove the verdict")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	var val string
	if *clear {
		if err := needArgs("verdict", pos, 1, 1, "CAR --clear"); err != nil {
			return err
		}
	} else {
		if err := needArgs("verdict", pos, 2, 2, "CAR up|maybe|down|clear [--note N]"); err != nil {
			return err
		}
		if val, err = normalizeVerdict(pos[1]); err != nil {
			return err
		}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	if val == "" {
		if err := cl.DeleteVerdict(e.ctx, pos[0]); err != nil {
			return err
		}
		return e.emit(map[string]any{"car": pos[0], "verdict": nil}, func(w io.Writer) {
			fmt.Fprintf(w, "car %s: verdict cleared\n", pos[0])
		})
	}
	v, err := cl.PutVerdict(e.ctx, pos[0], api.VerdictInput{Value: val, Note: *note})
	if err != nil {
		return err
	}
	return e.emit(v, func(w io.Writer) {
		fmt.Fprintf(w, "car %s: verdict %s %s", pos[0], verdictEmoji(&v), v.Value)
		if v.Note != nil && *v.Note != "" {
			fmt.Fprintf(w, " — %s", *v.Note)
		}
		fmt.Fprintln(w)
	})
}

func cmdDeal(e *env, args []string) error {
	f := newFlags(e, "deal")
	note := f.String("note", "", "why it is a good deal (one line, max 300 chars; \"\" clears; omitted keeps the current note)")
	at := f.String("at", "", "when (RFC 3339 or 'YYYY-MM-DD HH:MM' local; default now)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("deal", pos, 2, 2, "CAR on|off [--note N]"); err != nil {
		return err
	}
	on, err := normalizeOnOff(pos[1])
	if err != nil {
		return err
	}
	in := api.GoodDealInput{GoodDeal: &on}
	if f.isSet("note") {
		in.Note = note
	}
	if *at != "" {
		t, err := parseTime("at", *at)
		if err != nil {
			return err
		}
		in.At = &t
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	gd, err := cl.PutGoodDeal(e.ctx, pos[0], in)
	if err != nil {
		return err
	}
	return e.emit(gd, func(w io.Writer) { fmt.Fprintf(w, "car %s: %s\n", pos[0], fmtGoodDeal(gd)) })
}

// fmtGoodDeal: "★ good deal — note (by, at)" or "not a good deal".
func fmtGoodDeal(gd api.GoodDeal) string {
	if !gd.GoodDeal {
		return "not a good deal"
	}
	s := "★ good deal"
	if gd.Note != nil && *gd.Note != "" {
		s += " — " + *gd.Note
	}
	if gd.By != nil && gd.At != nil {
		s += fmt.Sprintf(" (%s, %s)", *gd.By, fmtTime(*gd.At))
	}
	return s
}

func cmdOpt(e *env, args []string) error  { return evidenceCmd(e, "opt", args) }
func cmdFact(e *env, args []string) error { return evidenceCmd(e, "fact", args) }

func evidenceCmd(e *env, kind string, args []string) error {
	f := newFlags(e, kind)
	source := f.String("source", "", "evidence source for args without one: "+strings.Join(api.EvidenceSources, " "))
	note := f.String("note", "", "note stored with each option")
	var rm multi
	f.Var(&rm, "rm", "remove KEY (repeatable)")
	if kind == "fact" {
		f.Lookup("note").Usage = "(options only)"
	}
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	syn := "CAR key=value[:source[:ref]]… [--source S] [--rm KEY]"
	if len(pos) < 1 || (len(pos) < 2 && len(rm) == 0) {
		return needArgs(kind, nil, 2, -1, syn)
	}
	car := pos[0]
	var evs []evidenceArg
	for _, a := range pos[1:] {
		var ev evidenceArg
		if kind == "opt" {
			ev, err = parseOptionArg(e, a, *source)
		} else {
			ev, err = parseEvidence(a, *source)
			if err == nil && ev.Value == "" {
				err = usageErrorf("%q: empty fact value (use --rm %s to delete)", a, ev.Key)
			}
		}
		if err != nil {
			return err
		}
		evs = append(evs, ev)
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var results []any
	var lines []string
	for _, ev := range evs {
		if kind == "opt" {
			o, err := cl.PutOption(e.ctx, car, ev.Key, api.OptionInput{Value: ev.Value, Source: ev.Source, SourceRef: ev.Ref, Note: *note})
			if err != nil {
				return fmt.Errorf("%s: %w", ev.Key, err)
			}
			results = append(results, o)
			lines = append(lines, fmt.Sprintf("%s %s = %s %s", optionMark(o.Value), o.Key, o.Value, evidenceSuffix(o.Source, o.SourceRef)))
		} else {
			fa, err := cl.PutFact(e.ctx, car, ev.Key, api.FactInput{Value: ev.Value, Source: ev.Source, SourceRef: ev.Ref})
			if err != nil {
				return fmt.Errorf("%s: %w", ev.Key, err)
			}
			results = append(results, fa)
			lines = append(lines, fmt.Sprintf("%s: %s %s", fa.Key, fa.Value, evidenceSuffix(fa.Source, fa.SourceRef)))
		}
	}
	var removed []string
	for _, k := range splitList(rm) {
		k = normalizeKey(k)
		if kind == "opt" {
			err = cl.DeleteOption(e.ctx, car, k)
		} else {
			err = cl.DeleteFact(e.ctx, car, k)
		}
		if err != nil {
			return fmt.Errorf("remove %s: %w", k, err)
		}
		removed = append(removed, k)
		lines = append(lines, "removed "+k)
	}
	return e.emit(map[string]any{"car": car, "set": results, "removed": removed}, func(w io.Writer) {
		for _, l := range lines {
			fmt.Fprintln(w, strings.TrimSpace(l))
		}
	})
}

func evidenceSuffix(source string, ref *string) string {
	s := ""
	if source != "" {
		s = "(" + source
		if ref != nil && *ref != "" {
			s += ": " + *ref
		}
		s += ")"
	}
	return s
}

func cmdAlias(e *env, args []string) error {
	f := newFlags(e, "alias")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("alias", pos, 2, -1, "CAR ALIAS…"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	for _, a := range pos[1:] {
		if err := cl.AddAlias(e.ctx, pos[0], a); err != nil {
			return fmt.Errorf("alias %s: %w", a, err)
		}
	}
	return e.emit(map[string]any{"car": pos[0], "added": pos[1:]}, func(w io.Writer) {
		fmt.Fprintf(w, "car %s: added alias %s\n", pos[0], strings.Join(pos[1:], ", "))
	})
}

// clearable maps --clear names (flag or JSON key) to the JSON key PATCH nulls.
func clearKey(name string) (string, bool) {
	n := strings.TrimPrefix(strings.TrimSpace(name), "--")
	for _, sf := range specFields {
		if n == sf.flag || n == sf.key || n == strings.TrimPrefix(sf.key, "powertrain.") || contains(sf.aliases, n) {
			return sf.key, true
		}
	}
	k := normalizeKey(n)
	switch k {
	case "slug", "summary", "status_reason", "needs_owner_reason", "red_flags", "open_questions", "seller", "seller_id", "model_family",
		"powertrain":
		return k, true
	case "family":
		return "model_family", true
	}
	if sub, ok := strings.CutPrefix(k, "powertrain."); ok {
		return clearKey(sub)
	}
	return "", false
}

func cmdSet(e *env, args []string) error {
	f := newFlags(e, "set")
	specs := addSpecFlags(f)
	seller := addSellerFlags(f)
	slug := f.String("slug", "", "stable human id")
	summary := f.String("summary", "", "one-line why interesting / watch-outs")
	status := f.String("status", "", "status (prefer `cardb status`)")
	statusReason := f.String("status-reason", "", "status reason")
	sellerID := f.String("seller-id", "", "re-point the car to an existing seller id")
	family := f.String("family", "", "manual model family, e.g. \"Audi Q4\" (cardb families --known); --clear model_family = auto")
	ifVersion := f.String("if-version", "", "only if the car is still at this version (from show/--json); else exit 1 with a conflict")
	var redFlags, questions, clears, rfAdd, rfRm, qAdd, qRm multi
	f.Var(&redFlags, "red-flag", "red flag (repeatable; replaces the list — prefer --red-flag-add)")
	f.Var(&questions, "question", "open question (repeatable; replaces the list — prefer --question-add)")
	f.Var(&rfAdd, "red-flag-add", "add a red flag, exact text (repeatable; safe with other writers)")
	f.Var(&rfRm, "red-flag-rm", "remove a red flag by exact text (repeatable)")
	f.Var(&qAdd, "question-add", "add an open question (repeatable)")
	f.Var(&qRm, "question-rm", "remove an open question by exact text (repeatable)")
	f.Var(&clears, "clear", "set FIELD to null (repeatable; flag name or JSON key, e.g. km, reg, vin, summary, engine-cc, powertrain.gearbox)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("set", pos, 1, 1, "CAR [--km N …] [--clear FIELD]"); err != nil {
		return err
	}
	patch, err := specs.collect(f)
	if err != nil {
		return err
	}
	str := func(flag, key string, v *string) {
		if f.isSet(flag) {
			patch[key] = *v
		}
	}
	str("slug", "slug", slug)
	str("summary", "summary", summary)
	str("status-reason", "status_reason", statusReason)
	str("family", "model_family", family)
	if f.isSet("status") {
		st, err := normalizeStatus(*status)
		if err != nil {
			return err
		}
		patch["status"] = st
	}
	if f.isSet("seller-id") {
		id, err := parseID("--seller-id", *sellerID)
		if err != nil {
			return err
		}
		patch["seller_id"] = id
	}
	if len(redFlags) > 0 {
		patch["red_flags"] = []string(redFlags)
	}
	if len(questions) > 0 {
		patch["open_questions"] = []string(questions)
	}
	for key, vals := range map[string]multi{"red_flags_add": rfAdd, "red_flags_remove": rfRm, "open_questions_add": qAdd, "open_questions_remove": qRm} {
		if len(vals) > 0 {
			patch[key] = []string(vals)
		}
	}
	if (len(redFlags) > 0 && len(rfAdd)+len(rfRm) > 0) || (len(questions) > 0 && len(qAdd)+len(qRm) > 0) {
		return usageErrorf("set: --red-flag/--question replace the whole list; don't combine them with the -add/-rm flags")
	}
	si, err := seller.build(f)
	if err != nil {
		return err
	}
	if si != nil {
		patch["seller"] = si
	}
	for _, c := range splitList(clears) {
		k, ok := clearKey(c)
		if !ok {
			return usageErrorf("--clear: unknown field %q", c)
		}
		if hasPath(patch, k) {
			return usageErrorf("--clear %s conflicts with a value for the same field", c)
		}
		putPath(patch, k, nil)
	}
	if len(patch) == 0 {
		return usageErrorf("set: nothing to change (give at least one field flag; see `cardb help set`)")
	}
	v, err := parseIfVersion(f, *ifVersion)
	if err != nil {
		return err
	}
	if v != nil {
		patch["version"] = *v
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	car, err := cl.PatchCar(e.ctx, pos[0], patch)
	if err != nil {
		return err
	}
	return e.emit(car, func(w io.Writer) {
		keys := make([]string, 0, len(patch))
		for k := range patch {
			if k != "version" {
				keys = append(keys, k)
			}
		}
		sort.Strings(keys)
		fmt.Fprintf(w, "car %d %s: updated %s\n", car.ID, car.Title, strings.Join(keys, ", "))
		if fmt.Sprint(car.ID) != pos[0] && isNumeric(pos[0]) {
			fmt.Fprintf(w, "note: car %s was merged into car %d\n", pos[0], car.ID)
		}
	})
}
