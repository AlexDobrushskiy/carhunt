package cli

import (
	"fmt"
	"io"
	"mime"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

// Messages, notes and events.

func normalizeDirection(d string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(d)) {
	case "in", "incoming", "received", "from", "←", "<":
		return "in", nil
	case "out", "outgoing", "sent", "to", "→", ">":
		return "out", nil
	}
	return "", usageErrorf("--dir: want in|out, got %q", d)
}

// attachmentType classifies a file by its content (WhatsApp saves JPEGs as .jfif); the extension
// is only a fallback for non-image kinds the sniffer can't name.
func attachmentType(path string) (kind, mimeType string) {
	sniffed, _ := client.SniffFile(path)
	if client.IsImage(sniffed) {
		return "image", sniffed
	}
	ext := strings.ToLower(filepath.Ext(path))
	mt := sniffed
	if mt == "" || strings.HasPrefix(mt, "application/octet-stream") || strings.HasPrefix(mt, "text/plain") {
		if byExt := mime.TypeByExtension(ext); byExt != "" {
			mt = byExt
		}
	}
	switch {
	case strings.HasPrefix(mt, "video/"):
		return "video", mt
	case strings.HasPrefix(mt, "audio/"):
		return "audio", mt
	case ext == ".pdf" || strings.HasPrefix(mt, "application/pdf") || strings.HasPrefix(mt, "text/") || strings.Contains(mt, "document"):
		return "document", mt
	}
	return "other", mt
}

