import { useState } from "react";
import { send } from "@/lib/client";
import { when } from "@/lib/format";
import type { GoodDeal } from "@/lib/cardb";

interface Props {
  car: number | string;
  goodDeal: boolean;
  note?: string | null;
  by?: string | null;
  at?: string | null;
  rank?: string | null;
  tz?: string;
}

export default function GoodDealControl({ car, goodDeal, note: initNote, by: initBy, at: initAt, rank, tz = "UTC" }: Props) {
  const [state, setState] = useState<GoodDeal>({ good_deal: goodDeal, note: initNote ?? null, by: initBy ?? null, at: initAt ?? null });
  const [note, setNote] = useState(initNote ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const on = state.good_deal;
  const saved = state.note ?? "";

  async function put(body: { good_deal: boolean; note?: string }) {
    setBusy(true);
    setErr("");
    try {
      const res = await send<GoodDeal>("PUT", `cars/${car}/good-deal`, body);
      if (res) {
        setState(res);
        setNote(res.note ?? "");
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Turning on sends the typed note (if any); off clears the note server-side.
  const toggle = () => put(on ? { good_deal: false } : { good_deal: true, ...(note.trim() ? { note } : {}) });
  const saveNote = () => {
    if (on && note !== saved) void put({ good_deal: true, note });
  };

  return (
    <div className="flex flex-col gap-2" data-good-deal={on ? "on" : "off"}>
      <div className="flex items-center gap-2 flex-wrap">
        {on ? (
          <span
            data-testid="good-deal-badge"
            title={saved || undefined}
            className="inline-flex items-center h-7 text-sm font-medium rounded-full px-2.5 bg-good-bg text-good whitespace-nowrap"
          >
            ★ Good deal{rank ? ` · ${rank}` : ""}
          </span>
        ) : rank ? (
          <span className="text-xs text-muted">deal rank {rank}</span>
        ) : null}
        {busy ? <span className="text-xs text-muted">saving…</span> : null}
        <button
          type="button"
          data-testid="good-deal-toggle"
          aria-pressed={on}
          disabled={busy}
          onClick={toggle}
          title={on ? "Remove the good-deal flag" : "Mark as a good deal"}
          className={`h-10 px-3 rounded-lg border text-sm transition disabled:cursor-wait ${on ? "ml-auto border-line bg-surface-2 text-muted" : "border-good text-good bg-surface-2 font-medium"}`}
        >
          {on ? "Unmark" : "☆ Mark good deal"}
        </button>
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          data-testid="good-deal-note"
          value={note}
          maxLength={300}
          placeholder={on ? "why it's a good deal (optional)" : "note for when you mark it (optional)"}
          aria-label="Good deal note"
          onChange={(e) => setNote(e.target.value)}
          onBlur={saveNote}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="flex-1 min-w-0 h-9 px-3 rounded-lg border border-line bg-surface-2 text-sm placeholder:text-muted"
        />
        {on && note !== saved ? (
          <button type="button" disabled={busy} onClick={saveNote} className="h-9 px-3 rounded-lg bg-accent text-bg text-sm font-medium">
            Save
          </button>
        ) : null}
      </div>
      {on && (state.by || state.at) ? (
        <p className="text-xs text-muted">
          {[state.by ? `by ${state.by}` : null, state.at ? when(state.at, tz) : null].filter(Boolean).join(" · ")}
        </p>
      ) : null}
      {err ? <p className="text-xs text-bad">{err}</p> : null}
    </div>
  );
}
