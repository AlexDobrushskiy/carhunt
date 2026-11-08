// The buyer profile as the UI needs it (labels, tiers, option keys). Pure: no server imports.
import type { components } from "./cardb-schema";

export type Profile = components["schemas"]["Profile"];
export type Role = "owner" | "viewer" | "other";

export interface UiProfile {
  ownerName: string;
  tz: string;
  homeCity: string;
  homeCountry: string;
  currency: string;
  users: { name: string; role: "owner" | "viewer" }[];
  tiers: { tier: number; label: string; rules: string[] }[];
  defaultTiers: number[];
  optionKeys: string[];
  mustHave: string[];
  optionsWanted: Record<string, number>;
  countries: string[];
  hardFilters: string[];
  /** false when GET /profile failed: labels fall back to neutral words. */
  loaded: boolean;
}

/** Built-in icon row when the profile names no wanted options. */
export const DEFAULT_ICON_KEYS = ["electric_seats", "power_tailgate", "pano", "premium_audio"];
export const MAX_ICONS = 4;

export function uiProfile(p: Profile | null | undefined): UiProfile {
  const o = p?.owner ?? {};
  const tiers = (p?.tiers ?? [])
    .filter((t): t is { tier: number; label?: string; rules?: string[] } => typeof t.tier === "number")
    .map((t) => ({ tier: t.tier, label: t.label ?? `Tier ${t.tier}`, rules: t.rules ?? [] }))
    .sort((a, b) => a.tier - b.tier);
  return {
    ownerName: o.name || "owner",
    tz: validTz(o.tz) ? (o.tz as string) : "UTC",
    homeCity: o.home?.city ?? "",
    homeCountry: (o.home?.country ?? "").toUpperCase(),
    currency: p?.currency || "EUR",
    users: (p?.users ?? []).map((u) => ({ name: u.name, role: u.role })),
    tiers,
    defaultTiers: p?.queue_default_tiers?.length ? p.queue_default_tiers : tiers.map((t) => t.tier),
    optionKeys: p?.option_keys ?? [],
    mustHave: p?.must_have ?? [],
    optionsWanted: p?.options_wanted ?? {},
    countries: (p?.countries ?? []).map((c) => c.toUpperCase()),
    hardFilters: p?.hard_filters ?? [],
    loaded: Boolean(p),
  };
}

function validTz(tz: string | undefined): boolean {
  if (!tz) return false;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

export function roleOf(p: UiProfile, name: string): Role {
  const u = p.users.find((x) => x.name === name);
  if (u) return u.role;
  return name && name === p.ownerName ? "owner" : "other";
}

/** Users who rate (owner + viewers); `?user=` is sent only for these, cardb 422s on other names. */
export function isUser(p: UiProfile, name: string): boolean {
  return p.users.some((x) => x.name === name);
}

/** Icon row: must-haves first, then the heaviest wanted options; built-in four when the profile has none. */
export function iconKeys(p: UiProfile): string[] {
  const wanted = Object.entries(p.optionsWanted)
    .filter(([, w]) => w > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k);
  const keys = [...new Set([...p.mustHave, ...wanted])].slice(0, MAX_ICONS);
  return keys.length ? keys : DEFAULT_ICON_KEYS;
}

/** Filterable options in the filter sheet: icon keys first, then the rest of the wanted ones. */
export function filterOptionKeys(p: UiProfile): string[] {
  return [...new Set([...iconKeys(p), ...p.mustHave, ...Object.keys(p.optionsWanted)])];
}

/** "Needs <owner>": agents raise the flag for the owner, whoever is viewing. */
export function needsLabel(p: UiProfile): string {
  return `Needs ${p.ownerName}`;
}

export function homeLabel(p: UiProfile): string {
  return p.homeCity || p.homeCountry || "home";
}
