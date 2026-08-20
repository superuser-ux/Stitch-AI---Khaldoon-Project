#!/usr/bin/env bash

set -euo pipefail

target="${1:-registry.npmjs.org}"

echo "Codex network check"
echo "cwd: $(pwd)"
echo "target: ${target}"
echo

echo "Sandbox environment"
env | grep -E '^CODEX_SANDBOX|^CODEX_SANDBOX_NETWORK_DISABLED=' || true
echo

echo "Node DNS lookup"
node -e "require('node:dns').lookup(process.argv[1],(e,a,f)=>{if(e){console.error('lookup_failed', e.code || e.message); process.exit(2)} console.log('lookup_ok', a, f)})" "${target}" || true
echo

if [[ "${CODEX_SANDBOX_NETWORK_DISABLED:-0}" == "1" ]]; then
  cat <<'EOF'
Result
- This shell is running with network-disabled sandboxing.
- DNS failures here are likely execution-policy failures, not host DNS failures.

Recommended next step
- Restart from a host terminal with:
  codex -C /Users/Kay/Dev/tanaghom -s danger-full-access -a on-request --search

Fallback
- Run networked install commands in the host terminal, then return to Codex.
EOF
else
  cat <<'EOF'
Result
- This shell does not report network-disabled sandboxing.
- If lookups still fail, continue with host DNS, proxy, VPN, firewall, or CA diagnostics.
EOF
fi
