import { useState } from "react";
import { send } from "@/lib/client";
import { VERDICTS } from "@/lib/vocab";

interface Props {
  car: number | string;
  value?: string | null;
  note?: string | null;
}

export default function VerdictControl({ car, value: initValue = null, note: initNote = "" }: Props) {
  const [value, setValue] = useState<string | null>(initValue ?? null);
  const [note, setNote] = useState(initNote ?? "");
  const [savedNote, setSavedNote] = useState(initNote ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function pick(v: string) {
    const prev = value;
    const next = v === value ? null : v;
    setValue(next);
    setBusy(true);
    setErr("");
    try {
      if (next) await send("PUT", `cars/${car}/verdict`, { value: next, note: note || undefined });
      else await send("DELETE", `cars/${car}/verdict`);
      setSavedNote(next ? note : "");
    } catch (e) {
      setValue(prev);
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (note === savedNote) return;
    if (!value) {
      setErr("Pick 👍 🤔 👎 first");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await send("PUT", `cars/${car}/verdict`, { value, note });
      setSavedNote(note);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const btn = "h-11 min-w-14 text-xl";
  return (
    <div className="flex flex-col gap-2" data-testid="verdict-control" data-verdict={value ?? "none"}>
      <div className="flex items-center gap-2">
        {VERDICTS.map((v) => {
          const on = value === v.value;
          const tone = v.value === "up" ? "border-good bg-good-bg" : v.value === "maybe" ? "border-warn bg-warn-bg" : "border-bad bg-bad-bg";
          return (
            <button
              key={v.value}
              type="button"
              aria-pressed={on}
              aria-label={v.label}
              title={on ? `${v.label} (tap again to clear)` : v.label}
              disabled={busy}
              onClick={() => pick(v.value)}
              className={`${btn} px-2 rounded-lg border transition ${on ? tone : "border-line bg-surface-2 opacity-70 hover:opacity-100"} disabled:cursor-wait`}
            >
              {v.emoji}
            </button>
          );
        })}
        {busy ? <span className="text-xs text-muted">saving…</span> : null}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={note}
          placeholder="verdict note (optional)"
          aria-label="Verdict note"
          onChange={(e) => setNote(e.target.value)}
          onBlur={saveNote}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="flex-1 min-w-0 h-9 px-3 rounded-lg border border-line bg-surface-2 text-sm placeholder:text-muted"
        />
        {note !== savedNote ? (
          <button type="button" onClick={saveNote} className="h-9 px-3 rounded-lg bg-accent text-bg text-sm font-medium">
            Save
          </button>
        ) : null}
      </div>
      {err ? <p className="text-xs text-bad">{err}</p> : null}
    </div>
  );
}
