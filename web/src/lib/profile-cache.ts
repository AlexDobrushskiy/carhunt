// GET /profile, cached per process (it only changes on a cardb restart with a new config).
import { getProfile } from "./cardb";
import { cardbUrl } from "./env";
import type { Caller } from "./http";
import type { Profile } from "./profile";

const TTL_MS = 60_000;
let cache: { url: string; at: number; p: Profile } | null = null;

/** Stale-on-error: a cardb hiccup keeps the last profile; never cached → null (UI falls back to neutral labels). */
export async function cachedProfile(who: Caller, now = Date.now()): Promise<Profile | null> {
  const url = cardbUrl();
  if (cache && cache.url === url && now - cache.at < TTL_MS) return cache.p;
  try {
    const p = await getProfile(who);
    cache = { url, at: now, p };
    return p;
  } catch {
    return cache?.url === url ? cache.p : null;
  }
}

export function resetProfileCacheForTesting() {
  cache = null;
}
