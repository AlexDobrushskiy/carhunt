import { useState } from "react";
import { send } from "@/lib/client";

export interface NoteRow {
  id: number;
  author?: string;
  author_kind?: string;
  text: string;
  pinned?: boolean;
  created_at?: string;
  updated_at?: string;
}

interface Props {
  car: number | string;
  notes: NoteRow[];
  /** The viewer: their own notes show as "You". */
  me: string;
  tz: string;
  /** Viewers read notes but cannot write them (cardb: viewer tokens write only their own verdict). */
  readOnly?: boolean;
}

function order(ns: NoteRow[]): NoteRow[] {
  return [...ns].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || (b.created_at ?? "").localeCompare(a.created_at ?? ""));
}

const box = "w-full rounded-lg border border-line bg-surface-2 p-2.5 text-sm placeholder:text-muted";
const btn = "h-9 px-3 rounded-lg text-sm";

export default function NotesPanel({ car, notes: initial, me, tz, readOnly = false }: Props) {
  const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const stamp = (s?: string) => (s ? fmt.format(new Date(s)) : "");
  const [notes, setNotes] = useState<NoteRow[]>(order(initial));
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const add = () =>
    run(async () => {
      const text = draft.trim();
      if (!text) return;
      const n = await send<NoteRow>("POST", `cars/${car}/notes`, { text });
      if (n) setNotes((ns) => order([n, ...ns]));
      setDraft("");
    });

  const save = (id: number) =>
    run(async () => {
      const n = await send<NoteRow>("PATCH", `notes/${id}`, { text: editText.trim() });
      if (n) setNotes((ns) => order(ns.map((x) => (x.id === id ? n : x))));
      setEditing(null);
    });

  const togglePin = (note: NoteRow) =>
    run(async () => {
      const n = await send<NoteRow>("PATCH", `notes/${note.id}`, { pinned: !note.pinned });
      if (n) setNotes((ns) => order(ns.map((x) => (x.id === note.id ? n : x))));
    });

  const remove = (id: number) =>
    run(async () => {
      if (!confirm("Delete this note?")) return;
      await send("DELETE", `notes/${id}`);
      setNotes((ns) => ns.filter((x) => x.id !== id));
    });

  return (
    <div className="flex flex-col gap-3" data-testid="notes">
      {readOnly ? null : <div className="flex flex-col gap-2">
        <textarea
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a note (agents read these too)"
          aria-label="New note"
          className={box}
        />
        <div className="flex items-center gap-2">
          <button type="button" disabled={busy || !draft.trim()} onClick={add} className={`${btn} bg-accent text-bg font-medium disabled:opacity-40`}>
            Add note
          </button>
          {busy ? <span className="text-xs text-muted">saving…</span> : null}
          {err ? <span className="text-xs text-bad">{err}</span> : null}
        </div>
      </div>}
      {notes.length === 0 ? <p className="text-sm text-muted">No notes yet.</p> : null}
      <ul className="flex flex-col gap-2">
        {notes.map((n) => {
          const mine = Boolean(me) && n.author === me;
          return (
            <li key={n.id} className={`rounded-xl border p-3 ${n.pinned ? "border-warn" : "border-line"} ${mine ? "bg-surface" : "bg-surface-2"}`} data-note-id={n.id}>
              <p className="text-xs text-muted mb-1">
                {n.pinned ? "📌 " : ""}
                {mine ? "You" : n.author ?? "agent"} · {stamp(n.created_at)}
                {n.updated_at && n.updated_at !== n.created_at ? ` · edited ${stamp(n.updated_at)}` : ""}
              </p>
              {editing === n.id ? (
                <div className="flex flex-col gap-2">
                  <textarea rows={3} value={editText} onChange={(e) => setEditText(e.target.value)} aria-label="Edit note" className={box} autoFocus />
                  <div className="flex gap-2">
                    <button type="button" disabled={busy || !editText.trim()} onClick={() => save(n.id)} className={`${btn} bg-accent text-bg font-medium`}>
                      Save
                    </button>
                    <button type="button" onClick={() => setEditing(null)} className={`${btn} border border-line`}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className="text-sm whitespace-pre-wrap break-words">{n.text}</p>
                  {readOnly ? null : <div className="flex gap-3 mt-2 text-xs">
                    <button type="button" className="text-accent" onClick={() => { setEditing(n.id); setEditText(n.text); }}>Edit</button>
                    <button type="button" className="text-muted" onClick={() => togglePin(n)}>{n.pinned ? "Unpin" : "Pin"}</button>
                    <button type="button" className="text-bad" onClick={() => remove(n.id)}>Delete</button>
                  </div>}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
