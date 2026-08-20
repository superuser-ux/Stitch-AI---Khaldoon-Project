# syntax=docker/dockerfile:1
# #338 — reproducible, exact-SHA-traceable V2 workbench image. Multi-stage: a builder installs from the
# frozen lockfile with a pinned pnpm and produces a Next standalone server; a minimal runner ships only
# the standalone server + static + public assets (no dev dependencies, no source tree, no host recipe).
# Build context is `workbench/` (a self-contained pnpm project). Build with:
#   docker build -f workbench/Dockerfile --build-arg GIT_SHA=<40-char sha> -t tanaghom-acc-workbench:<sha> workbench

# ---- builder ----
FROM node:22-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Pinned package manager via Corepack — deterministic, no floating resolution.
RUN corepack enable && corepack prepare pnpm@10.15.1 --activate
# Install with the frozen lockfile first (cache-friendly, no regeneration).
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
# Build the standalone output from the exact-SHA source.
COPY . .
RUN pnpm build

# ---- runner (minimal, non-root) ----
FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3001 \
    HOSTNAME=0.0.0.0

# Exact-SHA provenance + baked runtime identity (single validated value; see docker-entrypoint.sh).
ARG GIT_SHA=""
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/Kholio/tanaghom" \
      org.opencontainers.image.title="tanaghom-workbench"
ENV TANAGHOM_WORKBENCH_BUILD_SHA="${GIT_SHA}"
RUN printf '%s' "${GIT_SHA}" > /app/BUILD_SHA

# Next standalone deploy layout: the traced server (+ minimal node_modules) sits at the app root; the
# static chunks and public assets are copied alongside it (standalone does not include them).
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Next's standalone dependency tracer over-includes `typescript` (a devDependency). The production
# server never type-checks and never requires it (verified: no runtime `require('typescript')`), so it
# is removed — the runtime image then carries NO dev dependency, only traced production deps.
RUN rm -rf /app/node_modules/typescript

# Explicit numeric non-root user owns the app tree; the standalone server writes nothing at runtime.
RUN groupadd --system --gid 10001 workbench \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home workbench \
 && chmod +x /app/docker-entrypoint.sh \
 && chown -R 10001:10001 /app
USER 10001:10001

EXPOSE 3001
# Readiness proves the server answers its runtime-identity route, not just an open socket. Uses node
# (present in the final image); no curl/wget dependency.
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=15 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3001)+'/api/runtime').then(r=>{process.exit(r.ok?0:1)}).catch(()=>process.exit(1))"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
