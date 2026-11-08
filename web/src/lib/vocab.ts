// Display vocabulary shared by server pages and islands (no server imports here).

export const STATUSES = ["new", "to_contact", "contacted", "talking", "ready_to_visit", "visited", "closed", "dropped", "bought"] as const;
export type StatusKey = (typeof STATUSES)[number];

export const STATUS_LABEL: Record<StatusKey, string> = {
  new: "New",
  to_contact: "To contact",
  contacted: "Contacted",
  talking: "Talking",
  ready_to_visit: "Ready to visit",
  visited: "Visited",
  closed: "Closed",
  dropped: "Dropped",
  bought: "Bought",
};

/** Tone per status → CSS classes. */
export const STATUS_TONE: Record<StatusKey, string> = {
  new: "bg-surface-2 text-muted",
  to_contact: "bg-accent-bg text-accent",
  contacted: "bg-accent-bg text-accent",
  talking: "bg-warn-bg text-warn",
  ready_to_visit: "bg-good-bg text-good",
  visited: "bg-good-bg text-good",
  closed: "bg-surface-2 text-muted",
  dropped: "bg-bad-bg text-bad",
  bought: "bg-good-bg text-good",
};

export const VERDICTS = [
  { value: "up", emoji: "👍", label: "Like" },
  { value: "maybe", emoji: "🤔", label: "Maybe" },
  { value: "down", emoji: "👎", label: "No" },
] as const;
export type VerdictKey = (typeof VERDICTS)[number]["value"];
export const VERDICT_EMOJI: Record<string, string> = { up: "👍", maybe: "🤔", down: "👎" };

export const OPTION_LABEL: Record<string, string> = {
  pano: "Panoramic roof",
  pano_opening: "Opening pano",
  power_tailgate: "Power tailgate",
  electric_seats: "Electric seats",
  memory_seats: "Memory seats",
  heated_seats: "Heated seats",
  ventilated_seats: "Ventilated seats",
  premium_audio: "Premium audio",
  hud: "Head-up display",
  camera_360: "360° camera",
  adaptive_cruise: "Adaptive cruise",
  heat_pump: "Heat pump",
  towbar: "Towbar",
  matrix_led: "Matrix LED",
  keyless: "Keyless",
  massage_seats: "Massage seats",
  rear_recline: "Rear recline",
  air_suspension: "Air suspension",
  adaptive_dampers: "Adaptive dampers",
  sunroof: "Sunroof",
  parking_sensors: "Parking sensors",
  rear_camera: "Rear camera",
  apple_carplay: "CarPlay / Android Auto",
  navigation: "Navigation",
  leather: "Leather",
};

export function optionLabel(key: string): string {
  return OPTION_LABEL[key] ?? humanKey(key);
}

export const SOURCE_LABEL: Record<string, string> = {
  ad_text: "ad text",
  ad_spec: "ad spec",
  photo: "photo",
  vin_pr_code: "VIN PR code",
  vin_decoder: "VIN decoder",
  seller_said: "seller said",
  inspection: "inspection",
  agent_inference: "agent guess",
  owner: "owner",
};

/** Evidence source label; `owner` shows the owner's name. */
export function sourceLabel(src: string | null | undefined, ownerName: string): string | null {
  if (!src) return null;
  if (src === "owner") return ownerName;
  return SOURCE_LABEL[src] ?? src;
}

export const SELLER_TYPES = ["private", "dealer", "reseller", "unknown"] as const;

export function optionMark(v: string | undefined | null): { sym: string; cls: string; word: string } {
  if (v === "yes") return { sym: "✓", cls: "text-good", word: "yes" };
  if (v === "no") return { sym: "✗", cls: "text-bad", word: "no" };
  return { sym: "?", cls: "text-muted", word: "unknown" };
}

