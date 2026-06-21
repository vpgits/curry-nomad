# Next.js frontend (the Nora chat UI). Build context = apps/web.
#
#   docker build -t curry-nomad-web apps/web
# Usually built via the repo-root docker-compose.yml (the `web` service).
#
# NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time, so the
# backend URL is a build arg — and it must be the address the *browser* uses
# (http://localhost:2024, the host-published port), not a compose-internal name.

FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app

# -----------------------------
# Dependencies (cached on the lockfile)
# -----------------------------
FROM base AS deps
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# -----------------------------
# Build
# -----------------------------
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:2024
ARG NEXT_PUBLIC_ASSISTANT_ID=nora
# The /inventory page calls the operations REST API directly from the browser, so this is the
# host-published address (http://localhost:8000), not the compose-internal service name.
ARG NEXT_PUBLIC_OPS_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_ASSISTANT_ID=$NEXT_PUBLIC_ASSISTANT_ID \
    NEXT_PUBLIC_OPS_API_URL=$NEXT_PUBLIC_OPS_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# -----------------------------
# Runtime (next start; respects PORT)
# -----------------------------
FROM base AS run
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.mjs ./next.config.mjs
EXPOSE 3000
CMD ["pnpm", "start"]
