import { useState } from "react";
import { send } from "@/lib/client";
import { STATUSES, STATUS_LABEL } from "@/lib/vocab";

interface Props {
  car: number | string;
  status: string;
  needsOwner: boolean;
  needsOwnerReason?: string | null;
  /** "Needs <owner>" fallback text. */
  needsLabel: string;
  /** Car version at page load: a write after someone else's change gets 412 instead of silently overwriting it. */
  version?: number | null;
}

interface Written { version?: number; status?: string }

const conflict = (e: unknown) => {
  const msg = (e as Error).message;
  return (e as { status?: number }).status === 412 ? "Changed by someone else meanwhile: reload the page and retry." : msg;
};

export default function StatusControl({ car, status: initStatus, needsOwner: initNeeds, needsOwnerReason, needsLabel, version: initVersion }: Props) {
  const [version, setVersion] = useState(initVersion ?? null);
  const [status, setStatus] = useState(initStatus);
  const [pending, setPending] = useState(initStatus);
  const [reason, setReason] = useState("");
  const [needs, setNeeds] = useState(initNeeds);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function saveStatus() {
    setBusy(true);
    setErr("");
    try {
      const res = await send<Written>("POST", `cars/${car}/status`, { status: pending, reason: reason || undefined, version: version ?? undefined });
      if (res?.version != null) setVersion(res.version);
      setStatus(pending);
      setReason("");
    } catch (e) {
      setErr(conflict(e));
    } finally {
      setBusy(false);
    }
  }

  async function resolveNeeds() {
    setBusy(true);
    setErr("");
    try {
      const res = await send<Written>("PATCH", `cars/${car}`, { needs_owner: false, version: version ?? undefined });
      if (res?.version != null) setVersion(res.version);
      setNeeds(false);
    } catch (e) {
      setErr(conflict(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {needs ? (
        <div className="rounded-lg bg-warn-bg text-warn px-3 py-2 text-sm flex items-start gap-2" data-testid="needs-owner">
          <span className="flex-1">⚑ {needsOwnerReason || needsLabel}</span>
          <button type="button" disabled={busy} onClick={resolveNeeds} className="shrink-0 text-xs underline">
            Done
          </button>
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        <select
          value={pending}
          onChange={(e) => setPending(e.target.value)}
          aria-label="Status"
          className="h-9 px-2 rounded-lg border border-line bg-surface-2 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        {pending !== status ? (
          <>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="why (optional)"
              aria-label="Status reason"
              className="flex-1 min-w-0 h-9 px-2 rounded-lg border border-line bg-surface-2 text-sm placeholder:text-muted"
            />
            <button type="button" disabled={busy} onClick={saveStatus} className="h-9 px-3 rounded-lg bg-accent text-bg text-sm font-medium">
              Set
            </button>
          </>
        ) : null}
      </div>
      {err ? <p className="text-xs text-bad">{err}</p> : null}
    </div>
  );
}