export function humanKey(k: string): string {
  const s = k.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Import provenance pointers ("outreach: confirmed.km", "picker:") say nothing to a reader. */
export function readableRef(ref: string | null | undefined): string | null {
  if (!ref) return null;
  const r = ref.trim();
  if (/^[\w-]+:\s*((confirmed|facts)\.[\w.]+|[\w.]*)$/.test(r)) return null;
  return r.replace(/^[\w-]+:\s*(?:confirmed|facts)\.[\w.]+\s*[·;,-]\s*/, "");
}

export type OptionState = "yes" | "no" | "unknown";
export interface IconOption { key: string; label: string; state: OptionState; info: string }

/** State + "Electric seats: yes · ad text" for each icon key; a missing row is unknown, never no. */
export function iconOptions(
  keys: string[],
  values: Record<string, string | undefined | null>,
  sources: Record<string, string | undefined | null> = {},
  ownerName = "owner",
): IconOption[] {
  return keys.map((key) => {
    const label = optionLabel(key);
    const v = values[key];
    const state: OptionState = v === "yes" || v === "no" ? v : "unknown";
    const src = state !== "unknown" ? sourceLabel(sources[key], ownerName) : null;
    return { key, label, state, info: `${label}: ${optionMark(state).word}${src ? ` · ${src}` : ""}` };
  });
}

export const FUEL_LABEL: Record<string, string> = {
  bev: "Electric",
  phev: "Plug-in hybrid",
  hev: "Hybrid",
  mhev: "Mild hybrid",
  petrol: "Petrol",
  diesel: "Diesel",
  lpg: "LPG",
  cng: "CNG",
  hydrogen: "Hydrogen",
};

export interface PowertrainLike {
  fuel?: string | null;
  battery_net_kwh?: number | null;
  battery_gross_kwh?: number | null;
  engine_cc?: number | null;
  gearbox?: string | null;
  wltp_range_km?: number | null;
  wltp_consumption?: number | null;
  co2_g_km?: number | null;
}

const hasBattery = (f: string | null | undefined) => f === "bev" || f === "phev";
const hasEngine = (f: string | null | undefined) => !!f && f !== "bev" && f !== "unknown";

/** Engine size the way ads say it: 1598 cc → "1.6 l". */
export function engineLitres(cc: number | null | undefined): string | null {
  return cc ? `${(Math.round(cc / 100) / 10).toFixed(1)} l` : null;
}

/** One short token for list cards: "77 kWh" (BEV), "1.6 l PHEV 13 kWh", "2.0 l diesel auto". */
export function powertrainShort(pt: PowertrainLike | null | undefined): string | null {
  if (!pt) return null;
  const f = pt.fuel ?? null;
  const kwh = pt.battery_net_kwh ?? pt.battery_gross_kwh ?? null;
  if (f === "bev") return kwh ? `${kwh} kWh` : "EV";
  const parts = [
    engineLitres(pt.engine_cc),
    f && f !== "unknown" ? (f === "petrol" || f === "diesel" ? f : f.toUpperCase()) : null,
    hasBattery(f) && kwh ? `${kwh} kWh` : null,
    pt.gearbox === "automatic" ? "auto" : pt.gearbox === "manual" ? "manual" : null,
  ].filter(Boolean);
  if (!f && kwh) parts.push(`${kwh} kWh`);
  return parts.length ? parts.join(" ") : null;
}

/** Health facts worth showing next to the powertrain: battery for EVs, engine wear for combustion. */
export const HEALTH_FACTS: Record<"battery" | "engine", string[]> = {
  battery: ["battery_soh", "soh", "battery_warranty"],
  engine: ["timing_belt", "dpf", "compression", "clutch", "oil_consumption"],
};

/** Spec rows for the car page's powertrain block, by fuel. Rows with no value are dropped. */
export function powertrainRows(pt: PowertrainLike | null | undefined, facts: { key?: string; value?: string }[] = []): [string, string][] {
  const p = pt ?? {};
  const f = p.fuel ?? null;
  const rows: [string, string | null][] = [["Fuel", f && f !== "unknown" ? FUEL_LABEL[f] ?? f : null]];
  const battery = hasBattery(f) || (!f && (p.battery_net_kwh || p.battery_gross_kwh));
  const engine = hasEngine(f) && f !== "bev";
  if (battery) {
    const b = [p.battery_net_kwh && `${p.battery_net_kwh} net`, p.battery_gross_kwh && `${p.battery_gross_kwh} gross`].filter(Boolean).join(" / ");
    rows.push(["Battery", b ? `${b} kWh` : null]);
    rows.push(["Range", p.wltp_range_km ? `${p.wltp_range_km} km WLTP` : null]);
  }
  if (engine) rows.push(["Engine", engineLitres(p.engine_cc)]);
  if (p.gearbox && p.gearbox !== "unknown") rows.push(["Gearbox", p.gearbox]);
  if (p.wltp_consumption) rows.push(["Consumption", f === "bev" ? `${p.wltp_consumption} kWh/100 km` : `${p.wltp_consumption} l/100 km`]);
  if (p.co2_g_km != null && f !== "bev") rows.push(["CO₂", `${p.co2_g_km} g/km`]);
  const healthKeys = [...(battery ? HEALTH_FACTS.battery : []), ...(engine ? HEALTH_FACTS.engine : [])];
  for (const k of healthKeys) {
    const fact = facts.find((x) => x.key === k);
    if (fact?.value) rows.push([k === "soh" || k === "battery_soh" ? "Battery health" : humanKey(k), fact.value]);
  }
  return rows.filter((r): r is [string, string] => Boolean(r[1]));
}
