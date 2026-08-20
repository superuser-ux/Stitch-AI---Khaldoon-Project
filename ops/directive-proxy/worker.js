// Tanaghom Directive Bus — Cloudflare Worker proxy.
//
// Why this exists: ChatGPT custom-GPT Actions send no User-Agent header and ignore any header defined
// in the OpenAPI schema, but the GitHub REST API 403s every request without a User-Agent. This proxy
// sits between the GPT and GitHub, adds the required headers + the real GitHub token, and forwards only
// the whitelisted issue operations on Kholio/tanaghom.
//
// Security model:
//   - The real GitHub token lives ONLY here (Cloudflare secret GITHUB_TOKEN) — never in OpenAI.
//   - The GPT authenticates to THIS worker with a separate shared secret (PROXY_SECRET). If that leaks,
//     the blast radius is only the whitelisted issue endpoints on this one repo — the GitHub token is safe.
//   - Anything outside the allow-list is rejected.
//
// Secrets (set with `wrangler secret put ...` or in the dashboard → Settings → Variables):
//   GITHUB_TOKEN  — fine-grained PAT on Kholio/tanaghom only: Issues read+write, and (for the
//                   read-only PR-inspection endpoints below) Pull requests: read. It has NO
//                   contents-write, PR-write, or merge scope — GPT can read PRs but never merge/modify them.
//   PROXY_SECRET  — a random string the GPT sends as `Authorization: Bearer <PROXY_SECRET>`.

const REPO_ISSUES = "/repos/Kholio/tanaghom/issues";

function json(obj, status) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}

function isAllowed(method, path) {
  if (path === REPO_ISSUES) return method === "GET" || method === "POST";           // list / create
  if (/^\/repos\/Kholio\/tanaghom\/issues\/\d+$/.test(path)) return method === "GET";          // one issue
  if (/^\/repos\/Kholio\/tanaghom\/issues\/\d+\/comments$/.test(path)) return method === "GET"; // its comments
  // READ-ONLY pull-request inspection (GET only) — lets GPT plan against delivery state. No write/merge.
  if (path === "/repos/Kholio/tanaghom/pulls") return method === "GET";                         // list PRs
  if (/^\/repos\/Kholio\/tanaghom\/pulls\/\d+$/.test(path)) return method === "GET";            // one PR
  if (/^\/repos\/Kholio\/tanaghom\/pulls\/\d+\/reviews$/.test(path)) return method === "GET";   // its reviews
  return false;
}

export default {
  async fetch(request, env) {
    // 1) Authenticate the caller (the GPT) with the shared proxy secret.
    if (!env.PROXY_SECRET || request.headers.get("Authorization") !== `Bearer ${env.PROXY_SECRET}`) {
      return json({ error: "unauthorized" }, 401);
    }

    const url = new URL(request.url);
    const method = request.method.toUpperCase();

    // 2) Allow only the directive-bus issue operations on this one repo.
    if (!isAllowed(method, url.pathname)) {
      return json({ error: "forbidden", method, path: url.pathname }, 403);
    }

    // 3) Forward to GitHub with the headers it requires + the real token.
    const init = {
      method,
      headers: {
        "User-Agent": "tanaghom-directive-gpt",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    };
    if (method === "POST") {
      init.headers["Content-Type"] = "application/json";
      init.body = await request.text();
    }

    const gh = await fetch("https://api.github.com" + url.pathname + url.search, init);
    const body = await gh.text();
    return new Response(body, { status: gh.status, headers: { "Content-Type": "application/json" } });
  },
};
