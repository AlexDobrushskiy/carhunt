// Allowlist for browser → API writes. Everything else is refused.
import type { Role } from "./profile";

const SEG = "[^/]+";
const VERDICT = new RegExp(`^cars/${SEG}/verdict$`);
const RULES: { method: string; re: RegExp; viewer?: boolean }[] = [
  { method: "PUT", re: VERDICT, viewer: true },
  { method: "DELETE", re: VERDICT, viewer: true },
  { method: "POST", re: new RegExp(`^cars/${SEG}/notes$`) },
  { method: "PATCH", re: /^notes\/\d+$/ },
  { method: "DELETE", re: /^notes\/\d+$/ },
  { method: "POST", re: new RegExp(`^cars/${SEG}/status$`) },
  { method: "PUT", re: new RegExp(`^cars/${SEG}/good-deal$`) },
  { method: "PATCH", re: new RegExp(`^cars/${SEG}$`) },
  { method: "POST", re: new RegExp(`^cars/${SEG}/merge$`) },
  { method: "POST", re: /^duplicates\/\d+\/reject$/ },
];

/** Viewers may only set their own verdict (cardb enforces it too; this keeps the 403 local). */
export function isAllowed(method: string, path: string, role: Role = "owner"): boolean {
  if (path.split("/").some((s) => s === ".." || s === "." || s === "")) return false;
  return RULES.some((r) => r.method === method && r.re.test(path) && (role !== "viewer" || r.viewer));
}

export function isVerdictPath(path: string): boolean {
  return VERDICT.test(path);
}

/** Writes from the web UI are always the viewer's: `author` (and `user` on verdicts) are forced. */
export function withAuthor(body: string, method: string, author: string, path = ""): string | undefined {
  if (method === "DELETE") return undefined;
  let obj: Record<string, unknown> = {};
  if (body.trim()) {
    const parsed = JSON.parse(body);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) obj = parsed;
  }
  delete obj.author;
  delete obj.user;
  if (author) obj.author = author;
  if (author && isVerdictPath(path)) obj.user = author;
  return JSON.stringify(obj);
}

/** Cross-site requests are refused: a page elsewhere must not write as the viewer. */
export function sameOrigin(headers: Headers): boolean {
  const origin = headers.get("Origin");
  if (!origin) return headers.get("Sec-Fetch-Site") !== "cross-site";
  const host = headers.get("X-Forwarded-Host") ?? headers.get("Host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
