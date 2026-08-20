# Directive Bus — one-time setup (your ~3-minute part)

Everything on the GitHub side is done (labels + this pack). This is the part that only you can do,
because it lives inside your ChatGPT account (GPT Builder). Do it once.

## Step 1 — Create a minimal, revocable GitHub token

GitHub → **Settings → Developer settings → Fine-grained tokens → Generate new token**

| Field | Value |
|-------|-------|
| Token name | `chatgpt-directive-writer` |
| Expiration | 90 days (rotate; auto-revokes if forgotten) |
| Resource owner | `Kholio` (your account) |
| Repository access | **Only select repositories → `Kholio/tanaghom`** |
| Permissions → Repository → **Issues** | **Read and write** |
| Every other permission | **No access** (GitHub auto-adds *Metadata: Read* — leave it) |

Generate → **copy the token** (`github_pat_…`). This is the whole blast radius: *create/edit issues in one
repo, nothing else.* Revoke anytime on that same page (instant).

## Step 2 — Create the custom GPT

chatgpt.com → **Explore GPTs → Create** (or **My GPTs → Create a GPT**) → **Configure** tab:

1. **Name:** e.g. `Tanaghom Directive Author`.
2. **Instructions:** paste the full contents of [`gpt-instructions.md`](./gpt-instructions.md).
3. **Actions → Create new action:**
   - **Schema:** paste the full contents of [`gpt-action-schema.json`](./gpt-action-schema.json).
   - **Authentication:** Authentication Type = **API Key** · Auth Type = **Bearer** · Key = *paste the
     token from Step 1*.
   - **Privacy policy URL** (the form requires one): `https://github.com/Kholio/tanaghom` is fine.
4. Set the GPT to **"Only me"** (do not publish/share) → **Save**.

## Step 3 — Test it

Ask the GPT: *"Draft a tiny test directive and post it."* Confirm the post. It should return a
`directive:pending` issue; check it appears in the repo issues. Delete/close that test issue after.

## Daily use after setup

1. In the GPT: plan work → *"post it"* → it creates a `directive:pending` issue (**zero copy-paste**).
2. In GitHub: review the issue → apply **`directive:approved`** (your one-click gate).
3. In Claude Code: say **"run the next directive"** → it fetches the approved one, ACKs its plan, executes,
   and posts a report comment + closes it.
4. The GPT reads the report + merged PR → plans the next one.

## Security recap
- Token = **issues-write, one repo, time-boxed**. Can't push code, merge, read secrets, or touch other repos.
- A posted issue is **propose-only** — it does nothing until *you* apply `directive:approved`, and Claude
  Code always ACKs before touching code.
- Revoke instantly: GitHub → Settings → Developer settings → Fine-grained tokens → the token → Revoke.
