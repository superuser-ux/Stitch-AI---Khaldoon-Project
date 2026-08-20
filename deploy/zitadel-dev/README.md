# Private ZITADEL developer pilot

This package implements issue #396 only. It creates a private, persistent ZITADEL v4.16.2 pilot for
developer use. It does **not** enable Tanaghom IAM, create a Tanaghom identity binding, grant product
authority, onboard a real user, or alter UAT/staging/production.

## Boundaries

- Compose project: `tanaghom-zitadel-dev`.
- Services: ZITADEL API, Login V2, PostgreSQL 17, and static Caddy.
- Network: `tanaghom-iam-dev`; no Docker socket, privileged container, or host networking.
- Exposure: only `127.0.0.1:18210 -> caddy:13210` on the VPS.
- External issuer: `http://iam.localhost:13210`, deliberately HTTP and developer-only.
- Secrets: OpenBao KV paths under `tanaghom/dev/zitadel/`; four root-only files in a host-tmpfs
  generation selected by `/run/tanaghom-zitadel/current`. A single atomic symlink rename activates all
  four files together. No secret is passed in environment, labels, Compose interpolation, or argv.
- ZITADEL API and Login V2 run as root inside their isolated containers, matching the official v4 Compose
  bootstrap posture, so they can read root-only files and share the generated Login PAT. They remain
  unprivileged Docker containers: no `privileged`, host network, host PID, or Docker socket access.
- The generated Login V2 client PAT stays in the candidate-owned `login_bootstrap` Docker volume and is
  mounted read-only into Login V2. The PostgreSQL volume is retained by rollback for diagnosis.

## Exact artifacts

`provenance.lock` pins each multi-arch index and expected linux/amd64 child. `provenance.sh` retrieves raw
registry manifests, verifies both digests, and records timestamped evidence. Any mismatch is a hard stop.

## Package and host execution

From an exact clean reviewed commit:

```bash
deploy/zitadel-dev/packaging_test.sh
deploy/zitadel-dev/stage.sh <40-char-merge-sha> /tmp/tanaghom-zitadel
```

Transfer the staged directory and its external manifest digest to `/srv/tanaghom-zitadel`. On the VPS,
run the following exact sequence. The manifest digest comes from the separate
`/tmp/tanaghom-zitadel.manifest.sha256` trust anchor, not from inside the package.

```bash
cd /srv/tanaghom-zitadel
sudo ./preflight.sh <manifest-sha256>
sudo ./provision.sh
sudo ./deploy.sh
sudo ./verify.sh --observe 600
```

`preflight.sh` refuses existing candidate containers, network, volumes, ports, OpenBao objects, custody,
systemd units, runtime files, or ZITADEL-specific images. A shared PostgreSQL/Caddy cache entry is allowed
only at the exact approved linux/amd64 digest; it is never removed or otherwise controlled. Preflight also
captures the current workload/listener baseline.
`provision.sh` snapshots OpenBao, creates only the three KV values plus one read-only policy/AppRole, and
starts the root-only tmpfs materializer. `deploy.sh` re-verifies registry provenance before pulling and
starts only the candidate project. `verify.sh` proves issuer/JWKS/routes, resource limits, loopback-only
exposure, secret metadata, existing-workload identity stability, and the requested ten-minute observation.
Before retaining rendered Compose or inspect evidence, the scanner reads the real masterkey, database
password, bootstrap password, and Login PAT privately and checks their exact bytes against rendered
Compose, container inspect/argv/env/labels/mount metadata, all candidate logs, and candidate evidence.
The same runtime scan runs again after the observation window so late log output cannot evade acceptance.
Cold-start health allows up to five minutes for the resource-capped developer VPS to complete initial
migrations, with a seven-minute hard Compose ceiling. The ZITADEL readiness subprocess loads the committed
non-secret config so its port and TLS scheme match the main server; subprocesses do not inherit
`start-from-init` command flags. On failure,
`deploy.sh` reads bounded container state and the last 2,000 log lines in memory,
checks the actual masterkey, database password, bootstrap password, and generated Login PAT bytes, then
discards every raw string. It retains only typed health fields and fixed-vocabulary category counters;
raw logs and arbitrary runtime error text are never written. The exact rollback proof is then printed.

## Mac access

Starting and maintaining the tunnel is an operator action, outside the host package:

```bash
ssh -N \
  -L 13210:127.0.0.1:18210 \
  -i ~/.ssh/stitch_vps_rebuild_ed25519 \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o BatchMode=yes \
  administrator@155.117.45.45
```

Then open `http://iam.localhost:13210/`. The bootstrap login name is
`zitadel-admin@tanaghom-dev.iam.localhost`. Its password is intentionally not printed or exposed; it
remains at the OpenBao path `tanaghom/dev/zitadel/bootstrap-admin`. Real operator creation and password
rotation are later human actions.

## Rollback

```bash
cd /srv/tanaghom-zitadel
sudo ./rollback.sh
```

Rollback stops/removes only candidate containers and network, disables only the candidate timer, deletes
only journaled ZITADEL AppRole/policy/KV/custody/runtime objects, and verifies candidate residue is absent.
It deletes the Login PAT volume, preserves the candidate PostgreSQL volume when created, and preserves the
pre-change OpenBao snapshot. PASS requires proof that all journaled OpenBao/systemd/custody/runtime objects
and candidate containers/network/PAT volume are absent, the diagnostic PostgreSQL volume and snapshot
remain, and every captured preflight container and Docker network ID is unchanged. It never restores the full snapshot
automatically and never prunes Docker. If exact compensation cannot be proven, it retains the journal and
evidence rather than broadening deletion.

After a proven failed deployment, the retained candidate PostgreSQL volume can be removed before one
explicitly approved retry. This command refuses any candidate container, network, listener, incomplete
journal, attached volume, or non-exact Compose labels, and removes no other object:

```bash
cd /srv/tanaghom-zitadel
sudo ./reset-diagnostic.sh
```
