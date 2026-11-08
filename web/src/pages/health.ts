import type { APIRoute } from "astro";

// Container liveness of the web itself (cardb has its own /healthz).
export const GET: APIRoute = () => new Response('{"ok":true}', { headers: { "Content-Type": "application/json" } });
