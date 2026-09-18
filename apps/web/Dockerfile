# Follows the official Next.js Docker example (examples/with-docker), reduced to npm.
# The current Node.js LTS, as listed on nodejs.org and published on Docker Hub.
ARG NODE_VERSION=24.21.0-slim

# ---- Stage 1: install dependencies from the lockfile ----
FROM node:${NODE_VERSION} AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ---- Stage 2: build the standalone server ----
FROM node:${NODE_VERSION} AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so the API URL is
# a build argument: setting it on the running container has no effect.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Stage 3: run ----
FROM node:${NODE_VERSION} AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

COPY --from=builder --chown=node:node /app/public ./public
RUN mkdir .next && chown node:node .next
# output: "standalone" traces only the files the server needs.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# Non-root user shipped with the official image.
USER node
EXPOSE 3000
CMD ["node", "server.js"]
