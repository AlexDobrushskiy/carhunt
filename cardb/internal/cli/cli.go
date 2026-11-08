// Package cli implements the cardb client subcommands. Run is the testable entrypoint;
// server-side subcommands (serve, backup, healthcheck, import) are dispatched in cmd/cardb.
package cli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"carhunt/cardb/internal/api"
	"carhunt/cardb/internal/client"
)

// Exit codes.
const (
	ExitOK       = 0
	ExitError    = 1 // API, network or runtime error
	ExitUsage    = 2 // bad flags/arguments
	ExitNotFound = 3 // car/listing/note/photo not found (HTTP 404), or find-listing with no match
)

type env struct {
	ctx    context.Context
	stdout io.Writer
	stderr io.Writer
	stdin  io.Reader

	json     bool
	override client.Config
	cl       *client.Client
}

// client builds the API client lazily so that flags parsed after the subcommand still apply.
func (e *env) client() (*client.Client, error) {
	if e.cl != nil {
		return e.cl, nil
	}
	cl, err := client.FromEnv(e.override)
	if err != nil {
		return nil, err
	}
	if cl.BaseURL == "" {
		return nil, errors.New("no server configured: set CARDB_URL and CARDB_TOKEN, pass --server/--token, or run `cardb config set --url URL --token TOKEN`")
	}
	e.cl = cl
	return cl, nil
}

type command struct {
	name    string
	args    string // positional synopsis
	summary string
	run     func(e *env, args []string) error
}

var commands []command

func init() {
	commands = []command{
		{"upsert", "--url URL [fields…] | --from-json FILE|-", "create/update a listing by URL (idempotent); prints car + listing ids and duplicate candidates", cmdUpsert},
		{"show", "CAR", "full card: specs, seller, listings + price history, options, facts, verdict, notes, timeline, chat", cmdShow},
		{"ls", "[filters]", "list/filter cars (table; --json raw)", cmdLs},
		{"queue", "[--tier 1,2] [--tier 3] [--spec confirmed|unknown] [--limit N] [--offset N]", "\"To rate\" queue: unrated cars passing the hard filters, by tier / deal / trim / price gap", cmdQueue},
		{"set", "CAR [--km N --fuel F …] [--red-flag-add T] [--clear FIELD] [--if-version N]", "update car fields (only given fields change)", cmdSet},
		{"status", "CAR STATUS [--reason R] [--if-version N]", "set status: " + strings.Join(statusList(), " "), cmdStatus},
		{"needs-owner", "CAR REASON | CAR --clear", "flag/unflag a car for the owner's attention", cmdNeedsOwner},
		{"verdict", "CAR up|maybe|down|clear [--note N]", "the owner's verdict (also 👍 🤔 👎, like/dislike)", cmdVerdict},
		{"deal", "CAR on|off [--note N] [--at T]", "flag/unflag a good deal (also yes/no, true/false, ✓/✗); --note \"\" clears the note", cmdDeal},
		{"opt", "CAR key=value[:source[:ref]]… [--rm KEY]", "set equipment options with evidence", cmdOpt},
		{"fact", "CAR key=value[:source[:ref]]… [--rm KEY]", "set free-form facts with evidence", cmdFact},
		{"alias", "CAR ALIAS…", "add aliases (stable human ids)", cmdAlias},
		{"msg", "--car CAR|--url LISTING_URL|--to CONTACT --channel CH --dir in|out TEXT|--text-file F|- · msg rm ID… [--reason R] · msg restore ID… · msg dupes", "log a chat message (idempotent, near duplicates return the existing row); remove/restore one; list double-logged pairs", cmdMsg},
		{"msgs", "CAR", "print a car's chat log", cmdMsgs},
		{"note", "CAR TEXT|- [--pin]", "add a note", cmdNote},
		{"notes", "CAR", "list notes", cmdNotes},
		{"note-edit", "ID [TEXT] [--pin|--unpin]", "edit a note", cmdNoteEdit},
		{"note-rm", "ID", "delete a note", cmdNoteRm},
		{"event", "CAR --type T --summary S [--data JSON] [--at T] [--key K]", "add a timeline event (idempotent on --key)", cmdEvent},
		{"events", "CAR", "print a car's timeline", cmdEvents},
		{"photo", "add|get|ls|edit|rm …", "photos: upload/fetch/list/edit/delete", cmdPhoto},
		{"listing", "show|set ID …", "one listing: show, or change status/price", cmdListing},
		{"seller", "show|set ID …", "one seller: show, or edit name/type/contacts", cmdSeller},
		{"find-listing", "URL", "find a listing by URL (exit 3 if none)", cmdFindListing},
		{"dupes", "[--car CAR] [--status S]", "duplicate proposals", cmdDupes},
		{"dupe-reject", "ID…", "mark proposals as not the same car", cmdDupeReject},
		{"rm", "CAR --yes", "permanently delete a car and everything on it (without --yes: show what would go, exit 2)", cmdRm},
		{"merge", "TARGET SOURCE…", "merge SOURCE cars into TARGET", cmdMerge},
		{"split", "CAR --listing ID… [--move-messages] [--keep-photos]", "move listings out to a new car", cmdSplit},
		{"families", "[--known]", "model families with car counts (+ unmapped); --known lists every family name", cmdFamilies},
		{"stats", "", "counts per status / verdict", cmdStats},
		{"activity", "[--since 24h|RFC3339] [--limit N]", "global feed of events + messages", cmdActivity},
		{"health", "", "server liveness (no auth)", cmdHealth},
		{"config", "set|show", "client config (~/.config/cardb/config.json)", cmdConfig},
		{"version", "", "print the cardb version", cmdVersion},
		{"help", "[COMMAND]", "show help", cmdHelp},
	}
}

