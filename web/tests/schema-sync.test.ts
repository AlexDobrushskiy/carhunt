import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The TS types must match cardb's OpenAPI contract; skipped where cardb/ is not checked out (web-only branch).
const spec = resolve(__dirname, "../../cardb/api/openapi.yaml");
const committed = resolve(__dirname, "../src/lib/cardb-schema.ts");

describe.skipIf(!existsSync(spec))("cardb schema", () => {
  it("src/lib/cardb-schema.ts is regenerated from cardb/api/openapi.yaml (npm run gen:api)", () => {
    const out = join(mkdtempSync(join(tmpdir(), "carhunt-schema-")), "schema.ts");
    const bin = resolve(__dirname, "../node_modules/.bin/openapi-typescript");
    const r = spawnSync(bin, [spec, "-o", out], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);
    expect(readFileSync(out, "utf8")).toBe(readFileSync(committed, "utf8"));
  }, 30_000);
});
