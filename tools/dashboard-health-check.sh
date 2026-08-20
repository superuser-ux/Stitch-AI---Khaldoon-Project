#!/usr/bin/env bash

set -euo pipefail

fix_tailscale=0
dashboard_port="${DASHBOARD_PORT:-}"
api_url="${API_HEALTH_URL:-http://127.0.0.1:8009/health}"
check_mobile=1
check_telegram=1
allow_stub=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix-tailscale)
      fix_tailscale=1
      shift
      ;;
    --skip-mobile)
      check_mobile=0
      shift
      ;;
    --skip-telegram)
      check_telegram=0
      shift
      ;;
    --allow-stub)
      allow_stub=1
      shift
      ;;
    --dashboard-port)
      dashboard_port="${2:-}"
      shift 2
      ;;
    --api-url)
      api_url="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

detect_dashboard_port() {
  node <<'EOF'
const fs = require("node:fs");
const path = require("node:path");
const pkg = JSON.parse(fs.readFileSync(path.join(process.cwd(), "dashboard", "package.json"), "utf8"));
const scripts = [pkg.scripts?.start, pkg.scripts?.dev].filter(Boolean);
for (const script of scripts) {
  const match = script.match(/(?:^|\s)-p\s+(\d+)(?:\s|$)/);
  if (match) {
    console.log(match[1]);
    process.exit(0);
  }
}
console.log("3000");
EOF
}

if [[ -z "${dashboard_port}" ]]; then
  dashboard_port="$(detect_dashboard_port)"
fi

dashboard_url="http://127.0.0.1:${dashboard_port}"

check_url() {
  local label="$1"
  local url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null; then
    echo "ok  ${label}: ${url}"
  else
    echo "err ${label}: ${url}" >&2
    return 1
  fi
}

echo "Dashboard health check"
echo "dashboard_port: ${dashboard_port}"
echo "dashboard_url:  ${dashboard_url}"
echo "api_url:        ${api_url}"
echo

check_url "dashboard" "${dashboard_url}"
api_health="$(curl -fsS --max-time 5 "${api_url}")"
echo "ok  gate api: ${api_url}"
if printf '%s' "${api_health}" | grep -q '"writer_stub"[[:space:]]*:[[:space:]]*true'; then
  if [[ "${allow_stub}" == "1" ]]; then
    echo "warn writer mode: STUB is enabled (allowed by flag)"
  else
    echo "err writer mode: STUB is enabled on the gate API; this is not demo-safe" >&2
    exit 1
  fi
else
  echo "ok  writer mode: live"
fi

echo

public_url=""
if command -v tailscale >/dev/null 2>&1; then
  funnel_status="$(tailscale funnel status 2>/dev/null || true)"
  if [[ -z "${funnel_status}" ]]; then
    echo "err tailscale: no funnel status available" >&2
    exit 1
  else
    current_proxy="$(printf '%s\n' "${funnel_status}" | sed -nE 's#^\|-- / proxy http://127\.0\.0\.1:([0-9]+)$#\1#p' | head -n1)"
    public_url="$(printf '%s\n' "${funnel_status}" | sed -nE 's#^(https://[^ ]+) \(Funnel on\)$#\1#p' | head -n1)"

    if [[ -n "${current_proxy}" ]]; then
      echo "tailscale_funnel_url: ${public_url:-unknown}"
      echo "tailscale_proxy_port: ${current_proxy}"
      if [[ "${current_proxy}" != "${dashboard_port}" ]]; then
        echo "warn tailscale: funnel points to ${current_proxy}, expected ${dashboard_port}"
        if [[ "${fix_tailscale}" == "1" ]]; then
          tailscale funnel --bg "${dashboard_port}" >/dev/null
          echo "fix tailscale: updated funnel to http://127.0.0.1:${dashboard_port}"
          public_url="$(tailscale funnel status 2>/dev/null | sed -nE 's#^(https://[^ ]+) \(Funnel on\)$#\1#p' | head -n1)"
          current_proxy="${dashboard_port}"
        fi
      fi
      if [[ "${current_proxy}" == "${dashboard_port}" ]]; then
        echo "ok  tailscale: funnel matches dashboard port ${dashboard_port}"
      fi
    else
      echo "err tailscale: no dashboard funnel proxy found" >&2
      if [[ "${fix_tailscale}" == "1" ]]; then
        tailscale funnel --bg "${dashboard_port}" >/dev/null
        echo "fix tailscale: started funnel for http://127.0.0.1:${dashboard_port}"
        public_url="$(tailscale funnel status 2>/dev/null | sed -nE 's#^(https://[^ ]+) \(Funnel on\)$#\1#p' | head -n1)"
      else
        exit 1
      fi
    fi
  fi
else
  echo "err tailscale: command not installed" >&2
  exit 1
fi

if [[ -z "${public_url}" ]]; then
  echo "err tailscale: public funnel URL missing" >&2
  exit 1
fi

check_url "public dashboard" "${public_url}"

if [[ "${check_telegram}" == "1" ]]; then
  if docker ps --format '{{.Names}}' | grep -qx 'tanaghom-bot'; then
    echo "ok  telegram: tanaghom-bot is running"
  else
    echo "err telegram: tanaghom-bot is not running" >&2
    exit 1
  fi
fi

if [[ "${check_mobile}" == "1" ]]; then
  echo
  (
    cd dashboard
    DASHBOARD_URL="${dashboard_url}" PUBLIC_URL="${public_url}" node <<'EOF'
const { chromium, devices } = require("playwright");

const urls = [process.env.DASHBOARD_URL, process.env.PUBLIC_URL].filter(Boolean);

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "chrome" });
  try {
    let hadFailure = false;
    for (const url of urls) {
      const context = await browser.newContext({ ...devices["iPhone 13"] });
      const page = await context.newPage();
      const routeFailures = [];
      page.on("requestfailed", (request) => {
        routeFailures.push(`requestfailed ${request.resourceType()} ${request.url()} ${request.failure()?.errorText || "unknown"}`);
      });
      page.on("response", (response) => {
        if (response.status() >= 400 && ["document", "stylesheet", "script", "fetch", "xhr"].includes(response.request().resourceType())) {
          routeFailures.push(`http ${response.status()} ${response.request().resourceType()} ${response.url()}`);
        }
      });
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
      await page.getByTestId("new-run").waitFor({ state: "visible", timeout: 15000 });
      await page.getByTestId("round-trigger").waitFor({ state: "visible", timeout: 15000 });
      if (routeFailures.length) {
        hadFailure = true;
        console.error(`err mobile-smoke: ${url}`);
        routeFailures.forEach((failure) => console.error(`  ${failure}`));
      } else {
        console.log(`ok  mobile-smoke: ${url}`);
      }
      await context.close();
    }
    if (hadFailure) process.exit(1);
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error(err.stack || String(err));
  process.exit(1);
});
EOF
  )
fi