// Server-side subcommands handled by cmd/cardb; listed here for help output only.
var serverCommands = []command{
	{name: "serve", summary: "run the HTTP server (CARDB_DATA_DIR, CARDB_LISTEN, CARDB_TOKENS / CARDB_TOKENS_FILE)"},
	{name: "backup", args: "DEST.sqlite3", summary: "consistent SQLite snapshot (VACUUM INTO)"},
	{name: "healthcheck", summary: "container healthcheck against the local listener"},
}

func findCommand(name string) *command {
	for i := range commands {
		if commands[i].name == name {
			return &commands[i]
		}
	}
	return nil
}

// Run executes one cardb client invocation and returns the process exit code.
func Run(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	return RunWithStdin(ctx, args, os.Stdin, stdout, stderr)
}

// RunWithStdin is Run with an explicit stdin (used by tests).
func RunWithStdin(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	e := &env{ctx: ctx, stdout: stdout, stderr: stderr, stdin: stdin}
	rest, err := parseGlobal(e, args)
	if err != nil {
		return e.fail(err)
	}
	if len(rest) == 0 {
		printUsage(stdout)
		return ExitUsage
	}
	name := rest[0]
	if name == "-h" || name == "--help" {
		printUsage(stdout)
		return ExitOK
	}
	if name == "--version" {
		name = "version"
	}
	cmd := findCommand(name)
	if cmd == nil {
		for _, s := range serverCommands {
			if s.name == name {
				return e.fail(usageErrorf("`cardb %s` is handled by the cardb binary entrypoint, not the client", name))
			}
		}
		return e.fail(usageErrorf("unknown command %q (run `cardb help`)", name))
	}
	if err := cmd.run(e, rest[1:]); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return ExitOK
		}
		return e.fail(err)
	}
	return ExitOK
}

// parseGlobal consumes global flags that precede the subcommand.
func parseGlobal(e *env, args []string) ([]string, error) {
	for len(args) > 0 {
		a := args[0]
		if !strings.HasPrefix(a, "-") || a == "-" || a == "-h" || a == "--help" || a == "--version" {
			return args, nil
		}
		if a == "--" {
			return args[1:], nil
		}
		name, val, hasVal := strings.Cut(strings.TrimLeft(a, "-"), "=")
		takeVal := func() (string, error) {
			if hasVal {
				args = args[1:]
				return val, nil
			}
			if len(args) < 2 {
				return "", usageErrorf("flag --%s needs a value", name)
			}
			v := args[1]
			args = args[2:]
			return v, nil
		}
		var err error
		switch name {
		case "json":
			e.json = !hasVal || val == "true" || val == "1"
			args = args[1:]
		case "url", "server":
			e.override.URL, err = takeVal()
		case "token":
			e.override.Token, err = takeVal()
		case "author":
			e.override.Author, err = takeVal()
		default:
			return nil, usageErrorf("unknown global flag %s (global flags: --json --server URL --token T --author A)", a)
		}
		if err != nil {
			return nil, err
		}
	}
	return args, nil
}

// ---- errors ----

type usageError struct{ msg string }

func (u *usageError) Error() string { return u.msg }

func usageErrorf(format string, a ...any) error { return &usageError{fmt.Sprintf(format, a...)} }

type notFoundError struct{ msg string }

func (n *notFoundError) Error() string { return n.msg }

