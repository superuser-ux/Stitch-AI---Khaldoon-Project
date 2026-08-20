#!/usr/bin/env bash
#
# demo-preflight.sh — observe-only "safe to demo?" preflight for the Tanaghom stack (#5).
#
# Reports pass/warn/fail for the things that make a live walkthrough look broken, then exits non-zero
# if any demo-BLOCKING condition is confidently detected. It is strictly OBSERVE-ONLY: it never
# restarts a service, recreates a container, edits env/secrets, reconfigures Tailscale, or touches run
# or client-trial data. Safe to run repeatedly.
#
# Severity model:
#   FAIL  — demo-blocking, exits non-zero: dashboard/API unreachable, or the gate API is in WRITER-STUB
#           mode (deterministic offline stub content makes a live review look corrupted — the #5 finding).
#   WARN  — context-dependent, does NOT block a localhost demo: no Tailscale Funnel / public URL, the
#           Telegram bot not running, port drift. Escalate to FAIL with the --require-* flags below when
#           your demo actually needs public access or Telegram.
#   PASS  — checked and healthy.
#
# Exit codes: 0 = no FAIL (safe, possibly with warnings) · 1 = one or more FAIL (not demo-safe) · 2 = usage.
#
# Usage: tools/demo-preflight.sh [options]
#   --dashboard-port N     dashboard port (default: $DASHBOARD_PORT or detected from dashboard/package.json, else 3000)
#   --api-url URL          gate API health URL (default: $API_HEALTH_URL or http://127.0.0.1:8009/health)
#   --api-container NAME   gate API container for the env cross-check (default: $GATEAPI_CONTAINER or tanaghom-gateapi)
#   --bot-container NAME   Telegram bot container (default: $BOT_CONTAINER or tanaghom-bot)
#   --json                 emit the same preflight result as machine-readable JSON (observe-only)
#   --require-funnel       treat a missing/mismatched Tailscale Funnel as FAIL (public-access demo profile)
#   --require-telegram     treat a not-running Telegram bot as FAIL (Telegram demo profile)
#   -h, --help             print this help and exit 0

set -uo pipefail

dashboard_port="${DASHBOARD_PORT:-}"
api_url="${API_HEALTH_URL:-http://127.0.0.1:8009/health}"
api_container="${GATEAPI_CONTAINER:-tanaghom-gateapi}"
bot_container="${BOT_CONTAINER:-tanaghom-bot}"
require_funnel=0
require_telegram=0
json_mode=0

usage() { sed -n '2,/^set /p' "$0" | sed 's/^# \{0,1\}//; s/^#$//; /^set /d'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dashboard-port) dashboard_port="${2:-}"; shift 2 ;;
    --api-url) api_url="${2:-}"; shift 2 ;;
    --api-container) api_container="${2:-}"; shift 2 ;;
    --bot-container) bot_container="${2:-}"; shift 2 ;;
    --json) json_mode=1; shift ;;
    --require-funnel) require_funnel=1; shift ;;
    --require-telegram) require_telegram=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# ── output helpers (color only on a TTY) ─────────────────────────────────────
