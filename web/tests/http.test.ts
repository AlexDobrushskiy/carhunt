import { afterEach, describe, expect, it } from "vitest";
import { api, setFetchForTesting } from "@/lib/http";
import { cardbUrl, DEFAULT_CARDB_URL } from "@/lib/env";

describe("api client", () => {
  afterEach(() => {
    setFetchForTesting((...a) => fetch(...a));
    delete process.env.CARDB_URL;
  });

  it("defaults to a local cardb", () => {
    delete process.env.CARDB_URL;
    expect(cardbUrl()).toBe(DEFAULT_CARDB_URL);
    expect(new URL(DEFAULT_CARDB_URL).hostname).toBe("127.0.0.1");
  });

  it("sends the caller's token always and X-Author only on writes", async () => {
    process.env.CARDB_URL = "http://cardb:8484/";
    const seen: { url: string; headers: Record<string, string> }[] = [];
    setFetchForTesting(async (url, init) => {
      seen.push({ url: String(url), headers: (init?.headers ?? {}) as Record<string, string> });
      return new Response('{"ok":true}', { status: 200 });
    });
    const who = { token: "t0k", author: "sam" };
    await api(who, "/api/v1/stats");
    await api(who, "/api/v1/cars/1/notes", { method: "POST", body: "{}" });
    await api({ token: "", author: "" }, "/api/v1/stats");
    expect(seen[0].url).toBe("http://cardb:8484/api/v1/stats");
    expect(seen[0].headers.Authorization).toBe("Bearer t0k");
    expect(seen[0].headers["X-Author"]).toBeUndefined();
    expect(seen[1].headers["X-Author"]).toBe("sam");
    expect(seen[2].headers.Authorization).toBeUndefined();
  });

  it("raises ApiError with the status on failure", async () => {
    setFetchForTesting(async () => new Response('{"error":"nope"}', { status: 404 }));
    await expect(api({ token: "", author: "" }, "/api/v1/cars/x")).rejects.toMatchObject({ status: 404 });
  });
});
