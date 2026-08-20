# Host-local Tanaghom config

This directory is intentionally left as a placeholder in git.

Create the following files on the VPS:

- `config/system_config.yaml` from the repo-root `system_config.example.yaml`

Do not commit either file.

## Trial generation route (#230 — temporary, config-only)

`models.topic_hook` and `models.script` run a temporary, reversible trial route.
The **executable** order is three hops:

    OpenRouter Scout → Groq Scout → Groq Qwen

This is bootstrap policy pending the capability-matrix layer, not a production
governance decision. The exact provider/model IDs, temperatures, and token limits
live in `system_config.example.yaml`; the host `config/system_config.yaml` is
derived from it, so keep the two in sync when the trial route changes.

**GFWS Ollama** is the **authorized final _logical_ hop, but DEFERRED** — it is
deliberately **not** an executable fallback. The shared `ollama` provider resolves
to `host.docker.internal` (the host's embeddings-only Ollama), which is **not** the
separate GFWS machine; wiring a chat model under it would be a knowingly-wrong
endpoint/model pairing. Add GFWS only via a **dedicated `gfws_ollama` provider**
once its private endpoint is verified over **Tailscale**. That networking/provider
work is **out of scope for #230** — do not add it here.

**Provider naming (unambiguous):** `ollama_embed` is **embeddings-only**
(`mxbai-embed-large` / `whisper`) and is never a chat hop; on this host it is the
VPS-local Ollama. The `ollama` chat provider is **host-local**, not GFWS.

**Preconditions on the VPS host (checked, not assumed):**

- `OPENROUTER_API_KEY` must be present in the gateapi environment for the
  OpenRouter primary to actually serve. If it is absent, the runner transparently
  and truthfully falls through to Groq Scout — safe, but **not** a real trial
  activation. Provision the key per the #187 secret rules (never commit/print it);
  this is a deployment prerequisite, not permission to embed/move the key.

## Config-only model-replacement rule (temporary trial operating rule)

While the trial route is in force, changing a topic/script model **within an
already-registered provider and the same writer contract** is a *managed config
edit*, not an architecture exercise. The required steps are:

1. Edit the `{provider, model}` in `models.topic_hook` / `models.script` (and keep
   `system_config.example.yaml` in sync). Use an exact, runtime-verified model ID.
2. Confirm attribution stays truthful — each successful generation and each
   fallback hop reports its real provider/model (no silent substitution).
3. Run the focused smoke: one synthetic (non-client) topic + script proving the
   intended primary serves, and a forced primary-failure proving the next hop.
4. Get operator approval.

No new provider framework, schema, settings UI, IAM, secret manager, or routing
engine is implied. The future capability matrix supersedes this static order.