if [[ -t 1 ]]; then C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_0=$'\033[0m'; else C_G=""; C_Y=""; C_R=""; C_0=""; fi
pass_n=0; warn_n=0; fail_n=0
have() { command -v "$1" >/dev/null 2>&1; }
check_ids=()
check_statuses=()
check_messages=()
record_check() {
  check_ids+=("$1")
  check_statuses+=("$2")
  check_messages+=("${3:-}")
}
pass() {
  pass_n=$((pass_n+1))
  record_check "$1" "pass" "${2:-}"
  [[ "${json_mode}" == "1" ]] || printf '%sPASS%s %-16s %s\n' "$C_G" "$C_0" "$1" "${2:-}"
}
warn() {
  warn_n=$((warn_n+1))
  record_check "$1" "warn" "${2:-}"
  [[ "${json_mode}" == "1" ]] || printf '%sWARN%s %-16s %s\n' "$C_Y" "$C_0" "$1" "${2:-}"
}
fail() {
  fail_n=$((fail_n+1))
  record_check "$1" "fail" "${2:-}"
  [[ "${json_mode}" == "1" ]] || printf '%sFAIL%s %-16s %s\n' "$C_R" "$C_0" "$1" "${2:-}"
}
join_by() {
  local sep="$1"; shift
  local IFS="$sep"
  printf '%s' "$*"
}
emit_json() {
  local overall_status="pass"
  [[ "${fail_n}" -gt 0 ]] && overall_status="fail"
  [[ "${fail_n}" -eq 0 && "${warn_n}" -gt 0 ]] && overall_status="warn"
  local sep=$'\037'
  export PRECHECK_IDS="$(join_by "$sep" "${check_ids[@]}")"
  export PRECHECK_STATUSES="$(join_by "$sep" "${check_statuses[@]}")"
  export PRECHECK_MESSAGES="$(join_by "$sep" "${check_messages[@]}")"
  export PRECHECK_OVERALL_STATUS="${overall_status}"
  export PRECHECK_DEMO_SAFE="$([[ "${fail_n}" -eq 0 ]] && echo true || echo false)"
  export PRECHECK_PASS_COUNT="${pass_n}"
  export PRECHECK_WARN_COUNT="${warn_n}"
  export PRECHECK_FAIL_COUNT="${fail_n}"
  export PRECHECK_REQUIRE_FUNNEL="${require_funnel}"
  export PRECHECK_REQUIRE_TELEGRAM="${require_telegram}"
  export PRECHECK_DASHBOARD_URL="${dashboard_url}"
  export PRECHECK_API_URL="${api_url}"
  export PRECHECK_API_CONTAINER="${api_container}"
  export PRECHECK_BOT_CONTAINER="${bot_container}"
  if have python3; then
    python3 - <<'PY'
import json
import os

sep = "\x1f"
ids = [x for x in os.getenv("PRECHECK_IDS", "").split(sep) if x != ""]
statuses = [x for x in os.getenv("PRECHECK_STATUSES", "").split(sep) if x != ""]
messages = [x for x in os.getenv("PRECHECK_MESSAGES", "").split(sep) if x != ""]
checks = []
for i, cid in enumerate(ids):
    checks.append({
        "id": cid,
        "name": cid,
        "status": statuses[i] if i < len(statuses) else "unknown",
        "message": messages[i] if i < len(messages) else "",
    })
print(json.dumps({
    "overall_status": os.getenv("PRECHECK_OVERALL_STATUS", "pass"),
    "demo_safe": os.getenv("PRECHECK_DEMO_SAFE", "false") == "true",
    "failure_count": int(os.getenv("PRECHECK_FAIL_COUNT", "0")),
    "warning_count": int(os.getenv("PRECHECK_WARN_COUNT", "0")),
    "pass_count": int(os.getenv("PRECHECK_PASS_COUNT", "0")),
    "options": {
        "require_funnel": os.getenv("PRECHECK_REQUIRE_FUNNEL", "0") == "1",
        "require_telegram": os.getenv("PRECHECK_REQUIRE_TELEGRAM", "0") == "1",
    },
    "context": {
        "dashboard_url": os.getenv("PRECHECK_DASHBOARD_URL", ""),
        "api_url": os.getenv("PRECHECK_API_URL", ""),
        "api_container": os.getenv("PRECHECK_API_CONTAINER", ""),
        "bot_container": os.getenv("PRECHECK_BOT_CONTAINER", ""),
    },
    "checks": checks,
}, ensure_ascii=False))
PY
    return
  fi
  if have node; then
    node - <<'JS'
const sep = "\x1f";
const split = (key) => (process.env[key] || "").split(sep).filter(Boolean);
const ids = split("PRECHECK_IDS");
const statuses = split("PRECHECK_STATUSES");
const messages = split("PRECHECK_MESSAGES");
const checks = ids.map((id, i) => ({
  id,
  name: id,
  status: statuses[i] || "unknown",
  message: messages[i] || "",
}));
process.stdout.write(JSON.stringify({
  overall_status: process.env.PRECHECK_OVERALL_STATUS || "pass",
  demo_safe: process.env.PRECHECK_DEMO_SAFE === "true",
  failure_count: Number(process.env.PRECHECK_FAIL_COUNT || 0),
  warning_count: Number(process.env.PRECHECK_WARN_COUNT || 0),
  pass_count: Number(process.env.PRECHECK_PASS_COUNT || 0),
  options: {
    require_funnel: process.env.PRECHECK_REQUIRE_FUNNEL === "1",
    require_telegram: process.env.PRECHECK_REQUIRE_TELEGRAM === "1",
  },
  context: {
    dashboard_url: process.env.PRECHECK_DASHBOARD_URL || "",
    api_url: process.env.PRECHECK_API_URL || "",
    api_container: process.env.PRECHECK_API_CONTAINER || "",
    bot_container: process.env.PRECHECK_BOT_CONTAINER || "",
  },
  checks,
}));
JS
    return
  fi
  echo "--json requires python3 or node to serialize the observe-only check results" >&2
  exit 2
}