func cmdMsg(e *env, args []string) error {
	if len(args) > 0 {
		switch args[0] {
		case "rm", "delete":
			return msgRm(e, args[1:])
		case "restore":
			return msgRestore(e, args[1:])
		case "dupes", "duplicates":
			return msgDupes(e, args[1:])
		}
	}
	f := newFlags(e, "msg")
	car := f.String("car", "", "car id/alias")
	lurl := f.String("url", "", "listing URL (car resolved from it)")
	to := f.String("to", "", "counterpart: seller phone/email/chat handle (car resolved if it maps to one car)")
	channel := f.String("channel", "", "whatsapp|standvirtual|olx|custojusto|email|mobile.de|autoscout24|lacentrale|leboncoin|coches.net|phone|sms|telegram|other")
	dir := f.String("dir", "", "in (from seller) | out (to seller)")
	f.StringVar(dir, "direction", "", "alias of --dir")
	at := f.String("at", "", "message time (RFC 3339 or 'YYYY-MM-DD HH:MM' local; default now)")
	sender := f.String("sender", "", "who wrote it: agent session id, 'owner', seller name/number")
	senderKind := f.String("sender-kind", "", "seller|agent|owner|system")
	externalID := f.String("external-id", "", "channel message id (idempotency key)")
	dedupeKey := f.String("dedupe-key", "", "idempotency key when there is no --external-id")
	f.StringVar(dedupeKey, "key", "", "alias of --dedupe-key")
	failed := f.Bool("failed", false, "the send attempt failed (delivery=failed)")
	errMsg := f.String("error", "", "send error text (implies --failed)")
	delivery := f.String("delivery", "", "sent|failed|received|unknown")
	textFile := f.String("text-file", "", "read the text from a file (- = stdin)")
	allowDup := f.Bool("allow-duplicate", false, "log it even if the same text is already logged within 5 min (an intentional repeat)")
	var attach multi
	f.Var(&attach, "attach", "attachment file (repeatable; images are stored as car photos and linked)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	text, err := e.textArg(pos, *textFile)
	if err != nil {
		return err
	}
	if *car == "" && *lurl == "" && *to == "" {
		return usageErrorf("msg: give --car, --url or --to")
	}
	if *channel == "" {
		return usageErrorf("msg: --channel is required (whatsapp, email, olx, …)")
	}
	if *dir == "" {
		return usageErrorf("msg: --dir in|out is required")
	}
	if text == "" && len(attach) == 0 {
		return usageErrorf("msg: TEXT is empty (pass it as an argument, --text-file F or - for stdin)")
	}
	in := api.MessageInput{Car: *car, ListingURL: *lurl, Counterpart: *to, Channel: strings.ToLower(*channel),
		Sender: *sender, Text: text, ExternalID: *externalID, DedupeKey: *dedupeKey, Delivery: *delivery, Error: *errMsg,
		AllowDuplicate: *allowDup}
	if in.Direction, err = normalizeDirection(*dir); err != nil {
		return err
	}
	if *senderKind != "" {
		if !contains([]string{"seller", "agent", "owner", "system"}, *senderKind) {
			return usageErrorf("--sender-kind: want seller|agent|owner|system")
		}
		in.SenderKind = *senderKind
	}
	if *failed || *errMsg != "" {
		if *delivery != "" && *delivery != "failed" {
			return usageErrorf("--failed/--error conflict with --delivery %s", *delivery)
		}
		in.Delivery = "failed"
	}
	if in.Delivery != "" && !contains([]string{"sent", "failed", "received", "unknown"}, in.Delivery) {
		return usageErrorf("--delivery: want sent|failed|received|unknown")
	}
	if *at != "" {
		t, err := parseTime("at", *at)
		if err != nil {
			return err
		}
		in.At = &t
	}
	for _, a := range attach {
		if _, err := os.Stat(a); err != nil {
			return usageErrorf("--attach: %v", err)
		}
	}
	cl, err := e.client()
	if err != nil {
		return err
	}

	// Store image attachments as photos first when the car is known, so the message links photo_id.
	carRef := *car
	if carRef == "" && *lurl != "" && len(attach) > 0 {
		if ls, err := cl.FindListings(e.ctx, *lurl, "", ""); err == nil && len(ls) == 1 {
			carRef = strconv.FormatInt(ls[0].CarID, 10)
		}
	}
	photoSource := "seller"
	if in.Direction == "out" {
		photoSource = "other"
	}
	deferred := map[int]string{} // attachment index → image file, uploaded once the message resolves the car
	for _, a := range attach {
		name := filepath.Base(a)
		kind, mt := attachmentType(a)
		att := api.Attachment{Kind: kind, Name: &name}
		if mt != "" {
			att.Mime = &mt
		}
		if att.Kind == "image" {
			if carRef == "" {
				deferred[len(in.Attachments)] = a
			} else {
				ph, _, err := uploadPhotoFile(e, cl, carRef, a, client.PhotoMeta{Source: photoSource, SourceRef: *externalID})
				if err != nil {
					return fmt.Errorf("attach %w", err)
				}
				att.PhotoID = &ph.ID
			}
		} else {
			e.warnf("%s: only images are stored; logged as a %s attachment by name", a, att.Kind)
		}
		in.Attachments = append(in.Attachments, att)
	}

	m, created, err := cl.AddMessage(e.ctx, in)
	if err != nil {
		return err
	}
	if len(deferred) > 0 {
		if m, err = linkDeferredPhotos(e, cl, m, in.Attachments, deferred, photoSource, *externalID); err != nil {
			return err
		}
	}
	return e.emit(map[string]any{"message": m, "created": created}, func(w io.Writer) {
		state := "logged"
		switch {
		case created:
		case m.MatchedBy == "near_duplicate":
			state = "already logged (same text within 5 min under key " + derefStr(m.DedupeKey) + "; --allow-duplicate to log a repeat)"
		default:
			state = "already logged"
		}
		if m.DeletedAt != nil {
			state += " [deleted: " + derefStr(m.DeletedReason) + "]"
		}
		fmt.Fprintf(w, "message %d %s on car %d (%s %s)\n", m.ID, state, m.CarID, m.Channel, arrow(m.Direction))
	})
}

func derefStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func msgIDs(e *env, name string, args []string, extra func(f *flags)) ([]int64, error) {
	f := newFlags(e, name)
	if extra != nil {
		extra(f)
	}
	pos, err := f.parse(args)
	if err != nil {
		return nil, err
	}
	if err := needArgs(name, pos, 1, -1, "ID…"); err != nil {
		return nil, err
	}
	var ids []int64
	for _, s := range pos {
		id, err := parseID("message id", strings.TrimPrefix(s, "#"))
		if err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, nil
}

// msgRm soft-deletes messages: they leave the chat log, the feed and the counts; the car timeline gets a
// message_deleted event; re-posting their keys returns them instead of logging them again.
func msgRm(e *env, args []string) error {
	var reason *string
	ids, err := msgIDs(e, "msg rm", args, func(f *flags) { reason = f.String("reason", "", "why (stored + shown on the timeline)") })
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var out []api.Message
	for _, id := range ids {
		m, err := cl.DeleteMessage(e.ctx, id, *reason)
		if err != nil {
			return fmt.Errorf("message %d: %w", id, err)
		}
		out = append(out, m)
	}
	return e.emit(out, func(w io.Writer) {
		for _, m := range out {
			fmt.Fprintf(w, "message %d removed from car %d (%s %s, %s)\n", m.ID, m.CarID, m.Channel, arrow(m.Direction), fmtTime(m.At))
		}
	})
}

func msgRestore(e *env, args []string) error {
	ids, err := msgIDs(e, "msg restore", args, nil)
	if err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var out []api.Message
	for _, id := range ids {
		m, err := cl.RestoreMessage(e.ctx, id)
		if err != nil {
			return fmt.Errorf("message %d: %w", id, err)
		}
		out = append(out, m)
	}
	return e.emit(out, func(w io.Writer) {
		for _, m := range out {
			fmt.Fprintf(w, "message %d restored on car %d\n", m.ID, m.CarID)
		}
	})
}

// msgDupes lists live pairs that look like one message logged twice (same rule as the server's
// near-duplicate check). Clean up with: cardb msg rm DROP_ID --reason "dup of #KEEP_ID".
func msgDupes(e *env, args []string) error {
	f := newFlags(e, "msg dupes")
	if _, err := f.parse(args); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	pairs, err := cl.MessageDuplicates(e.ctx)
	if err != nil {
		return err
	}
	return e.emit(pairs, func(w io.Writer) {
		if len(pairs) == 0 {
			fmt.Fprintln(w, "no double-logged messages")
			return
		}
		for _, p := range pairs {
			fmt.Fprintf(w, "car %d  keep #%d [%s]  drop #%d [%s]  %s %s %s  Δ%.0fs  %s\n", p.CarID, p.Keep.ID, derefStr(p.Keep.DedupeKey),
				p.Drop.ID, derefStr(p.Drop.DedupeKey), fmtTime(p.Keep.At), p.Keep.Channel, arrow(p.Keep.Direction), p.Seconds,
				excerpt60(p.Keep.Text))
		}
	})
}

func excerpt60(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	if r := []rune(s); len(r) > 60 {
		return string(r[:60]) + "…"
	}
	return s
}

// linkDeferredPhotos uploads image attachments to the car the message resolved to, then PATCHes
// the message so each attachment carries its photo_id. Uploads are idempotent by content.
func linkDeferredPhotos(e *env, cl *client.Client, m api.Message, sent []api.Attachment, deferred map[int]string, source, externalID string) (api.Message, error) {
	atts := sent
	if len(m.Attachments) == len(sent) {
		atts = append([]api.Attachment(nil), m.Attachments...) // keep what the server stored (re-log case)
	}
	ref := externalID
	if ref == "" {
		ref = fmt.Sprintf("message:%d", m.ID)
	}
	changed := false
	for i, path := range deferred {
		if atts[i].PhotoID != nil {
			continue // already linked by an earlier run
		}
		ph, _, err := uploadPhotoFile(e, cl, strconv.FormatInt(m.CarID, 10), path, client.PhotoMeta{Source: source, SourceRef: ref})
		if err != nil {
			return m, fmt.Errorf("message %d logged, but attach failed: %w", m.ID, err)
		}
		atts[i].PhotoID = &ph.ID
		changed = true
	}
	if !changed {
		return m, nil
	}
	pm, err := cl.PatchMessage(e.ctx, m.ID, api.MessagePatch{Attachments: &atts})
	if err != nil {
		return m, fmt.Errorf("message %d logged, but linking its photos failed: %w", m.ID, err)
	}
	return pm, nil
}

func arrow(dir string) string {
	if dir == "in" {
		return "←"
	}
	return "→"
}

func printMessage(w io.Writer, m api.Message) {
	who := m.Sender
	if who == "" {
		who = m.SenderKind
	}
	extra := ""
	if m.Delivery == "failed" {
		extra = " [FAILED"
		if m.Error != nil && *m.Error != "" {
			extra += ": " + *m.Error
		}
		extra += "]"
	}
	for _, a := range m.Attachments {
		label := a.Kind
		if a.Name != nil {
			label += " " + *a.Name
		}
		if a.PhotoID != nil {
			label += fmt.Sprintf(" (photo %d)", *a.PhotoID)
		}
		extra += " [" + label + "]"
	}
	prefix := fmt.Sprintf("  %s %-9s %s %s: ", fmtTime(m.At), m.Channel, arrow(m.Direction), who)
	fmt.Fprintf(w, "%s%s%s\n", prefix, indent(m.Text, strings.Repeat(" ", 6)), extra)
}

func cmdMsgs(e *env, args []string) error {
	f := newFlags(e, "msgs")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("msgs", pos, 1, 1, "CAR"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ms, err := cl.ListMessages(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return e.emit(ms, func(w io.Writer) {
		if len(ms) == 0 {
			fmt.Fprintln(w, "no messages")
		}
		for _, m := range ms {
			printMessage(w, m)
		}
	})
}

func cmdNote(e *env, args []string) error {
	f := newFlags(e, "note")
	pin := f.Bool("pin", false, "pin the note to the top")
	textFile := f.String("text-file", "", "read the text from a file (- = stdin)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) < 1 {
		return needArgs("note", pos, 2, 2, "CAR TEXT|- [--pin]")
	}
	text, err := e.textArg(pos[1:], *textFile)
	if err != nil {
		return err
	}
	if strings.TrimSpace(text) == "" {
		return usageErrorf("note: TEXT is empty")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	n, err := cl.AddNote(e.ctx, pos[0], api.NoteInput{Text: text, Pinned: *pin})
	if err != nil {
		return err
	}
	return e.emit(n, func(w io.Writer) {
		fmt.Fprintf(w, "note %d added to car %d\n", n.ID, n.CarID)
	})
}

func printNote(w io.Writer, n api.Note) {
	pin := ""
	if n.Pinned {
		pin = "📌 "
	}
	fmt.Fprintf(w, "  %s#%d %s %s: %s\n", pin, n.ID, fmtTime(n.CreatedAt), n.Author, indent(n.Text, "      "))
}

func cmdNotes(e *env, args []string) error {
	f := newFlags(e, "notes")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("notes", pos, 1, 1, "CAR"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ns, err := cl.ListNotes(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return e.emit(ns, func(w io.Writer) {
		if len(ns) == 0 {
			fmt.Fprintln(w, "no notes")
		}
		for _, n := range ns {
			printNote(w, n)
		}
	})
}

func cmdNoteEdit(e *env, args []string) error {
	f := newFlags(e, "note-edit")
	pin := f.Bool("pin", false, "pin")
	unpin := f.Bool("unpin", false, "unpin")
	textFile := f.String("text-file", "", "read the new text from a file (- = stdin)")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if len(pos) < 1 {
		return needArgs("note-edit", pos, 1, 2, "ID [TEXT] [--pin|--unpin]")
	}
	id, err := parseID("note id", pos[0])
	if err != nil {
		return err
	}
	text, err := e.textArg(pos[1:], *textFile)
	if err != nil {
		return err
	}
	var p api.NotePatch
	if text != "" {
		p.Text = &text
	}
	switch {
	case *pin && *unpin:
		return usageErrorf("--pin and --unpin are exclusive")
	case *pin, *unpin:
		v := *pin
		p.Pinned = &v
	}
	if p.Text == nil && p.Pinned == nil {
		return usageErrorf("note-edit: give new TEXT and/or --pin/--unpin")
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	n, err := cl.PatchNote(e.ctx, id, p)
	if err != nil {
		return err
	}
	return e.emit(n, func(w io.Writer) { fmt.Fprintf(w, "note %d updated\n", n.ID) })
}

func cmdNoteRm(e *env, args []string) error {
	f := newFlags(e, "note-rm")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("note-rm", pos, 1, -1, "ID…"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	var ids []int64
	for _, s := range pos {
		id, err := parseID("note id", s)
		if err != nil {
			return err
		}
		if err := cl.DeleteNote(e.ctx, id); err != nil {
			return fmt.Errorf("note %d: %w", id, err)
		}
		ids = append(ids, id)
	}
	return e.emit(map[string]any{"deleted": ids}, func(w io.Writer) { fmt.Fprintf(w, "deleted note %v\n", ids) })
}

func cmdEvent(e *env, args []string) error {
	f := newFlags(e, "event")
	typ := f.String("type", "", "event type: vin_check, report, visit, call, or custom")
	summary := f.String("summary", "", "human one-liner")
	data := f.String("data", "", "JSON object with details")
	dataFile := f.String("data-file", "", "file with the JSON details (- = stdin)")
	at := f.String("at", "", "when (RFC 3339 or 'YYYY-MM-DD HH:MM' local; default now)")
	key := f.String("key", "", "dedupe key: the same key is stored once")
	f.StringVar(key, "dedupe-key", "", "alias of --key")
	listing := f.String("listing", "", "listing id this event concerns")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("event", pos, 1, 2, "CAR --type T --summary S [--data JSON]"); err != nil {
		return err
	}
	if len(pos) == 2 && *summary == "" {
		*summary = pos[1]
	} else if len(pos) == 2 {
		return usageErrorf("event: give the summary once (positional or --summary)")
	}
	if *typ == "" || strings.TrimSpace(*summary) == "" {
		return usageErrorf("event: --type and --summary are required")
	}
	in := api.EventInput{Type: *typ, Summary: *summary, DedupeKey: *key}
	if *data != "" && *dataFile != "" {
		return usageErrorf("--data and --data-file are exclusive")
	}
	if *data != "" {
		if in.Data, err = parseJSONArg("data", *data); err != nil {
			return err
		}
	}
	if *dataFile != "" {
		b, err := e.readInput(*dataFile)
		if err != nil {
			return err
		}
		if in.Data, err = parseJSONArg("data-file", strings.TrimSpace(string(b))); err != nil {
			return err
		}
	}
	if *at != "" {
		t, err := parseTime("at", *at)
		if err != nil {
			return err
		}
		in.At = &t
	}
	if *listing != "" {
		id, err := parseID("--listing", *listing)
		if err != nil {
			return err
		}
		in.ListingID = &id
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	ev, created, err := cl.AddEvent(e.ctx, pos[0], in)
	if err != nil {
		return err
	}
	return e.emit(map[string]any{"event": ev, "created": created}, func(w io.Writer) {
		state := "added"
		if !created {
			state = "already existed"
		}
		fmt.Fprintf(w, "event %d %s on car %d (%s)\n", ev.ID, state, ev.CarID, ev.Type)
	})
}

func printEvent(w io.Writer, ev api.Event) {
	fmt.Fprintf(w, "  %s  %-15s %s", fmtTime(ev.At), ev.Type, indent(ev.Summary, "      "))
	if ev.Author != "" {
		fmt.Fprintf(w, "  (%s)", ev.Author)
	}
	fmt.Fprintln(w)
}

func cmdEvents(e *env, args []string) error {
	f := newFlags(e, "events")
	pos, err := f.parse(args)
	if err != nil {
		return err
	}
	if err := needArgs("events", pos, 1, 1, "CAR"); err != nil {
		return err
	}
	cl, err := e.client()
	if err != nil {
		return err
	}
	evs, err := cl.ListEvents(e.ctx, pos[0])
	if err != nil {
		return err
	}
	return e.emit(evs, func(w io.Writer) {
		if len(evs) == 0 {
			fmt.Fprintln(w, "no events")
		}
		for _, ev := range evs {
			printEvent(w, ev)
		}
	})
}
