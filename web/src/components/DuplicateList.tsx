import { useState } from "react";
import { send } from "@/lib/client";

interface Dup {
  id?: number;
  other_car_id?: number;
  other_title?: string;
  score?: number;
  reasons?: string[];
}

export default function DuplicateList({ car, dups: initial }: { car: number; dups: Dup[] }) {
  const [dups, setDups] = useState(initial);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState("");

  async function act(d: Dup, kind: "merge" | "reject") {
    if (kind === "merge" && !confirm(`Merge #${d.other_car_id} into this car? Its ads, chats, notes and photos move here.`)) return;
    setBusy(d.id ?? null);
    setErr("");
    try {
      if (kind === "merge") {
        await send("POST", `cars/${car}/merge`, { from: [String(d.other_car_id)] });
        location.reload();
        return;
      }
      await send("POST", `duplicates/${d.id}/reject`);
      setDups((xs) => xs.filter((x) => x.id !== d.id));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!dups.length) return null;
  return (
    <div className="rounded-xl border border-warn bg-warn-bg p-3 flex flex-col gap-3" data-testid="duplicates">
      <p className="text-sm font-medium text-warn">Possibly the same car as:</p>
      {dups.map((d) => (
        <div key={d.id} className="flex flex-col gap-1.5">
          <a href={`/cars/${d.other_car_id}`} className="text-sm font-medium">
            #{d.other_car_id} {d.other_title}
          </a>
          <p className="text-xs text-muted">
            {d.score != null ? `${Math.round(d.score * 100)}% · ` : ""}
            {(d.reasons ?? []).join(" · ")}
          </p>
          <div className="flex gap-2">
            <button type="button" disabled={busy != null} onClick={() => act(d, "merge")} className="h-8 px-3 rounded-lg bg-accent text-bg text-xs font-medium">
              Same car: merge here
            </button>
            <button type="button" disabled={busy != null} onClick={() => act(d, "reject")} className="h-8 px-3 rounded-lg border border-line text-xs">
              Different car
            </button>
          </div>
        </div>
      ))}
      {err ? <p className="text-xs text-bad">{err}</p> : null}
    </div>
  );
}
