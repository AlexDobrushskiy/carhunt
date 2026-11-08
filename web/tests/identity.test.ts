import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { identities, parseTokens } from "@/lib/env";
import { resolveViewer, safeBack } from "@/lib/identity";

describe("token map", () => {
  it("parses name:token lists in any separator, first colon splits", () => {
    expect(parseTokens("sam:aaa, kim:bb:cc\nbad\n:x\nlee:")).toEqual([
      { name: "sam", token: "aaa" },
      { name: "kim", token: "bb:cc" },
    ]);
    expect(parseTokens("sam:a sam:b")).toEqual([{ name: "sam", token: "a" }]);
  });

  it("reads the env var, else the file", () => {
    const dir = mkdtempSync(join(tmpdir(), "carhunt-web-"));
    const file = join(dir, "tokens");
    writeFileSync(file, "sam:filetok\n");
    expect(identities({ CARDB_WEB_TOKENS_FILE: file })).toEqual([{ name: "sam", token: "filetok" }]);
    expect(identities({ CARDB_WEB_TOKENS: "kim:envtok", CARDB_WEB_TOKENS_FILE: file })).toEqual([{ name: "kim", token: "envtok" }]);
  });
});

describe("viewer", () => {
  const ids = [
    { name: "kim", token: "t1" },
    { name: "sam", token: "t2" },
  ];
  it("cookie, else the owner, else the first identity", () => {
    expect(resolveViewer({ ids, cookie: "kim", ownerName: "sam" })).toMatchObject({ name: "kim", token: "t1", choices: ["kim", "sam"], locked: false });
    expect(resolveViewer({ ids, cookie: "nobody", ownerName: "sam" })?.name).toBe("sam");
    expect(resolveViewer({ ids, ownerName: "lee" })?.name).toBe("kim");
    expect(resolveViewer({ ids: [ids[0]], ownerName: "kim" })?.choices).toEqual([]);
    expect(resolveViewer({ ids: [], ownerName: "kim" })).toEqual({ name: "", token: "", choices: [], locked: false });
  });
  it("a trusted proxy header pins the identity and hides the picker", () => {
    expect(resolveViewer({ ids, cookie: "kim", header: "sam" })).toMatchObject({ name: "sam", locked: true, choices: [] });
    expect(resolveViewer({ ids, header: "" })).toBeNull();
    expect(resolveViewer({ ids, header: "mallory" })).toBeNull();
  });
  it("only goes back to same-origin paths", () => {
    expect(safeBack("/cars/3?x=1")).toBe("/cars/3?x=1");
    expect(safeBack("http://127.0.0.1:4323/queue?all=1")).toBe("/queue?all=1");
    expect(safeBack("//evil.example/x")).toBe("/");
    expect(safeBack("javascript:alert(1)")).toBe("/");
    expect(safeBack(null)).toBe("/");
  });
});
