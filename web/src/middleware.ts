import { defineMiddleware, sequence } from "astro:middleware";
import { cardb } from "@/lib/cardb";
import { identities, userHeader } from "@/lib/env";
import { COOKIE, resolveViewer } from "@/lib/identity";
import { roleOf, uiProfile } from "@/lib/profile";
import { cachedProfile } from "@/lib/profile-cache";

// Utility-class HTML compresses ~18× (a 230-car list: 760 KB → 42 KB); phones on mobile data feel it.
const COMPRESSIBLE = /^(text\/|application\/(json|javascript))/;

const gzip = defineMiddleware(async (ctx, next) => {
  const res = await next();
  const type = res.headers.get("Content-Type") ?? "";
  if (
    !res.body ||
    res.headers.has("Content-Encoding") ||
    !COMPRESSIBLE.test(type) ||
    !/\bgzip\b/.test(ctx.request.headers.get("Accept-Encoding") ?? "")
  ) {
    return res;
  }
  const headers = new Headers(res.headers);
  headers.set("Content-Encoding", "gzip");
  headers.delete("Content-Length");
  headers.append("Vary", "Accept-Encoding");
  return new Response(res.body.pipeThrough(new CompressionStream("gzip")), { status: res.status, statusText: res.statusText, headers });
});

// Viewer + profile + a cardb client bound to the viewer's token, for every page and proxy call.
const who = defineMiddleware(async (ctx, next) => {
  if (ctx.url.pathname === "/health") return next();
  const ids = identities();
  const hdr = userHeader();
  const header = hdr ? ctx.request.headers.get(hdr) ?? "" : undefined;
  // The profile is the same for every token: read it with any identity we hold.
  const raw = await cachedProfile({ token: ids[0]?.token ?? "", author: "" });
  const profile = uiProfile(raw);
  const viewer = resolveViewer({ ids, cookie: ctx.cookies.get(COOKIE)?.value, header, ownerName: profile.ownerName });
  if (!viewer) return new Response("Unknown user", { status: 403 });
  ctx.locals.profile = profile;
  ctx.locals.viewer = { ...viewer, role: roleOf(profile, viewer.name) };
  ctx.locals.db = cardb({ token: viewer.token, author: viewer.name, name: viewer.name }, profile);
  return next();
});

export const onRequest = sequence(gzip, who);
