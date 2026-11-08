// Photo proxy: /photos/<id>?size=thumb|medium|full → cardb with the viewer's token (the browser never holds one).
import type { APIRoute } from "astro";
import { apiRaw } from "@/lib/http";

const SIZES = new Set(["thumb", "medium", "full"]);

export const GET: APIRoute = async ({ params, url, locals }) => {
  const id = params.id ?? "";
  if (!/^\d+$/.test(id)) return new Response("bad id", { status: 400 });
  const size = url.searchParams.get("size") ?? "full";
  if (!SIZES.has(size)) return new Response("bad size", { status: 400 });
  const upstream = await apiRaw({ token: locals.viewer.token, author: "" }, `/api/v1/photos/${id}?size=${size}`);
  if (!upstream.ok || !upstream.body) return new Response(null, { status: upstream.status === 404 ? 404 : 502 });
  const headers: Record<string, string> = {
    "Content-Type": upstream.headers.get("Content-Type") ?? "image/jpeg",
    // Photo bytes per id never change.
    "Cache-Control": "private, max-age=31536000, immutable",
  };
  const len = upstream.headers.get("Content-Length");
  if (len) headers["Content-Length"] = len;
  return new Response(upstream.body, { status: 200, headers });
};
