import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

// #293 §6 + regression for the 11db665 review (P1.2).
//
// At 11db665 preflight honoured PORT while package.json hard-coded `-p 3001`, so a successful
// preflight on an alternate port was disconnected from the process that actually started, and the
// documented `PORT=<free-port> pnpm dev` override silently did nothing. These lock the two ends of
// the contract together: dev/start must ASK the preflight script for the port, and the preflight
// script must resolve it.

const WB = path.resolve(__dirname, "..");
const script = path.join(WB, "scripts", "preflight-port.mjs");

/** Run the preflight script; return exit code + streams instead of throwing. */
function preflight(args: string[], env: Record<string, string> = {}) {
  try {
    const stdout = execFileSync("node", [script, ...args], {
      // PORT is blanked first so the ambient shell cannot leak into these assertions.
      env: { ...process.env, PORT: "", ...env },
      stdio: ["ignore", "pipe", "pipe"],
    }).toString();
    return { code: 0, stdout };
  } catch (e) {
    const err = e as { status: number; stdout?: Buffer; stderr?: Buffer };
    return { code: err.status ?? 1, stdout: err.stdout?.toString() ?? "", stderr: err.stderr?.toString() ?? "" };
  }
}

test("dev and start take their port FROM the preflight script (no hard-coded port)", () => {
  const pkg = JSON.parse(readFileSync(path.join(WB, "package.json"), "utf8"));
  for (const name of ["dev", "start"]) {
    const cmd: string = pkg.scripts[name];
    // Must gate on preflight...
    expect(cmd, `${name} must run the preflight gate`).toContain("scripts/preflight-port.mjs &&");
    // ...and must source the port from it, rather than restating a literal.
    expect(cmd, `${name} must resolve its port via preflight --print`).toContain(
      "-p $(node scripts/preflight-port.mjs --print)",
    );
    expect(cmd, `${name} must not hard-code a port`).not.toMatch(/-p\s+\d+/);
  }
});

test("--print resolves the port that was validated, honouring PORT", () => {
  expect(preflight(["--print"]).stdout.trim()).toBe("3001"); // documented default
  expect(preflight(["--print"], { PORT: "3007" }).stdout.trim()).toBe("3007"); // override is real
});

test("the V1 production port is refused on every path, including --print", () => {
  const gate = preflight([], { PORT: "3000" });
  expect(gate.code, "preflight must refuse V1's port").toBe(1);

  // --print must not be an escape hatch around the refusal.
  const printed = preflight(["--print"], { PORT: "3000" });
  expect(printed.code).toBe(1);
  expect(printed.stdout.trim()).toBe("");
});

test("an occupied port is refused clearly — and nothing is killed", () => {
  // V1 is running on 3000 for this suite; use a port we know is occupied: V2's own.
  const held = preflight([], { PORT: "3001" });
  expect(held.code, "an occupied port must fail closed").toBe(1);
  expect(held.stderr).toContain("already in use");
  // The refusal must name the holder and hand the decision to the operator — never stop it (§6).
  expect(held.stderr).toContain("V2 will NOT stop it");

  // Proof it did not kill the process it found: V2 is still listening.
  const stillUp = preflight([], { PORT: "3001" });
  expect(stillUp.code).toBe(1);
});

test("invalid ports are rejected", () => {
  expect(preflight([], { PORT: "not-a-port" }).code).toBe(2);
  expect(preflight([], { PORT: "70000" }).code).toBe(2);
});
