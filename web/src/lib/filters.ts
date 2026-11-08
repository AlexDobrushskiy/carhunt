import type { CarQuery } from "./cardb";

/** Saved views = preset filters; the page's own params narrow them further. */
export const VIEWS = [
  { key: "active", label: "Active", query: { status: ["new", "to_contact", "contacted", "talking", "ready_to_visit", "visited"] } },
  { key: "review", label: "To review", query: { verdict: ["none"], status: ["new", "to_contact", "contacted", "talking", "ready_to_visit", "visited"] } },
  { key: "needs", label: "Needs owner", query: { needs_owner: true } },
  { key: "to_contact", label: "To contact", query: { status: ["to_contact"] } },
  { key: "talking", label: "Talking", query: { status: ["contacted", "talking"] } },
  { key: "visit", label: "Visit", query: { status: ["ready_to_visit", "visited"] } },
  { key: "liked", label: "👍", query: { verdict: ["up"] } },
  { key: "dups", label: "Dupes?", query: { has_duplicates: true } },
  { key: "closed", label: "Closed", query: { status: ["closed", "dropped", "bought"] } },
  { key: "all", label: "All", query: {} },
] as const satisfies readonly { key: string; label: string; query: CarQuery }[];

export type ViewKey = (typeof VIEWS)[number]["key"];
export const DEFAULT_VIEW: ViewKey = "active";

const NUMS = ["hp_min", "hp_max", "year_min", "year_max", "km_max", "price_min", "price_max", "distance_km_max"] as const;
const LISTS = ["drive", "fuel", "country", "seller_type", "status", "verdict"] as const;
export const FUELS = ["bev", "phev", "hev", "mhev", "petrol", "diesel", "lpg", "cng", "hydrogen", "unknown"] as const;
export const MARKETS = ["home", "abroad"] as const;
export const SORTS = [
  { key: "last_activity", label: "Recent activity" },
  { key: "price", label: "Price" },
  { key: "km", label: "Mileage" },
  { key: "year", label: "Year" },
  { key: "distance_km", label: "Distance" },
  { key: "created", label: "Newest found" },
  { key: "model", label: "Model" },
  { key: "deal_rank", label: "Deal rank" },
  { key: "score", label: "Score" },
] as const;

export interface FilterState {
  view: ViewKey;
  goodDeal: boolean;
  families: string[]; // model_family names; "none" = unmapped
  model: string; // legacy substring filter (old URLs), no form field
  q: string;
  market: string;
  nums: Partial<Record<(typeof NUMS)[number], number>>;
  lists: Record<(typeof LISTS)[number], string[]>;
  options: Record<string, string>; // key → yes|no|unknown|yes_or_unknown
  sort: string;
  order: string;
}

function intOrUndef(v: string | null): number | undefined {
  if (v == null || v.trim() === "") return undefined;
  const n = parseInt(v.replace(/[\s.,_]/g, ""), 10);
  return Number.isFinite(n) ? n : undefined;
}

/** `optionKeys` = filterable options from the profile (others in the URL are ignored). */
export function parseFilters(sp: URLSearchParams, optionKeys: string[] = []): FilterState {
  const view = (VIEWS.find((v) => v.key === sp.get("view"))?.key ?? DEFAULT_VIEW) as ViewKey;
  const nums: FilterState["nums"] = {};
  for (const k of NUMS) {
    const n = intOrUndef(sp.get(k));
    if (n !== undefined) nums[k] = n;
  }
  const lists = Object.fromEntries(LISTS.map((k) => [k, sp.getAll(k).filter(Boolean)])) as FilterState["lists"];
  const options: Record<string, string> = {};
  for (const key of optionKeys) {
    const v = sp.get(`opt_${key}`);
    if (v && ["yes", "no", "unknown", "yes_or_unknown"].includes(v)) options[key] = v;
  }
  const families = [...new Set(sp.getAll("family").flatMap((v) => v.split(",")).map((v) => v.trim()).filter(Boolean))];
  return {
    view,
    goodDeal: ["1", "true", "yes", "on"].includes((sp.get("good_deal") ?? "").toLowerCase()),
    families,
    model: (sp.get("model") ?? "").trim(),
    q: (sp.get("q") ?? "").trim(),
    market: (MARKETS as readonly string[]).includes(sp.get("market") ?? "") ? (sp.get("market") as string) : "",
    nums,
    lists,
    options,
    sort: SORTS.some((s) => s.key === sp.get("sort")) ? (sp.get("sort") as string) : "last_activity",
    order: sp.get("order") === "asc" || sp.get("order") === "desc" ? (sp.get("order") as string) : "",
  };
}

