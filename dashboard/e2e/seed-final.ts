import { execSync } from "node:child_process";

export function reseedFinalRound() {
  execSync("docker exec -w /work tanaghom-gateapi python gates/e2e_final_seed.py", { stdio: "ignore" });
}
