FROM node:22-slim
WORKDIR /app

COPY package.json pnpm-workspace.yaml ./
COPY packages/ packages/

RUN corepack enable pnpm && \
    pnpm install --frozen-lockfile || true

CMD ["echo", "asya-ui stub image"]
