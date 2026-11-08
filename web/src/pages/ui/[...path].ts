import type { APIRoute } from "astro";
import { apiRaw, qs } from "@/lib/http";
import { isAllowed, isVerdictPath, sameOrigin, withAuthor } from "@/lib/proxy";
import { isUser } from "@/lib/profile";

const json = (status: number, error: string) =>
  new Response(JSON.stringify({ error }), { status, headers: { "Content-Type": "application/json" } });

export const ALL: APIRoute = async ({ params, request, locals }) => {
  const path = params.path ?? "";
  const method = request.method.toUpperCase();
  const { viewer, profile } = locals;
  if (!sameOrigin(request.headers)) return json(403, "cross-site request refused");
  if (!isAllowed(method, path, viewer.role)) return json(viewer.role === "viewer" ? 403 : 405, "not allowed");
  let body: string | undefined;
  try {
    body = withAuthor(await request.text(), method, viewer.name, path);
  } catch {
    return json(400, "bad JSON");
  }
  // DELETE has no body: name the user in the query so a viewer clears only their own verdict.
  const user = method === "DELETE" && isVerdictPath(path) && isUser(profile, viewer.name) ? qs({ user: viewer.name }) : "";
  const upstream = await apiRaw({ token: viewer.token, author: viewer.name }, `/api/v1/${path}${user}`, {
    method,
    body,
    headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
  });
  const text = await upstream.text();
  return new Response(text || null, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json", "Cache-Control": "no-store" },
  });
};
