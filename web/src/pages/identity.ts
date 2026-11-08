import type { APIRoute } from "astro";
import { identities, userHeader } from "@/lib/env";
import { COOKIE, safeBack } from "@/lib/identity";
import { sameOrigin } from "@/lib/proxy";

// "Viewing as" picker: stores a name (not a token) in a cookie; the server maps it to a token.
export const POST: APIRoute = async ({ request, cookies, redirect }) => {
  if (userHeader()) return new Response("Identity is set by the proxy", { status: 403 });
  if (!sameOrigin(request.headers)) return new Response("cross-site request refused", { status: 403 });
  const form = await request.formData();
  const name = String(form.get("user") ?? "");
  if (!identities().some((x) => x.name === name)) return new Response("Unknown user", { status: 400 });
  cookies.set(COOKIE, name, { path: "/", httpOnly: true, sameSite: "lax", maxAge: 365 * 86400 });
  return redirect(safeBack(String(form.get("back") ?? request.headers.get("Referer") ?? "/")), 303);
};
