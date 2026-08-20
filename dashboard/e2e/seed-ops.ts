import { execSync } from "node:child_process";

export function reseedOpsRounds() {
  execSync("docker exec -w /work tanaghom-gateapi python gates/e2e_ops_seed.py", { stdio: "ignore" });
}
