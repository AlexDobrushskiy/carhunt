// Server-side client for the cardb API. Tokens never reach the browser.
import { cardbUrl } from "./env";

export class ApiError extends Error {
  constructor(public status: number, public body: string, path: string) {
    super(`cardb ${status} on ${path}: ${body.slice(0, 200)}`);
  }
}

let fetchImpl: typeof fetch = (...a) => fetch(...a);
export function setFetchForTesting(f: typeof fetch) {
  fetchImpl = f;
}

export interface Caller {
  token: string;
  /** Author of writes (the viewer's token name); empty = let cardb use the token name. */
  author: string;
}

export function apiRaw(who: Caller, path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {};
  if (who.token) headers.Authorization = `Bearer ${who.token}`;
  if (who.author && method !== "GET" && method !== "HEAD") headers["X-Author"] = who.author;
  Object.assign(headers, init.headers as Record<string, string> | undefined);
  return fetchImpl(cardbUrl() + path, { ...init, headers });
}

export async function api<T>(who: Caller, path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body != null) headers["Content-Type"] = "application/json";
  const res = await apiRaw(who, path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  const text = await res.text();
  if (!res.ok) throw new ApiError(res.status, text, path);
  return (text ? JSON.parse(text) : null) as T;
}

export function qs(params: Record<string, string | number | boolean | string[] | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x));
    else u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}
