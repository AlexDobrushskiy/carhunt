// "To rate" queue page helpers (pure; shared by the page, cards and tests).

export const QUEUE_LIMIT = 200;
export const QUEUE_LIMIT_MAX = 1000;

export type QueueSpec = "" | "confirmed" | "unknown";

/** Spec chips from the profile's must-have options; none → no chips (cardb 400s on spec without must_have). */
export function queueSpecs(mustHave: string[], label: (k: string) => string): { value: Exclude<QueueSpec, "">; label: string; title: string }[] {
  if (!mustHave.length) return [];
  const names = mustHave.map(label);
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
  const short = names.length <= 2 ? names.join(" + ") : "Must-haves";
  return [
    { value: "confirmed", label: `${short} ✓`, title: `${list} all confirmed` },
    { value: "unknown", label: "Spec unknown", title: `${list}: at least one still unknown, none is a no` },
  ];
}

export interface QueueParams {
  /** Show every profile tier, not only queue_default_tiers. */
  all: boolean;
  spec: QueueSpec;
  limit: number;
}

const truthy = (v: string | null) => ["1", "true", "yes", "on"].includes((v ?? "").toLowerCase());

export function parseQueueParams(sp: URLSearchParams): QueueParams {
  const n = parseInt(sp.get("limit") ?? "", 10);
  const limit = Number.isFinite(n) && n > 0 ? Math.min(n, QUEUE_LIMIT_MAX) : QUEUE_LIMIT;
  const s = sp.get("spec");
  const spec: QueueSpec = s === "confirmed" || s === "unknown" ? s : "";
  return { all: truthy(sp.get("all")), spec, limit };
}

/** Tiers to ask for: all profile tiers, or the default ones. Empty = let cardb use its default. */
export function queueTiers(all: boolean, tiers: number[], defaults: number[]): string[] {
  return (all ? tiers : defaults).map(String);
}

/** Tiers hidden by default (the toggle shows them); empty → no toggle. */
export function hiddenTiers(tiers: number[], defaults: number[]): number[] {
  return tiers.filter((t) => !defaults.includes(t));
}

export function queueHref(p: Partial<QueueParams>): string {
  const u = new URLSearchParams();
  if (p.all) u.set("all", "1");
  if (p.spec) u.set("spec", p.spec);
  if (p.limit && p.limit !== QUEUE_LIMIT) u.set("limit", String(Math.min(p.limit, QUEUE_LIMIT_MAX)));
  const s = u.toString();
  return s ? `/queue?${s}` : "/queue";
}

export function tierTone(tier: number): string {
  return tier === 1 ? "bg-accent-bg text-accent" : tier === 2 ? "bg-good-bg text-good" : "bg-surface-2 text-muted";
}

/**
 * "−12 % vs ID.5 · 2025": landed cost relative to the peer group. cardb's price_gap_pct is positive when the car is
 * cheaper than peers, so the shown sign is flipped (minus = below fair). The family's make prefix is dropped.
 */
export function gapChip(pct: number | null | undefined, basis: string | null | undefined): { text: string; tone: string } | null {
  if (pct == null || !Number.isFinite(pct)) return null;
  const r = -Math.round(pct);
  const sign = r < 0 ? "−" : r > 0 ? "+" : "±";
  const vs = basis ? ` vs ${basis.replace(/^\S+\s+/, "")}` : "";
  const tone = r <= -5 ? "bg-good-bg text-good" : r >= 5 ? "bg-bad-bg text-bad" : "bg-surface-2 text-muted";
  return { text: `${sign}${Math.abs(r)} %${vs}`, tone };
}

export type AdBadge = { kind: "removed" | "sold" | "gone"; label: string } | null;

/** Car-level ad badge when no ad is live: removed beats the generic "ad gone". */
export function adBadge(c: { live_listing_count?: number; listing_count?: number; removed_listing_count?: number }): AdBadge {
  if ((c.live_listing_count ?? 0) > 0 || (c.listing_count ?? 0) === 0) return null;
  if ((c.removed_listing_count ?? 0) > 0) return { kind: "removed", label: "ad removed" };
  return { kind: "gone", label: "ad gone" };
}

/** Same for the car page, which knows every listing's status. */
export function adBadgeFromListings(listings: { status?: string | null }[]): AdBadge {
  if (!listings.length || listings.some((l) => l.status === "live")) return null;
  if (listings.some((l) => l.status === "removed")) return { kind: "removed", label: "ad removed" };
  if (listings.some((l) => l.status === "sold")) return { kind: "sold", label: "sold" };
  return { kind: "gone", label: "ad gone" };
}

/** Per-listing status pill on the car page. */
export function listingStatus(status: string | null | undefined): { label: string; tone: string } {
  switch (status) {
    case "live": return { label: "live", tone: "bg-good-bg text-good" };
    case "removed": return { label: "ad removed", tone: "bg-bad-bg text-bad" };
    case "sold": return { label: "sold", tone: "bg-warn-bg text-warn" };
    default: return { label: status || "unknown", tone: "bg-surface-2 text-muted" };
  }
}

export interface AdChip { url: string; site: string; status: string; live: boolean; label: string; note: string | null }

/** Car-page ad links under the specs line: live ads first; a repeated site gets its price to tell the ads apart. */
export function adChips(listings: { url?: string | null; site?: string | null; status?: string | null; price?: number | null }[], fmtPrice: (v: number | null | undefined) => string): AdChip[] {
  const withUrl = listings.filter((l) => l.url);
  const perSite = new Map<string, number>();
  for (const l of withUrl) perSite.set(l.site ?? "ad", (perSite.get(l.site ?? "ad") ?? 0) + 1);
  const chips = withUrl.map((l) => {
    const site = l.site ?? "ad";
    const live = l.status === "live";
    const dup = (perSite.get(site) ?? 0) > 1 && l.price != null;
    return {
      url: l.url as string,
      site,
      status: l.status ?? "unknown",
      live,
      label: dup ? `${site} · ${fmtPrice(l.price)}` : site,
      note: live ? null : listingStatus(l.status).label,
    };
  });
  return [...chips.filter((c) => c.live), ...chips.filter((c) => !c.live)];
}
