# syntax=docker/dockerfile:1
# Exact pin: a deploy that builds from cached layers without pulling would keep a stale floating tag.
FROM node:22.23.4-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:22.23.4-alpine AS run
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
USER node
ENV HOST=0.0.0.0 PORT=4323 NODE_ENV=production CARDB_URL=http://cardb:8480
EXPOSE 4323
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:4323/health >/dev/null || exit 1
CMD ["node", "./dist/server/entry.mjs"]
