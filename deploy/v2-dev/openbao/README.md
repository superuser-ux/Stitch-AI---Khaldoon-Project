# v2-dev OpenBao materializers

**Non-secret host adapter.** These files are the *only* component that knows OpenBao/AppRole. The
applications (gate API + workbench) remain manager-neutral: they read a plain file
(`REVIEWER_PROXY_SECRET_FILE`) resolved by `gates/reviewer_secret.py` and its TS mirror
(`{dashboard,workbench}/lib/reviewer-secret-file.ts`). No application OpenBao SDK or network attachment.

Nothing here is a secret. RoleID/SecretID and the fetched token/value are **never** committed, printed,
or placed in `/srv/tanaghom-v2-dev`. They live only in the root-only custody tree and process memory /
host tmpfs at runtime.

## Contents
- `materialize-reviewer-proxy.sh` — root oneshot: AppRole login over loopback → fetch one KV-v2 value →
  validate → `revoke-self` + prove reuse-denial → atomic publish to tmpfs. Publishes nothing unless
  revocation + reuse-denial succeed. No secret in argv/stdout/history.
- `reviewer-proxy-policy.hcl` — least-privilege policy: read of exactly `tanaghom/data/dev/reviewer-proxy`;
  everything else default-denied.
- `tanaghom-reviewer-proxy.service` / `.timer` — root oneshot + 5-minute refresh (mtime advances each
  success; a failed run does not refresh, so apps fail closed after the FILE max age).
- `materialize-provider-secret.sh` — the same bounded login/read/revoke/publish flow for exactly
  `openrouter`, `groq`, or `iam-session`; any other identifier is rejected before login.
- `{openrouter,groq,iam-session}-policy.hcl` — separate exact-path read policies. A runtime-secret token
  cannot read a sibling secret, reviewer secret, metadata, or system paths.
- `tanaghom-provider-secret@.service` / `.timer` — one hardened template instantiated separately as
  `openrouter`, `groq`, and `iam-session`.

## Runtime secret setup
For each allowlisted identifier, write the value through stdin to its exact policy path, install its
matching policy, and issue a dedicated AppRole. Store its RoleID and SecretID as root-owned `0600`
`custody/<identifier>.{role_id,secret_id}`. Enable the timers:

```
systemctl enable --now tanaghom-provider-secret@openrouter.timer
systemctl enable --now tanaghom-provider-secret@groq.timer
systemctl enable --now tanaghom-provider-secret@iam-session.timer
```

Successful refreshes publish `/run/tanaghom-secrets/openrouter_api_key` and
`/run/tanaghom-secrets/groq_api_key` at owner `10001:10001`, mode `0400`. The gate API reads them through
`agents/runtime_secret.py`; no application process is given OpenBao network credentials.

The IAM instance reads only `tanaghom/data/dev/iam/session` and publishes
`/run/tanaghom-secrets/iam_session_secret` under the same ownership and mode. The workbench reads that
file only when OIDC is enabled. ZITADEL remains a public PKCE client, so no OIDC client secret exists.

## Developer administration UI

The OpenBao listener stays on VPS loopback. Its native UI must be enabled in the host OpenBao server
configuration (`ui = true`) and is then reached from the developer Mac with a separate tunnel:

```sh
ssh -N -L 13200:127.0.0.1:18200 \
  -i ~/.ssh/stitch_vps_rebuild_ed25519 \
  -o StrictHostKeyChecking=yes administrator@155.117.45.45
```

Open `http://127.0.0.1:13200/ui/`. Use the existing scoped `dev-operator` token, never a root token and
never an AppRole credential. To move the token directly into the Mac clipboard without printing it,
run this in a second local terminal:

```sh
ssh -i ~/.ssh/stitch_vps_rebuild_ed25519 -o StrictHostKeyChecking=yes \
  administrator@155.117.45.45 \
  'sudo sed -n "s/^BAO_TOKEN=//p" /srv/tanaghom-dev/openbao/custody/operator.env' | pbcopy
```

Paste it into OpenBao's **Token** login. Do not save it in the browser. The Tanaghom
`/admin/secrets` page is deliberately a metadata-only operational surface: it reports whether the
three runtime inputs are valid and fresh but cannot enumerate OpenBao paths, display values, or mint
tokens. Secret writes and policy/auth administration stay in OpenBao's audited native UI until a
narrow privileged broker is designed alongside Zitadel-backed operator authentication.

## One-time OpenBao setup (cutover phase — not performed by this PR)
Run as the developer OpenBao operator against loopback `127.0.0.1:18200`, no secret material in argv:
1. Enable KV-v2 mount `tanaghom/` if absent; write the one value:
   `bao kv put tanaghom/dev/reviewer-proxy value=@-` (value piped via stdin — never argv).
2. Write the policy: `bao policy write tanaghom-reviewer-proxy reviewer-proxy-policy.hcl`.
3. Enable AppRole; create a role bound only to that policy (short token TTL, `token_num_uses` small,
   `secret_id_num_uses` as your rotation cadence requires); read RoleID and issue a SecretID.
4. Store RoleID/SecretID as **root-owned 0600** files under the custody tree
   (`/srv/tanaghom-dev/openbao/custody/reviewer-proxy.{role_id,secret_id}` by default). Never elsewhere.
5. These files ship as manifest-verified inputs in the candidate layout at
   `/srv/tanaghom-v2-dev/openbao/`. During cutover, **copy the manifest-verified artifacts** to the host
   OpenBao infrastructure: the unit files to `/etc/systemd/system/` and the adapter/policy to
   `/srv/tanaghom-dev/openbao/` (co-located with the custody tree; they are not executed from the app
   candidate path). `systemctl enable --now tanaghom-reviewer-proxy.timer`, and confirm
   `/run/tanaghom-secrets/reviewer_proxy_secret` appears (dir `0500`, file `0400`, owner `10001:10001`).

## Import / equality (cutover phase)
Prove the current gate/workbench env value equals the value to import **without output** (compare
digests in-process, never print the value), import it to OpenBao (stdin), then prove AppRole
read + the required denials before recreating only gate/workbench with the FILE seam.

## Rollback (cutover phase)
Restore the prior exact compose/images; materialize the credential into a temp root-only `0600` rollback
env file (no output); recreate only gate/workbench; verify; remove the candidate timer/service/tmpfs
material. Report restored env authority as the **weaker** state. Retain OpenBao data/snapshots/audits/
custody.

## Environment overrides (all non-secret)
`TANAGHOM_OPENBAO_ADDR`, `TANAGHOM_OPENBAO_CUSTODY`, `TANAGHOM_REVIEWER_KV_{MOUNT,PATH,FIELD}`,
`TANAGHOM_SECRET_DIR`, `TANAGHOM_SECRET_UID`/`_GID`. Defaults match this package.
