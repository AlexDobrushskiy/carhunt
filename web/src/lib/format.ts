const eur = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 0 });

/** Rounded metric horsepower (PS), matching the API hp filters. */
export function power(kw: number | null | undefined): string {
  return kw == null ? "—" : `${Math.round(kw * 1.36)} hp`;
}

export function price(v: number | null | undefined): string {
  return v == null ? "—" : eur.format(v);
}

export function km(v: number | null | undefined): string {
  if (v == null) return "? km";
  return v >= 1000 ? `${int.format(Math.round(v / 1000))}k km` : `${int.format(v)} km`;
}

/** "120 km to Lisbon"; an estimate (great-circle × road factor) gets "≈". */
export function distance(d: number | null | undefined, source: string | null | undefined, to?: string): string | null {
  if (d == null) return null;
  return `${source === "estimate" ? "≈" : ""}${int.format(d)} km${to ? ` to ${to}` : ""}`;
}

export function num(v: number | null | undefined): string {
  return v == null ? "—" : int.format(v);
}

/** ISO-2 → flag emoji (regional indicator letters); anything else passes through. */
export function flag(country: string | null | undefined): string {
  if (!country) return "";
  const c = country.trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(c)) return country;
  return String.fromCodePoint(...[...c].map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65));
}

/** Accepts unix seconds, unix ms or an ISO string. */
export function toDate(ts: number | string | null | undefined): Date | null {
  if (ts == null || ts === "") return null;
  if (typeof ts === "number") return new Date(ts < 1e12 ? ts * 1000 : ts);
  const d = new Date(ts);
  return isNaN(d.getTime()) ? null : d;
}

// Times show in the owner's zone (profile owner.tz), whatever zone the server runs in.
const fmts = new Map<string, { day: Intl.DateTimeFormat; time: Intl.DateTimeFormat; year: Intl.DateTimeFormat; long: Intl.DateTimeFormat }>();
function fmt(tz: string) {
  let f = fmts.get(tz);
  if (!f) {
    f = {
      day: new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short" }),
      time: new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit" }),
      year: new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "numeric", month: "short", year: "numeric" }),
      long: new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "long", day: "numeric", month: "long" }),
    };
    fmts.set(tz, f);
  }
  return f;
}

export function when(ts: number | string | null | undefined, tz = "UTC", now = new Date()): string {
  const d = toDate(ts);
  if (!d) return "";
  const f = fmt(tz);
  const sameYear = d.getFullYear() === now.getFullYear();
  return `${sameYear ? f.day.format(d) : f.year.format(d)} ${f.time.format(d)}`;
}

/** "Saturday 8 November": chat day separators. */
export function dayLong(ts: number | string | null | undefined, tz = "UTC"): string {
  const d = toDate(ts);
  return d ? fmt(tz).long.format(d) : "";
}

export function ago(ts: number | string | null | undefined, tz = "UTC", now = new Date()): string {
  const d = toDate(ts);
  if (!d) return "";
  const s = Math.round((now.getTime() - d.getTime()) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d`;
  return fmt(tz).year.format(d);
}

/** "2023-07" / "2023-07-14" → "07/2023"; a bare year passes through. */
export function regDate(v: string | number | null | undefined): string {
  if (v == null || v === "") return "";
  const m = String(v).match(/^(\d{4})-(\d{2})/);
  return m ? `${m[2]}/${m[1]}` : String(v);
}
