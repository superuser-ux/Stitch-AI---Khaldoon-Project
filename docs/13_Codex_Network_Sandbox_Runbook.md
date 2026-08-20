# Codex Network Sandbox Runbook

Date: 2026-07-02
Status: internal ops note

## Purpose

This document explains the recurring "DNS failure inside Codex" issue, how to confirm it quickly, and how to start future sessions in a state that does not block dependency installs or browser tooling.

## Quick Fix In Codex Desktop

If you are working in the Codex Desktop app, check the chat/session access setting first.

On this machine, the root cause was that the session was running in an approval-gated sandboxed mode. Switching the session setting to `Full Access` immediately restored normal DNS and network behavior.

Recommended first action before deeper troubleshooting:

1. Open the current Codex Desktop session settings from the chat box controls.
2. Check the access mode.
3. If it is an approval-gated mode and the task requires installs, browser tooling, or external network access, switch it to `Full Access`.
4. Rerun:

```bash
/Users/Kay/Dev/tanaghom/tools/codex-network-check.sh
```

If the checker passes after that, stop troubleshooting DNS. The issue was session policy.

## Symptom

Inside a Codex-managed shell, commands like these fail:

```bash
pnpm install
curl -I https://registry.npmjs.org
node -e "require('node:dns').lookup('registry.npmjs.org', console.log)"
python -c "import socket; print(socket.getaddrinfo('registry.npmjs.org', 443))"
```

Typical errors:

- `ENOTFOUND`
- `nodename nor servname provided, or not known`
- `Could not resolve host`

## Root Cause

In this repo, the observed failure was not host DNS.

The host terminal resolved external domains correctly, and an unsandboxed Codex command also resolved them correctly. The failure occurred only inside the current Codex desktop thread because the session environment contained:

```bash
CODEX_SANDBOX=seatbelt
CODEX_SANDBOX_NETWORK_DISABLED=1
```

That means the shell was launched in a network-disabled sandbox. The DNS errors are a symptom of sandbox policy, not a real workstation resolver problem.

In practice, for Codex Desktop, the fastest remedy may simply be changing the current session to `Full Access`.

## What We Verified

These checks established the boundary:

1. Host terminal DNS worked.
2. Docker container DNS worked.
3. The same lookup succeeded when rerun outside the Codex sandbox.
4. The sandboxed session had `CODEX_SANDBOX_NETWORK_DISABLED=1`.

Conclusion: this is an execution-mode issue.

## Fast Check

Run this inside the Codex shell:

```bash
env | rg 'CODEX_SANDBOX|NETWORK'
node -e "require('node:dns').lookup('registry.npmjs.org',(e,a,f)=>console.log({code:e&&e.code,address:a,family:f}))"
```

If you see `CODEX_SANDBOX_NETWORK_DISABLED=1` and the lookup fails with `ENOTFOUND`, do not spend time debugging macOS DNS first.

## Recommended Operating Modes

### Mode A: Reliable networked Codex session

Preferred for CLI-started sessions, start Codex from a host terminal with explicit session controls:

```bash
codex -C /Users/Kay/Dev/tanaghom -s danger-full-access -a on-request --search
```

Use this when the task needs:

- package installs
- browser downloads
- live web access
- remote MCP endpoints

Notes:

- `open -a Codex` only opens the app. It does not guarantee the thread will run with network-enabled shell permissions.
- This command is the most reliable path currently verified on this machine.

### Mode A1: Reliable networked Codex Desktop session

Preferred for Desktop-app sessions:

- switch the current session access mode to `Full Access`
- rerun [tools/codex-network-check.sh](/Users/Kay/Dev/tanaghom/tools/codex-network-check.sh)

Use this as the first-line fix before investigating DNS, Tailscale, proxy, or firewall behavior.

### Mode B: Desktop thread with selective escalation

If a desktop thread is already open and sandboxed, keep working there, but rerun networked commands with approval/escalation when needed.

This is acceptable for occasional installs or reachability checks, but it is slower than starting the session in the right mode.

### Mode C: Host-terminal fallback

If a dependency install is blocked only by Codex shell networking, run the install in the host terminal, then return to Codex for implementation and verification.

Use this for:

- `pnpm install`
- `playwright install`
- one-off font or package fetches

## Best-Practice Sequence For Future Work

1. Start Docker first if the repo depends on local services.
2. If using Codex Desktop, verify the session is in `Full Access`.
3. If using Codex CLI, start Codex from the host terminal with explicit sandbox and approval flags.
4. Run `tools/codex-network-check.sh` once at the start of the session.
5. If the script reports sandbox-disabled networking, fix the session mode first instead of pushing through repeated DNS failures.

## Troubleshooting Ladder

Use this order:

1. In Codex Desktop, check whether the session is set to `Full Access`.
2. Check `CODEX_SANDBOX_NETWORK_DISABLED`.
3. Test lookup inside the current Codex shell.
4. Test lookup outside sandbox.
5. Test lookup from the host terminal.
6. Only then investigate VPN, firewall, proxy, DNS server, or custom CA issues.

This order avoids wasting time on the wrong layer.

## Current Repo Guidance

For this project, prefer:

- Codex CLI sessions for network-heavy implementation phases
- desktop threads for review, editing, and light verification
- escalated commands only when a thread is already in progress and restarting would be costly

## When This Is Not A Sandbox Issue

Treat it as real network or DNS trouble only if one of these is true:

- host terminal also fails to resolve the same domains
- unsandboxed Codex commands fail the same way
- Docker containers also fail to resolve public hosts
- proxy, VPN, or corporate gateway rules changed recently

## Related Files

- [README.md](/Users/Kay/Dev/tanaghom/README.md)
- [docs/03_Foundation_Local_Setup.md](/Users/Kay/Dev/tanaghom/docs/03_Foundation_Local_Setup.md)
- [tools/codex-network-check.sh](/Users/Kay/Dev/tanaghom/tools/codex-network-check.sh)
