import { startStack } from "./stack";

// Starts cardb + web on loopback; tests read the URLs and ids from env. Returns the teardown.
export default async function globalSetup() {
  const s = await startStack();
  process.env.E2E_BASE_URL = s.web;
  process.env.E2E_CARDB_URL = s.cardb;
  process.env.E2E_SEED_TOKEN = s.seedToken;
  process.env.E2E_TOKENS = s.tokens.join(",");
  process.env.E2E_SEEDED = JSON.stringify(s.seeded);
  return s.stop;
}
