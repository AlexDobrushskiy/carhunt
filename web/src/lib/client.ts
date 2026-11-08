// Browser-side calls to this app's /ui proxy (the proxy adds the token and the author).

export class SendError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function send<T = unknown>(method: string, path: string, body?: unknown): Promise<T | null> {
  const res = await fetch(`/ui/${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    let msg = text;
    try {
      msg = JSON.parse(text).error ?? text;
    } catch {}
    throw new SendError(msg || `HTTP ${res.status}`, res.status);
  }
  return text ? (JSON.parse(text) as T) : null;
}
