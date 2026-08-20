# Groq API Key — Git History Exposure Audit

Date: 2026-07-05
Author: CC (read-only security audit)
Repo: `Kholio/tanaghom`
`origin/main` at audit time: `5dde51d`
Prompt: "Read-Only Groq Key History Audit — CC only (OR)"

---

## Risk classification

### `NO_GIT_HISTORY_EXPOSURE_FOUND`

The Groq API key currently in `dashboard/.env.local` — and any Groq-shaped (`gsk_…`) token — is **absent from the entire Git history across all refs** (local branches, remote-tracking branches, tags). No `.env`/`.env.local` file was ever committed. Exposure is **local-disk only**.

---

## Local file status

| Check | Result |
|-------|--------|
| Ignored? | ✅ Yes — matched by `dashboard/.gitignore:4:.env.local` |
| Tracked in worktree? | ❌ No (`git ls-files` empty) |
| Ever tracked in history? | ❌ No — 0 commits touched any `dashboard/.env.local` path |
| Variables in file (names only) | `API_BASE`, `GROQ_API_KEY`, `COPILOT_MODEL`, `COPILOTKIT_TELEMETRY_DISABLED` |

## Redacted key fingerprint (no secret value printed)

| Field | Value |
|-------|-------|
| Provider | Groq |
| Variable | `GROQ_API_KEY` |
| Prefix (first 6) | `gsk_tp` |
| Suffix (last 4) | `w61T` |
| Length | 56 |
| SHA256 (first 12 hex) | `63fed9fdd5c6` |

(46 of 56 characters withheld; fingerprint is one-way.)

## History audit results (all `--all` refs; metadata only, no diff content emitted)

| Search | Method | Result |
|--------|--------|--------|
| Exact current key | `git log --all --oneline -S"$KEY"` | **NO MATCH** — key value never added/removed in any commit |
| Groq key pattern | `git log --all --oneline -G'gsk_[A-Za-z0-9]{20,}'` | **NO MATCH** — no commit ever added/removed a Groq-shaped token |
| `.env` / `.env.local` files | `git log --all --oneline -- '*.env' '*.env.local'` | **NO MATCH** — no such file ever committed |
| Variable name `GROQ_API_KEY` | `git log --all --oneline -S'GROQ_API_KEY'` | 16 commits — **name-only references** (`.env.example`, docs, `os.getenv` call sites); the Groq-pattern NO-MATCH confirms none carry a key value |

**Affected commits/files with actual secret material:** NONE.

The 16 variable-name hits (e.g. `f94ae39`, `255a08d`, `c49903a` "security: scrub secrets from plan doc; add gitleaks", `9241749` "M3 round complete on Groq") reference the env-var *name* or the word "Groq" in prose/config — they do not contain a `gsk_` value, as independently confirmed by the pattern search returning nothing.

## Recommended next action

Because there is **no repository exposure**, this is discretionary local hygiene, not incident response:

1. **Rotate only if the key is live/shared** — if this Groq key is a real, active credential shared across machines or people, rotate it in the Groq console as routine hygiene (a key sitting in a developer `.env.local` is normal, but rotation is cheap insurance if its handling is uncertain). If it is a personal/dev-only key that has never left this machine, rotation is optional.
2. **Harden `.gitignore` intent** — it is already protected (`dashboard/.gitignore:4` ignores `.env.local`), so there is no gap today. Optional belt-and-suspenders: add an explicit `.env*` / `*.local` rule at the repo root so the protection is intentional and uniform across worktrees rather than relying on the per-dir rule. This would be a separate docs/config PR, not part of this audit.
3. **No history remediation needed** — no `git filter-repo`/BFG, no force-push, no GitHub secret-scanning remediation: there is nothing in history to purge.

## Attestation

- Read-only audit. **No secret value was printed, logged, written to any file, or placed in a shell command literal** — the value was read from `dashboard/.env.local` into an ephemeral shell variable, used only as an argument to `git log -S`, and unset afterward. Only the redacted fingerprint above was emitted.
- No key rotation. `dashboard/.env.local` not edited. No commits, no PR, no `.gitignore` change, no history rewrite, no provider revocation.
- No GitHub mutation. No DB mutation. No issue/label changes. No Pi usage.
- This report is written to disk **uncommitted** per the directive.
