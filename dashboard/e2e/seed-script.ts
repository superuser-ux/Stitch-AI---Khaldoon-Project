import { execSync } from "node:child_process";

export function reseedScriptRound() {
  execSync("docker exec -w /work tanaghom-gateapi python gates/e2e_script_seed.py", { stdio: "ignore" });
}