func (e *env) fail(err error) int {
	code := ExitError
	var ue *usageError
	var nf *notFoundError
	var ae *client.APIError
	status := 0
	switch {
	case errors.As(err, &ue):
		code = ExitUsage
	case errors.As(err, &nf):
		code = ExitNotFound
	case errors.As(err, &ae):
		status = ae.Status
		if ae.Status == 404 {
			code = ExitNotFound
		}
	}
	msg, extra := apiFailure(err)
	if msg == "" {
		msg = err.Error()
	}
	if e.json {
		out := map[string]any{"error": msg, "exit_code": code}
		if status != 0 {
			out["status"] = status
		}
		for k, v := range extra {
			out[k] = v
		}
		b, _ := json.Marshal(out)
		fmt.Fprintln(e.stderr, string(b))
	} else {
		fmt.Fprintf(e.stderr, "cardb: %s\n", msg)
		if code == ExitUsage {
			fmt.Fprintln(e.stderr, "run `cardb help` or `cardb help COMMAND` for usage")
		}
	}
	return code
}

func (e *env) warnf(format string, a ...any) {
	fmt.Fprintf(e.stderr, "cardb: warning: "+format+"\n", a...)
}

// emit prints v as JSON in --json mode, else calls human.
func (e *env) emit(v any, human func(w io.Writer)) error {
	if e.json {
		enc := json.NewEncoder(e.stdout)
		enc.SetIndent("", "  ")
		enc.SetEscapeHTML(false)
		return enc.Encode(v)
	}
	human(e.stdout)
	return nil
}

// ---- flags ----

type flags struct {
	*flag.FlagSet
	cmd  string
	set  map[string]bool
	help bool
	e    *env
}

// newFlags makes a FlagSet that also accepts the global flags anywhere on the line,
// except those named in skip (a subcommand that gives them its own meaning).
func newFlags(e *env, cmd string, skip ...string) *flags {
	fs := flag.NewFlagSet(cmd, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	f := &flags{FlagSet: fs, cmd: cmd, set: map[string]bool{}, e: e}
	skipped := func(n string) bool {
		for _, s := range skip {
			if s == n {
				return true
			}
		}
		return false
	}
	fs.BoolVar(&e.json, "json", e.json, "print JSON")
	if !skipped("author") {
		fs.StringVar(&e.override.Author, "author", e.override.Author, "author of writes (X-Author)")
	}
	if !skipped("token") {
		fs.StringVar(&e.override.Token, "token", e.override.Token, "API token")
	}
	fs.StringVar(&e.override.URL, "server", e.override.URL, "server URL")
	fs.BoolVar(&f.help, "h", false, "help")
	fs.BoolVar(&f.help, "help", false, "help")
	return f
}

// parse handles flags before, between and after positionals. Everything after `--` is positional.
func (f *flags) parse(args []string) ([]string, error) {
	var tail []string
	for i, a := range args {
		if a == "--" {
			tail = append(tail, args[i+1:]...)
			args = args[:i]
			break
		}
	}
	var pos []string
	for {
		if err := f.FlagSet.Parse(args); err != nil {
			if errors.Is(err, flag.ErrHelp) {
				f.printHelp()
				return nil, flag.ErrHelp
			}
			msg := err.Error()
			if strings.Contains(msg, "provided but not defined") {
				msg += " (if it is text starting with '-', put it after `--`)"
			}
			return nil, usageErrorf("%s: %s", f.cmd, msg)
		}
		rest := f.FlagSet.Args()
		if len(rest) == 0 {
			break
		}
		pos = append(pos, rest[0])
		args = rest[1:]
	}
	if f.help {
		f.printHelp()
		return nil, flag.ErrHelp
	}
	f.Visit(func(fl *flag.Flag) { f.set[fl.Name] = true })
	return append(pos, tail...), nil
}

func (f *flags) isSet(name string) bool { return f.set[name] }

func (f *flags) printHelp() {
	w := f.e.stdout
	top := strings.Fields(f.cmd)[0]
	if c := findCommand(top); c != nil {
		fmt.Fprintf(w, "usage: cardb %s %s\n  %s\n\nflags:\n", f.cmd, c.args, c.summary)
	} else {
		fmt.Fprintf(w, "usage: cardb %s\n\nflags:\n", f.cmd)
	}
	global := map[string]bool{"json": true, "author": true, "token": true, "server": true, "h": true, "help": true}
	var lines []string
	f.VisitAll(func(fl *flag.Flag) {
		if global[fl.Name] {
			return
		}
		lines = append(lines, fmt.Sprintf("  --%-18s %s", fl.Name, fl.Usage))
	})
	sort.Strings(lines)
	for _, l := range lines {
		fmt.Fprintln(w, l)
	}
	fmt.Fprintln(w, "\nglobal: --json --server URL --token T --author A (accepted anywhere)")
}

// multi is a repeatable string flag.
type multi []string

func (m *multi) String() string { return strings.Join(*m, ",") }
func (m *multi) Set(v string) error {
	*m = append(*m, v)
	return nil
}

// splitList flattens repeatable values that may also be comma-separated.
func splitList(vals []string) []string {
	var out []string
	for _, v := range vals {
		for _, p := range strings.Split(v, ",") {
			if p = strings.TrimSpace(p); p != "" {
				out = append(out, p)
			}
		}
	}
	return out
}

func needArgs(cmd string, pos []string, min, max int, synopsis string) error {
	if len(pos) < min || (max >= 0 && len(pos) > max) {
		extra := ""
		if max >= 0 && len(pos) > max {
			extra = fmt.Sprintf(" (got %d arguments; quote text that contains spaces)", len(pos))
		}
		return usageErrorf("usage: cardb %s %s%s", cmd, synopsis, extra)
	}
	return nil
}

// ---- help ----

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "cardb — used-EV listings database client\n\nusage: cardb [--json] [--server URL] [--token T] [--author A] COMMAND [args] [flags]\n\ncommands:")
	for _, c := range commands {
		fmt.Fprintf(w, "  %-13s %s\n", c.name, c.summary)
	}
	fmt.Fprintln(w, "\nserver-side:")
	for _, c := range serverCommands {
		fmt.Fprintf(w, "  %-13s %s\n", c.name, c.summary)
	}
	fmt.Fprintln(w, `
CAR is a numeric car id or any alias/slug. Flags may follow positional args.
Config: CARDB_URL, CARDB_TOKEN, CARDB_AUTHOR env, else ~/.config/cardb/config.json.
Author defaults to $AGTERM_SESSION_ID when set.
Exit codes: 0 ok, 1 error, 2 usage, 3 not found.`)
}

