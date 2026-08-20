# Directive Bus — Cloudflare Worker proxy setup (wrangler)

Why a proxy: ChatGPT custom-GPT Actions send **no `User-Agent`** and ignore any header you add in the
schema, but the GitHub API 403s every request without one. This Worker sits in front of GitHub, adds the
required headers + the real token, and forwards only the whitelisted issue operations. **The GitHub token
lives only in Cloudflare — never in OpenAI.**

Files: `ops/directive-proxy/worker.js`, `ops/directive-proxy/wrangler.toml`.

## 1. Deploy the Worker (from the repo)

```bash
cd ops/directive-proxy
npx wrangler login          # opens a browser to authorise Cloudflare (one time)
```

Generate the shared secret the GPT will use (save the output — you'll paste it twice):
```bash
openssl rand -hex 32
```

Set the two secrets (stored encrypted in Cloudflare, not in the repo):
```bash
npx wrangler secret put GITHUB_TOKEN    # paste the fine-grained PAT (Issues r/w on Kholio/tanaghom)
npx wrangler secret put PROXY_SECRET    # paste the openssl string from above
```

Deploy:
```bash
npx wrangler deploy         # prints your Worker URL, e.g. https://tanaghom-directive-proxy.<you>.workers.dev
```

## 2. Verify the Worker directly (before touching the GPT)

```bash
curl -s -H "Authorization: Bearer <PROXY_SECRET>" \
  "https://<your-worker-url>/repos/Kholio/tanaghom/issues?state=open&per_page=3" | head
```
- Returns issue JSON → the proxy + token + repo all work.
- `401 unauthorized` → wrong PROXY_SECRET.
- `403 forbidden` → path not on the allow-list (you changed something).

## 3. Point the GPT at the Worker

GPT Builder → your GPT → Configure → **Actions**:
1. **Schema:** paste `docs/directive-bus/gpt-action-schema.proxy.json`, then **replace
   `https://REPLACE-WITH-YOUR-WORKER-URL`** (the `servers.url`) with your actual Worker URL.
2. **Authentication:** API Key → **Bearer** → paste the **PROXY_SECRET** (NOT the GitHub token — the GPT
   never sees the GitHub token anymore).
3. Save, then click the top-right **Update** for the whole GPT.

## 4. Test end to end
Ask the GPT: *"Use listIssues, state=open."* → approve the consent → you should get **200** and the real
issue list. Then *"draft a tiny directive and post it"* → confirm → a `directive:pending` issue appears.

## Maintain
- Change the Worker code → `npx wrangler deploy` again.
- Rotate the GitHub token → `npx wrangler secret put GITHUB_TOKEN` (no GPT change needed).
- Rotate the proxy secret → `npx wrangler secret put PROXY_SECRET` **and** update the Bearer key in the GPT.
- Roll back: `npx wrangler deployments list` then `npx wrangler rollback [id]`.
- Kill switch: `npx wrangler delete` removes the Worker entirely.

## Security recap
- **GitHub token:** only in Cloudflare (`GITHUB_TOKEN` secret). OpenAI holds only `PROXY_SECRET`.
- The Worker **allow-lists** to issue GET/POST on `Kholio/tanaghom` only — a leaked proxy secret can do
  nothing but read/create issues on this one repo.
- Execution still gates on the human `directive:approved` label. Nothing runs unattended.
