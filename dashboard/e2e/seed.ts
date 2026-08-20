import { execSync } from "node:child_process";

// Fast reseed of the isolated RE2E round, reusing the already-running gate API container
// (has deps + the repo mounted at /work). Resets to a clean 3-topic start + opens the topic gate.
export function reseed() {
  execSync("docker exec -w /work tanaghom-gateapi python gates/e2e_seed.py", { stdio: "ignore" });
}
