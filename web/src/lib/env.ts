// Server-only settings, all from env. Defaults target a local cardb.
import { readFileSync } from "node:fs";

export const DEFAULT_CARDB_URL = "http://127.0.0.1:8484";

export interface Identity {
  name: string;
  token: string;
}

export function cardbUrl(env: NodeJS.ProcessEnv = process.env): string {
  return (env.CARDB_URL || DEFAULT_CARDB_URL).replace(/\/+$/, "");
}

/** `name:token` pairs separated by commas, spaces or newlines; the first `:` splits (tokens may contain `:`). */
export function parseTokens(raw: string): Identity[] {
  const out: Identity[] = [];
  for (const part of raw.split(/[\s,]+/)) {
    const i = part.indexOf(":");
    if (i <= 0 || i === part.length - 1) continue;
    const name = part.slice(0, i).trim();
    if (!out.some((x) => x.name === name)) out.push({ name, token: part.slice(i + 1).trim() });
  }
  return out;
}

let cache: { key: string; ids: Identity[] } | null = null;

/** Identities the web may act as: CARDB_WEB_TOKENS, else the file named by CARDB_WEB_TOKENS_FILE (Docker secret). */
export function identities(env: NodeJS.ProcessEnv = process.env): Identity[] {
  const key = `${env.CARDB_WEB_TOKENS ?? ""}\0${env.CARDB_WEB_TOKENS_FILE ?? ""}`;
  if (cache?.key === key) return cache.ids;
  let raw = env.CARDB_WEB_TOKENS ?? "";
  if (!raw && env.CARDB_WEB_TOKENS_FILE) raw = readFileSync(env.CARDB_WEB_TOKENS_FILE, "utf8");
  cache = { key, ids: parseTokens(raw) };
  return cache.ids;
}

/** Optional trusted header set by a reverse proxy (e.g. `Remote-User`); when set it pins the identity. */
export function userHeader(env: NodeJS.ProcessEnv = process.env): string | null {
  return env.CARDB_WEB_USER_HEADER?.trim() || null;
}