func cmdHelp(e *env, args []string) error {
	if len(args) == 0 {
		printUsage(e.stdout)
		return nil
	}
	c := findCommand(args[0])
	if c == nil {
		return usageErrorf("unknown command %q", args[0])
	}
	return c.run(e, append(args[1:], "--help"))
}

func cmdVersion(e *env, args []string) error {
	f := newFlags(e, "version")
	if _, err := f.parse(args); err != nil {
		return err
	}
	return e.emit(map[string]string{"version": api.Version}, func(w io.Writer) { fmt.Fprintf(w, "cardb %s\n", api.Version) })
}

func cmdConfig(e *env, args []string) error {
	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" {
		fmt.Fprintln(e.stdout, "usage: cardb config set [--url URL] [--token T] [--author A]\n       cardb config show")
		if len(args) == 0 {
			return usageErrorf("config: missing subcommand")
		}
		return nil
	}
	switch args[0] {
	case "set":
		f := newFlags(e, "config set", "token", "author")
		u := f.String("url", "", "server URL, e.g. https://ev.example.lan")
		tok := f.String("token", "", "API token")
		au := f.String("author", "", "default author (empty string clears)")
		pos, err := f.parse(args[1:])
		if err != nil {
			return err
		}
		if len(pos) > 0 {
			return usageErrorf("config set takes only flags")
		}
		path := client.ConfigPath()
		c, err := client.LoadConfigFile(path)
		if err != nil {
			return err
		}
		if f.isSet("url") {
			c.URL = strings.TrimRight(*u, "/")
		}
		if f.isSet("token") {
			c.Token = *tok
		}
		if f.isSet("author") {
			c.Author = *au
		}
		if err := client.SaveConfigFile(path, c); err != nil {
			return err
		}
		return e.emit(map[string]any{"path": path, "url": c.URL, "token_set": c.Token != "", "author": c.Author},
			func(w io.Writer) { fmt.Fprintf(w, "wrote %s\n", path) })
	case "show":
		f := newFlags(e, "config show")
		if _, err := f.parse(args[1:]); err != nil {
			return err
		}
		c, err := client.Resolve(e.override)
		if err != nil {
			return err
		}
		masked := ""
		if c.Token != "" {
			masked = c.Token[:min(4, len(c.Token))] + "…"
		}
		return e.emit(map[string]any{"path": client.ConfigPath(), "url": c.URL, "token": masked, "author": c.Author},
			func(w io.Writer) {
				fmt.Fprintf(w, "config: %s\nurl:    %s\ntoken:  %s\nauthor: %s\n", client.ConfigPath(), c.URL, masked, c.Author)
			})
	}
	return usageErrorf("config: unknown subcommand %q (set|show)", args[0])
}
