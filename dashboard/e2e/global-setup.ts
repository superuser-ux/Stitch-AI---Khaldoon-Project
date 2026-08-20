import { reseed } from "./seed";

// First seed before the suite. Each spec also reseeds per-test (beforeEach) for isolation.
export default async function globalSetup() {
  console.log("[e2e] seeding RE2E…");
  reseed();
}
