FROM node:22-slim
WORKDIR /app

COPY package.json pnpm-workspace.yaml ./
COPY packages/components/package.json ./packages/components/
COPY packages/vscode/package.json ./packages/vscode/

RUN corepack enable pnpm && \
    pnpm install --frozen-lockfile

COPY packages/ packages/

CMD ["echo", "asya-ui stub image"]
