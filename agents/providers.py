"""Provider clients for the writer agents.

Connection details come from the `providers` registry in system_config.yaml;
API keys from the env var each provider names (`api_key_env`). All chat providers
are OpenAI-compatible, so one ChatClient serves OpenRouter / Gemini / Ollama.

Key checks are deferred to call time so a missing key raises a ProviderError that
the StageRunner can fall through, rather than failing construction.
"""

import json
import os
import re
import time

import requests

try:
    from .runtime_secret import SecretError as RuntimeSecretError
    from .runtime_secret import resolve as resolve_runtime_secret
except ImportError:  # run_writers.py also supports direct execution from the agents directory
    from runtime_secret import SecretError as RuntimeSecretError
    from runtime_secret import resolve as resolve_runtime_secret


class ProviderError(RuntimeError):
    pass


def _base_url(provider_cfg, env_override=None):
    if env_override and os.environ.get(env_override):
        return os.environ[env_override].rstrip("/")
    return provider_cfg["base_url"].rstrip("/")


class ChatClient:
    """OpenAI-compatible /chat/completions (OpenRouter, Gemini, Ollama /v1, ...)."""

    def __init__(self, provider_cfg, model, temperature=0.8, max_tokens=1200,
                 params=None, prompt_suffix="", timeout=300):
        self.base_url = _base_url(provider_cfg)
        self.key_env = provider_cfg.get("api_key_env") or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.params = params or {}          # generic passthrough (reasoning_effort, stop, ...)
        self.prompt_suffix = prompt_suffix or ""
        self.timeout = timeout
        # 429 (rate-limit) handling — important on free tiers. Retry the SAME provider
        # with backoff before the StageRunner falls through to the next one.
        self.max_retries = int(provider_cfg.get("max_retries", 4))
        self.retry_base = float(provider_cfg.get("retry_base_seconds", 20))

    @staticmethod
    def _retry_after(resp, attempt, base):
        # honour a server-provided delay ("try again in 13.84s" / "in 488ms" / "retryDelay: 34s"),
        # else exponential backoff. Floor at `base`: a too-optimistic sub-second hint near a
        # TPM ceiling would otherwise burn a retry before the per-minute window resets. Capped
        # so a single hop never stalls too long.
        secs = None
        m = re.search(r'try again in (\d+(?:\.\d+)?)\s*(ms|s)\b', resp.text)
        if m:
            secs = float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
        else:
            m = re.search(r'(?:retryDelay"?\s*[:=]\s*"?|retry in )(\d+)', resp.text)
            if m:
                secs = float(m.group(1))
        if secs is None:
            secs = base * (2 ** attempt)
        return min(max(secs + 1, base), 65)

    @staticmethod
    def _is_persistent_429(resp):
        """Distinguish a *persistent* quota 429 (daily/quota exhausted) from a transient
        per-minute rate-limit. Retrying a persistent one is pointless — it only burns the
        backoff budget — so the StageRunner should fall through immediately. A per-minute
        (TPM/RPM) limit resets within ~a minute, so it is transient: retry, don't fall
        through. NB: do NOT match on the generic "…/settings/billing" upgrade URL that
        Groq appends to *every* 429 — it is not a quota signal."""
        body = resp.text.lower()
        if "per minute" in body or "(tpm)" in body or "(rpm)" in body:
            return False                       # transient — resets each minute, retry
        persistent = ("per day", "(tpd)", "(rpd)", "tokens per day", "requests per day",
                      "resource_exhausted", "insufficient_quota", "exceeded your current quota")
        return any(m in body for m in persistent)

    def _api_key(self):
        if not self.key_env:
            return ""
        try:
            return resolve_runtime_secret(self.key_env)[0]
        except RuntimeSecretError as exc:
            raise ProviderError(f"missing API key: {exc}") from exc

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json", "X-Title": "Tanaghom Writers"}
        key = self._api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + self.prompt_suffix},
            ],
        }
        body.update(self.params)            # provider-specific knobs from config
        for attempt in range(self.max_retries + 1):
            try:
                r = requests.post(f"{self.base_url}/chat/completions",
                                  headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                raise ProviderError(f"chat request failed: {e}") from e
            if r.status_code == 429 and attempt < self.max_retries:
                # persistent quota/daily-limit -> don't retry; let the runner fall through now
                if self._is_persistent_429(r):
                    print(f"  [quota] {self.model}: persistent 429 (quota/daily limit) "
                          f"-> falling through immediately", flush=True)
                    break
                delay = self._retry_after(r, attempt, self.retry_base)
                print(f"  [rate-limit] {self.model}: 429, waiting {delay:.0f}s "
                      f"(retry {attempt + 1}/{self.max_retries})", flush=True)
                time.sleep(delay)
                continue
            break
        if r.status_code != 200:
            raise ProviderError(f"chat HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"unexpected chat response: {json.dumps(data)[:400]}") from e
        if choice.get("finish_reason") == "length":
            raise ProviderError(
                f"response truncated at max_tokens ({self.max_tokens}); raise the stage's "
                f"max_tokens in system_config.yaml")
        return content


class EmbeddingClient:
    """Ollama /api/embeddings. Output dim must match the topic.embedding column."""

    def __init__(self, provider_cfg, model, timeout=90):
        self.base_url = _base_url(provider_cfg, env_override="OLLAMA_BASE_URL")
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        try:
            r = requests.post(f"{self.base_url}/api/embeddings",
                              json={"model": self.model, "prompt": text},
                              timeout=self.timeout)
        except requests.RequestException as e:
            raise ProviderError(f"embedding request failed: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"embedding HTTP {r.status_code}: {r.text[:300]}")
        vec = r.json().get("embedding")
        if not vec:
            raise ProviderError("embedding response had no 'embedding'")
        return vec