# ── resolve the dashboard port (prefer an explicit value, else package.json -p, else 3000) ──
if [[ -z "${dashboard_port}" ]]; then
  repo_root="$(cd "$(dirname "$0")/.." && pwd)"
  if have node && [[ -f "${repo_root}/dashboard/package.json" ]]; then
    dashboard_port="$(node -e '
      const p=require(process.argv[1]);
      const m=[p.scripts?.start,p.scripts?.dev].filter(Boolean).map(s=>s.match(/(?:^|\s)-p\s+(\d+)/)).find(Boolean);
      console.log(m?m[1]:"3000");' "${repo_root}/dashboard/package.json" 2>/dev/null || echo 3000)"
  fi
  dashboard_port="${dashboard_port:-3000}"
fi
dashboard_url="http://127.0.0.1:${dashboard_port}"

if [[ "${json_mode}" != "1" ]]; then
  echo "Tanaghom demo-safe preflight (observe-only)"
  echo "dashboard: ${dashboard_url}   api: ${api_url}   gate-api container: ${api_container}"
  echo
fi

# ── 1. local dashboard ───────────────────────────────────────────────────────
if curl -fsS --max-time 5 "${dashboard_url}" >/dev/null 2>&1; then
  pass "dashboard" "reachable at ${dashboard_url}"
else
  fail "dashboard" "NOT reachable at ${dashboard_url} — start the dashboard (pnpm dev) or fix the port"
fi

# ── 2. gate API health ─────────────────────────────────────────────────────────
api_health=""
if api_health="$(curl -fsS --max-time 5 "${api_url}" 2>/dev/null)"; then
  pass "gate-api" "healthy at ${api_url}"
else
  fail "gate-api" "health endpoint ${api_url} unreachable — is the gate API container up?"
fi

# ── 3. writer mode (the #5 footgun) — cross-check /health AND the container env ──
# Two independent observe-only signals: the RUNNING mode (/health) and the CONFIGURED env (docker
# inspect). Either one showing stub is a demo-blocking FAIL; a mismatch between them is a WARN.
health_stub="unknown"
if [[ -n "${api_health}" ]]; then
  if printf '%s' "${api_health}" | grep -Eq '"writer_stub"[[:space:]]*:[[:space:]]*true'; then health_stub="on"
  elif printf '%s' "${api_health}" | grep -Eq '"writer_stub"[[:space:]]*:[[:space:]]*false'; then health_stub="off"; fi
fi
env_stub="unknown"
if have docker; then
  env_line="$(docker inspect "${api_container}" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^TANAGHOM_WRITER_STUB=' || true)"
  if [[ -n "${env_line}" ]]; then
    case "${env_line#TANAGHOM_WRITER_STUB=}" in 1|true|TRUE|True) env_stub="on" ;; *) env_stub="off" ;; esac
  else
    env_stub="off"   # unset env => stub disabled (the app default)
  fi
fi

