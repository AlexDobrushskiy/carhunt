// Who is looking: picked from the server-side token map, never from a token in the browser.
import type { Identity } from "./env";

export const COOKIE = "carhunt_user";

export interface Viewer {
  /** Token name = cardb user name = author of every write. Empty when no tokens are configured. */
  name: string;
  token: string;
  /** Other names the picker offers (empty when pinned by a proxy header or only one identity). */
  choices: string[];
  /** Pinned by CARDB_WEB_USER_HEADER: the picker is hidden. */
  locked: boolean;
}

export interface ResolveInput {
  ids: Identity[];
  cookie?: string | null;
  /** Value of the trusted header when CARDB_WEB_USER_HEADER is configured; undefined when not configured. */
  header?: string | null;
  ownerName?: string | null;
}

/** null = a trusted header is configured but names nobody we hold a token for (→ 403). */
export function resolveViewer({ ids, cookie, header, ownerName }: ResolveInput): Viewer | null {
  if (header !== undefined) {
    const id = ids.find((x) => x.name === header);
    return id ? { ...id, choices: [], locked: true } : null;
  }
  if (!ids.length) return { name: "", token: "", choices: [], locked: false };
  const id = ids.find((x) => x.name === cookie) ?? ids.find((x) => x.name === ownerName) ?? ids[0];
  return { ...id, choices: ids.length > 1 ? ids.map((x) => x.name) : [], locked: false };
}

/** Same-origin path to go back to after switching identity; anything else → "/". */
export function safeBack(v: string | null | undefined): string {
  if (!v) return "/";
  try {
    const u = new URL(v, "http://x");
    if (v.startsWith("/") && !v.startsWith("//")) return u.pathname + u.search;
    return /^https?:/.test(v) ? u.pathname + u.search : "/";
  } catch {
    return "/";
  }
}