/** The view preset, overridden by any explicit list filter of the same name. */
export function toApiQuery(f: FilterState): CarQuery {
  const preset = VIEWS.find((v) => v.key === f.view)?.query ?? {};
  const q: CarQuery = { ...preset };
  for (const [k, v] of Object.entries(f.lists)) if (v.length) q[k] = v;
  Object.assign(q, f.nums);
  if (f.goodDeal) q.good_deal = true;
  if (f.families.length) q.model_family = f.families;
  if (f.model) q.model = f.model;
  if (f.q) q.q = f.q;
  if (f.market) q.market = f.market;
  const opts = Object.entries(f.options).map(([k, v]) => `${k}:${v}`);
  if (opts.length) q.option = opts;
  q.sort = f.sort;
  if (f.order) q.order = f.order;
  q.limit = 1000;
  return q;
}

/** Number of user-set filters beyond the view (for the filter button badge). */
export function activeFilterCount(f: FilterState): number {
  return (
    Object.keys(f.nums).length +
    Object.values(f.lists).filter((l) => l.length).length +
    Object.keys(f.options).length +
    (f.goodDeal ? 1 : 0) +
    (f.families.length ? 1 : 0) +
    (f.model ? 1 : 0) +
    (f.q ? 1 : 0) +
    (f.market ? 1 : 0)
  );
}

const familyKey = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();

/**
 * URL family values → canonical names from the API's `known` list (the API 400s on unknown names).
 * Unknown values are dropped; `none` (unmapped) is kept. Without a list, values pass through.
 */
export function resolveFamilies(selected: string[], known: string[] | null | undefined): string[] {
  if (!known) return selected;
  const byKey = new Map(known.map((k) => [familyKey(k), k]));
  const out = selected.map((s) => (familyKey(s) === "none" ? "none" : byKey.get(familyKey(s)))).filter((s): s is string => Boolean(s));
  return [...new Set(out)];
}

/** Families grouped by make, in API order; selected names missing from the list go last with count 0. */
export function familyGroups(
  families: { family: string; make: string; count: number }[],
  selected: string[],
): { make: string; items: { family: string; label: string; count: number }[] }[] {
  const groups: { make: string; items: { family: string; label: string; count: number }[] }[] = [];
  for (const fm of families) {
    let g = groups.find((x) => x.make === fm.make);
    if (!g) groups.push((g = { make: fm.make, items: [] }));
    const label = fm.family.startsWith(`${fm.make} `) ? fm.family.slice(fm.make.length + 1) : fm.family;
    g.items.push({ family: fm.family, label, count: fm.count });
  }
  const missing = selected.filter((s) => s !== "none" && !families.some((fm) => fm.family === s));
  if (missing.length) groups.push({ make: "No cars now", items: missing.map((m) => ({ family: m, label: m, count: 0 })) });
  return groups;
}

/** Dropdown summary: "Any model" or the selected names. */
export function familySummary(selected: string[]): string {
  return selected.length ? selected.map((s) => (s === "none" ? "Unmapped" : s)).join(", ") : "Any model";
}

/** Same filters, different view (tabs keep the user's narrowing). */
export function hrefWith(sp: URLSearchParams, changes: Record<string, string | null>): string {
  const u = new URLSearchParams(sp);
  for (const [k, v] of Object.entries(changes)) {
    if (v == null || v === "") u.delete(k);
    else u.set(k, v);
  }
  const s = u.toString();
  return s ? `/?${s}` : "/";
}

/** Count shown on a view tab, from /stats. */
export function viewCount(key: ViewKey, stats: { by_status?: Record<string, number>; by_verdict?: Record<string, number>; needs_owner?: number; duplicate_proposals?: number; total?: number } | null): number | null {
  if (!stats) return null;
  const s = stats.by_status ?? {};
  const sum = (...k: string[]) => k.reduce((a, x) => a + (s[x] ?? 0), 0);
  switch (key) {
    case "active": return sum("new", "to_contact", "contacted", "talking", "ready_to_visit", "visited");
    case "review": return null; // needs a verdict×status cross count the API does not give
    case "needs": return stats.needs_owner ?? null;
    case "to_contact": return sum("to_contact");
    case "talking": return sum("contacted", "talking");
    case "visit": return sum("ready_to_visit", "visited");
    case "liked": return stats.by_verdict?.up ?? null;
    case "dups": return stats.duplicate_proposals ?? null;
    case "closed": return sum("closed", "dropped", "bought");
    case "all": return stats.total ?? null;
  }
}
