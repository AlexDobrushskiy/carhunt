// Throwaway local stack for e2e: cardb on a temp data dir + this web, both on 127.0.0.1, synthetic seed data.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(WEB, "..");

export const OWNER = "Sam";
export const VIEWER = "Kim";
export const HOME_CITY = "Lisbon";

/** Fail closed: the suite only ever talks to loopback. */
export function assertLocal(url: string) {
  const host = new URL(url).hostname;
  if (!["127.0.0.1", "localhost", "::1", "[::1]"].includes(host)) throw new Error(`e2e refuses non-local URL ${url}`);
}

function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const s = createServer();
    s.once("error", fail);
    s.listen(0, "127.0.0.1", () => {
      const port = (s.address() as { port: number }).port;
      s.close(() => ok(port));
    });
  });
}

/** CARDB_BIN, else a build of ../cardb (Go), else `cardb` on PATH. */
function cardbBin(tmp: string): string {
  if (process.env.CARDB_BIN) return process.env.CARDB_BIN;
  if (existsSync(join(REPO, "cardb", "go.mod"))) {
    const out = join(tmp, "cardb");
    const r = spawnSync("go", ["build", "-tags", "nodynamic", "-o", out, "./cmd/cardb"], { cwd: join(REPO, "cardb"), stdio: "inherit" });
    if (r.status === 0) return out;
    throw new Error("go build of ../cardb failed (set CARDB_BIN to a built cardb)");
  }
  if (spawnSync("cardb", ["version"]).status === 0) return "cardb";
  throw new Error("no cardb: set CARDB_BIN, or run from a checkout with cardb/ and Go installed");
}

async function waitFor(url: string, proc: ChildProcess, what: string, timeoutMs = 30_000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (proc.exitCode != null) throw new Error(`${what} exited with ${proc.exitCode}`);
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`${what} not up at ${url} after ${timeoutMs} ms`);
}

// Synthetic buyer profile: owner + one viewer, tiers by model, one must-have option.
const CONFIG = `owner:
  name: ${OWNER}
  tz: Europe/Berlin
  home: {city: ${HOME_CITY}, country: PT, lat: 38.72, lon: -9.14}
search:
  countries: [PT, ES, DE]
  price: {max_eur: 60000, gross: true}
  year_min: 2018
  km_max: 200000
  models:
    - {make: Examplo, model: Voltara, tier: 1}
    - {make: Examplo, model: Ampera X, tier: 2}
  default_tier: 3
  queue_default_tiers: [1, 2]
  must_have: [electric_seats]
  options_wanted: {electric_seats: 3, towbar: 2, pano: 1}
cardb:
  users:
    - {name: ${VIEWER}, role: viewer}
`;

export interface Seeded {
  bev: number;
  ice: number;
  queueA: number;
  queueB: number;
}

export interface Stack {
  web: string;
  cardb: string;
  seedToken: string;
  tokens: string[];
  seeded: Seeded;
  stop: () => Promise<void>;
}

export async function startStack(): Promise<Stack> {
  const tmp = mkdtempSync(join(tmpdir(), "carhunt-web-e2e-"));
  const procs: ChildProcess[] = [];
  let built = false;
  const stop = async () => {
    for (const p of procs) if (p.exitCode == null) p.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 300));
    rmSync(tmp, { recursive: true, force: true });
    // dist/ holds Astro's per-build server key, which secret scanners (gitleaks dir) flag.
    if (built) rmSync(join(WEB, "dist"), { recursive: true, force: true });
  };
  try {
    const bin = cardbBin(tmp);
    writeFileSync(join(tmp, "config.yaml"), CONFIG);
    const tok = () => randomBytes(18).toString("hex");
    const tokens = { [OWNER]: tok(), [VIEWER]: tok(), e2e: tok() };
    const dbPort = await freePort();
    const cardb = `http://127.0.0.1:${dbPort}`;
    // Only what cardb needs: no inherited CARDB_*/CARHUNT_* from the developer's shell can point it at real data.
    const dbEnv = {
      PATH: process.env.PATH ?? "",
      HOME: tmp,
      CARHUNT_HOME: tmp,
      CARHUNT_CONFIG: join(tmp, "config.yaml"),
      CARDB_DATA_DIR: join(tmp, "data"),
      CARDB_LISTEN: `127.0.0.1:${dbPort}`,
      CARDB_TOKENS: Object.entries(tokens).map(([n, t]) => `${n}:${t}`).join(","),
    };
    // Request logs go to a file in the temp dir (E2E_VERBOSE=1 shows them).
    const out = process.env.E2E_VERBOSE ? "inherit" : "ignore";
    const db = spawn(bin, ["serve"], { env: dbEnv, stdio: ["ignore", out, "inherit"] });
    procs.push(db);
    await waitFor(`${cardb}/healthz`, db, "cardb");

    const seeded = await seed(cardb, tokens.e2e);

    if (!process.env.E2E_SKIP_BUILD) {
      const b = spawnSync("npm", ["run", "build"], { cwd: WEB, stdio: "inherit" });
      built = true;
      if (b.status !== 0) throw new Error("npm run build failed");
    }
    const webPort = await freePort();
    const web = `http://127.0.0.1:${webPort}`;
    const webProc = spawn(process.execPath, ["./dist/server/entry.mjs"], {
      cwd: WEB,
      env: {
        PATH: process.env.PATH ?? "",
        HOST: "127.0.0.1",
        PORT: String(webPort),
        NODE_ENV: "production",
        CARDB_URL: cardb,
        CARDB_WEB_TOKENS: `${OWNER}:${tokens[OWNER]},${VIEWER}:${tokens[VIEWER]}`,
      },
      stdio: ["ignore", "inherit", "inherit"],
    });
    procs.push(webProc);
    await waitFor(`${web}/health`, webProc, "web");
    assertLocal(web);
    assertLocal(cardb);
    return { web, cardb, seedToken: tokens.e2e, tokens: Object.values(tokens), seeded, stop };
  } catch (e) {
    await stop();
    throw e;
  }
}

