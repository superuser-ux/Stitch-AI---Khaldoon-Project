import { execSync } from "node:child_process";

// #175 — isolated RSCH round with an OPEN khal-only schedule_review gate (the not-assigned UX fixture).
export function reseedScheduleRound() {
  execSync("docker exec -w /work tanaghom-gateapi python gates/e2e_schedule_seed.py", { stdio: "ignore" });
}