if [[ "${health_stub}" == "on" || "${env_stub}" == "on" ]]; then
  fail "writer-mode" "WRITER STUB enabled (/health=${health_stub}, env=${env_stub}) — live review would show deterministic stub content; NOT demo-safe"
elif [[ "${health_stub}" == "off" ]]; then
  [[ "${env_stub}" == "off" ]] && pass "writer-mode" "live (real generation); stub off in /health and container env" \
                               || warn "writer-mode" "/health reports live but env cross-check was inconclusive (env=${env_stub})"
elif [[ "${env_stub}" == "off" && "${health_stub}" == "unknown" ]]; then
  warn "writer-mode" "could not read /health writer_stub; container env shows stub OFF (limited confidence)"
else
  warn "writer-mode" "could not confidently determine writer mode (/health=${health_stub}, env=${env_stub}) — verify manually before a live demo"
fi

# ── 3b. reviewer proxy secret (#147 / #146 S1) — must not ride the public dev fallback ──
# Read the two booleans /health now exposes (never the secret). A demo/production runtime with
# neither a configured secret nor explicit dev-mode fails CLOSED on every review action → FAIL.
# Dev-mode-with-no-secret works but signs with a known-public key → WARN (fine locally, not for a
# real client demo). A configured secret is the safe state.
rev_configured="unknown"; rev_devmode="unknown"
if [[ -n "${api_health}" ]]; then
  if printf '%s' "${api_health}" | grep -Eq '"reviewer_secret_configured"[[:space:]]*:[[:space:]]*true'; then rev_configured="yes"
  elif printf '%s' "${api_health}" | grep -Eq '"reviewer_secret_configured"[[:space:]]*:[[:space:]]*false'; then rev_configured="no"; fi
  if printf '%s' "${api_health}" | grep -Eq '"dev_mode"[[:space:]]*:[[:space:]]*true'; then rev_devmode="on"
  elif printf '%s' "${api_health}" | grep -Eq '"dev_mode"[[:space:]]*:[[:space:]]*false'; then rev_devmode="off"; fi
fi

if [[ "${rev_configured}" == "yes" ]]; then
  pass "reviewer-secret" "REVIEWER_PROXY_SECRET configured (review-action auth is not on the dev fallback)"
elif [[ "${rev_configured}" == "no" && "${rev_devmode}" == "on" ]]; then
  warn "reviewer-secret" "signing with the DEV fallback secret (TANAGHOM_DEV_MODE) — fine for a local dry run, NOT a client demo; set REVIEWER_PROXY_SECRET"
elif [[ "${rev_configured}" == "no" && "${rev_devmode}" == "off" ]]; then
  fail "reviewer-secret" "REVIEWER_PROXY_SECRET not configured and dev-mode off — review actions FAIL CLOSED; set REVIEWER_PROXY_SECRET (or TANAGHOM_DEV_MODE=1 for local/dev/test)"
else
  warn "reviewer-secret" "could not read reviewer-secret config from /health (older API?) — verify REVIEWER_PROXY_SECRET before a live demo"
fi

# ── 4. gate API published port / drift ──────────────────────────────────────────
# Expected external port is parsed from --api-url; warn if the container publishes a different one.
expected_api_port="$(printf '%s' "${api_url}" | sed -nE 's#.*://[^:/]+:([0-9]+).*#\1#p')"
if have docker && [[ -n "${expected_api_port}" ]]; then
  published="$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | awk -v n="${api_container}" '$1==n' | sed -nE 's/.*0\.0\.0\.0:([0-9]+)->.*/\1/p' | head -n1)"
  if [[ -n "${published}" && "${published}" != "${expected_api_port}" ]]; then
    warn "api-port" "container ${api_container} publishes :${published} but preflight expects :${expected_api_port} (port drift) — pass --api-url to match"
  elif [[ -n "${published}" ]]; then
    pass "api-port" "gate API published on expected :${expected_api_port}"
  fi
fi