async function call<T>(cardb: string, token: string, method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${cardb}/api/v1${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`seed ${method} ${path}: ${r.status} ${text}`);
  return (text ? JSON.parse(text) : null) as T;
}

async function upsert(cardb: string, token: string, body: Record<string, unknown>): Promise<number> {
  return (await call<{ car_id: number }>(cardb, token, "POST", "/listings/upsert", body)).car_id;
}

async function addPhoto(cardb: string, token: string, car: number, file: string, caption: string) {
  const form = new FormData();
  form.set("file", new Blob([readFileSync(join(WEB, "e2e", "fixtures", file))], { type: "image/jpeg" }), file);
  form.set("caption", caption);
  form.set("source", "ad");
  const r = await fetch(`${cardb}/api/v1/cars/${car}/photos`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
  if (!r.ok) throw new Error(`seed photo: ${r.status} ${await r.text()}`);
}

/** Synthetic cars only: example.invalid URLs, SYN VINs, 555 phones. */
async function seed(cardb: string, token: string): Promise<Seeded> {
  const bev = await upsert(cardb, token, {
    url: "https://example.invalid/ads/bev-1",
    site: "example-market",
    make: "Examplo",
    model: "Voltara",
    variant: "Long Range",
    reg_date: "2022-05",
    km: 24000,
    power_kw: 150,
    drive: "rwd",
    powertrain: { fuel: "bev", battery_net_kwh: 77, battery_gross_kwh: 82, wltp_range_km: 520, wltp_consumption: 16.5 },
    country: "PT",
    city: "Example City",
    distance_km: 120,
    vin: "SYN0000000000E2E1",
    price: 31900,
    status: "talking",
    summary: "Synthetic BEV for e2e",
    seller: { name: "Example Dealer", type: "dealer", city: "Example City", contacts: [{ kind: "phone", value: "+351 555 010 203" }] },
    options: { electric_seats: { value: "yes", source: "seller_said" }, towbar: { value: "no", source: "ad_spec" } },
    facts: { battery_soh: { value: "95 % (certificate)", source: "seller_said" } },
  });
  await addPhoto(cardb, token, bev, "synthetic-1.jpg", "front");
  await addPhoto(cardb, token, bev, "synthetic-2.jpg", "side");
  await call(cardb, token, "PATCH", `/cars/${bev}`, { needs_owner: true, needs_owner_reason: "Seller asks for a call slot" });

  const ice = await upsert(cardb, token, {
    url: "https://example.invalid/ads/ice-1",
    site: "example-market",
    make: "Examplo",
    model: "Dieselo",
    variant: "2.0 TD",
    reg_date: "2020-03",
    km: 61000,
    power_kw: 110,
    drive: "fwd",
    powertrain: { fuel: "diesel", engine_cc: 1968, gearbox: "automatic", wltp_consumption: 5.2, co2_g_km: 136 },
    country: "ES",
    city: "Example Town",
    price: 18500,
    status: "new",
    facts: { timing_belt: { value: "changed 2024", source: "seller_said" } },
  });
  await addPhoto(cardb, token, ice, "synthetic-3.jpg", "front");

  const queueA = await upsert(cardb, token, {
    url: "https://example.invalid/ads/bev-2",
    make: "Examplo",
    model: "Voltara",
    variant: "Standard",
    reg_date: "2023-01",
    km: 15000,
    powertrain: { fuel: "bev", battery_net_kwh: 58 },
    country: "DE",
    price: 29900,
    status: "new",
  });
  const queueB = await upsert(cardb, token, {
    url: "https://example.invalid/ads/bev-3",
    make: "Examplo",
    model: "Ampera X",
    reg_date: "2021-09",
    km: 40000,
    powertrain: { fuel: "bev", battery_net_kwh: 64 },
    country: "PT",
    price: 24900,
    status: "new",
  });
  return { bev, ice, queueA, queueB };
}
