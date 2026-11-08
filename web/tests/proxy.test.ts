import { describe, expect, it } from "vitest";
import { isAllowed, sameOrigin, withAuthor } from "@/lib/proxy";

describe("write proxy", () => {
  it("allows only the UI's writes", () => {
    expect(isAllowed("PUT", "cars/12/verdict")).toBe(true);
    expect(isAllowed("DELETE", "cars/porto-q4/verdict")).toBe(true);
    expect(isAllowed("POST", "cars/12/notes")).toBe(true);
    expect(isAllowed("PATCH", "notes/5")).toBe(true);
    expect(isAllowed("POST", "duplicates/3/reject")).toBe(true);
    expect(isAllowed("PUT", "cars/12/good-deal")).toBe(true);
    expect(isAllowed("DELETE", "cars/12/good-deal")).toBe(false);
    expect(isAllowed("POST", "cars/12/good-deal")).toBe(false);
    expect(isAllowed("POST", "listings/upsert")).toBe(false);
    expect(isAllowed("POST", "messages")).toBe(false);
    expect(isAllowed("DELETE", "cars/12")).toBe(false);
    expect(isAllowed("PUT", "cars/12/../../x/verdict")).toBe(false);
    expect(isAllowed("PUT", "cars/../verdict")).toBe(false);
    expect(isAllowed("PUT", "cars//verdict")).toBe(false);
  });

  it("lets a viewer set only their own verdict", () => {
    expect(isAllowed("PUT", "cars/12/verdict", "viewer")).toBe(true);
    expect(isAllowed("DELETE", "cars/12/verdict", "viewer")).toBe(true);
    expect(isAllowed("POST", "cars/12/notes", "viewer")).toBe(false);
    expect(isAllowed("POST", "cars/12/status", "viewer")).toBe(false);
    expect(isAllowed("PATCH", "cars/12", "viewer")).toBe(false);
    expect(isAllowed("POST", "cars/12/status", "other")).toBe(true);
  });

  it("stamps the viewer as author over any client value, and as user on verdicts", () => {
    expect(JSON.parse(withAuthor('{"value":"up","author":"agent","user":"sam"}', "PUT", "kim", "cars/1/verdict")!)).toEqual({ value: "up", author: "kim", user: "kim" });
    expect(JSON.parse(withAuthor('{"text":"x","author":"agent"}', "POST", "sam", "cars/1/notes")!)).toEqual({ text: "x", author: "sam" });
    expect(JSON.parse(withAuthor("", "POST", "sam")!)).toEqual({ author: "sam" });
    expect(JSON.parse(withAuthor('{"author":"x"}', "POST", "")!)).toEqual({});
    expect(withAuthor("", "DELETE", "sam")).toBeUndefined();
    expect(() => withAuthor("{bad", "PUT", "sam")).toThrow();
  });

  it("refuses cross-site writes", () => {
    const h = (o: Record<string, string>) => new Headers(o);
    expect(sameOrigin(h({ Origin: "http://127.0.0.1:4321", Host: "127.0.0.1:4321" }))).toBe(true);
    expect(sameOrigin(h({ Origin: "https://cars.example.com", Host: "web:4321", "X-Forwarded-Host": "cars.example.com" }))).toBe(true);
    expect(sameOrigin(h({ Origin: "https://evil.example", Host: "127.0.0.1:4321" }))).toBe(false);
    expect(sameOrigin(h({ Origin: "null", Host: "127.0.0.1:4321" }))).toBe(false);
    expect(sameOrigin(h({ "Sec-Fetch-Site": "cross-site" }))).toBe(false);
    expect(sameOrigin(h({}))).toBe(true);
  });
});