# ── 5. Tailscale Funnel (public access) — observe only, never reconfigure ────────
public_url=""
if have tailscale; then
  funnel_status="$(tailscale funnel status 2>/dev/null || true)"
  if [[ -n "${funnel_status}" ]]; then
    proxy_port="$(printf '%s\n' "${funnel_status}" | sed -nE 's#.*proxy http://127\.0\.0\.1:([0-9]+).*#\1#p' | head -n1)"
    public_url="$(printf '%s\n' "${funnel_status}" | sed -nE 's#^(https://[^ ]+) \(Funnel on\)$#\1#p' | head -n1)"
    if [[ -n "${proxy_port}" && "${proxy_port}" == "${dashboard_port}" ]]; then
      pass "tailscale" "Funnel → :${dashboard_port}  ${public_url:+(${public_url})}"
    elif [[ -n "${proxy_port}" ]]; then
      msg="Funnel proxies :${proxy_port} but dashboard is :${dashboard_port} (drift) — run: tailscale funnel --bg ${dashboard_port}"
      [[ "${require_funnel}" == "1" ]] && fail "tailscale" "${msg}" || warn "tailscale" "${msg}"
    else
      msg="no dashboard Funnel proxy configured — public access is off (fine for a localhost demo)"
      [[ "${require_funnel}" == "1" ]] && fail "tailscale" "${msg}" || warn "tailscale" "${msg}"
    fi
  else
    msg="Tailscale Funnel not active / not logged in — public access is off"
    [[ "${require_funnel}" == "1" ]] && fail "tailscale" "${msg}" || warn "tailscale" "${msg}"
  fi
else
  msg="tailscale CLI not installed — cannot verify public access"
  [[ "${require_funnel}" == "1" ]] && fail "tailscale" "${msg}" || warn "tailscale" "${msg}"
fi

# ── 6. public dashboard (only if a Funnel URL was found) ─────────────────────────
if [[ -n "${public_url}" ]]; then
  if curl -fsS --max-time 8 "${public_url}" >/dev/null 2>&1; then
    pass "public-dash" "reachable at ${public_url}"
  else
    msg="public URL ${public_url} not reachable — Funnel may still be warming up"
    [[ "${require_funnel}" == "1" ]] && fail "public-dash" "${msg}" || warn "public-dash" "${msg}"
  fi
fi

# ── 7. Telegram singleton (only one bot process may hold the long-poll) ──────────
if have docker; then
  running="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -cx "${bot_container}" || true)"
  if [[ "${running}" -ge 2 ]]; then
    fail "telegram" "MULTIPLE '${bot_container}' containers running (${running}) — Telegram allows one long-poll; they will fight and drop updates"
  elif [[ "${running}" == "1" ]]; then
    pass "telegram" "single '${bot_container}' container running (singleton satisfied)"
  else
    msg="'${bot_container}' not running — Telegram control channel is off (fine unless you're demoing Telegram)"
    [[ "${require_telegram}" == "1" ]] && fail "telegram" "${msg}" || warn "telegram" "${msg}"
  fi
elif [[ "${require_telegram}" == "1" ]]; then
  fail "telegram" "docker not available to verify the '${bot_container}' singleton"
fi

# ── summary ─────────────────────────────────────────────────────────────────────
if [[ "${json_mode}" == "1" ]]; then
  emit_json
elif [[ "${json_mode}" != "1" ]]; then
  echo
  printf 'summary: %d pass, %d warn, %d fail\n' "${pass_n}" "${warn_n}" "${fail_n}"
fi
if [[ "${fail_n}" -gt 0 ]]; then
  [[ "${json_mode}" == "1" ]] || echo "${C_R}NOT demo-safe${C_0} — resolve the FAIL item(s) above, then re-run. See docs/ops/demo-safe-preflight.md."
  exit 1
fi
if [[ "${warn_n}" -gt 0 ]]; then
  [[ "${json_mode}" == "1" ]] || echo "${C_Y}demo-safe with warnings${C_0} — review WARN item(s); they may be fine for a localhost-only walkthrough."
else
  [[ "${json_mode}" == "1" ]] || echo "${C_G}demo-safe${C_0} — all checks passed."
fi
exit 0
