FROM node:24-alpine

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.24.0 --activate
COPY . .
RUN pnpm install --frozen-lockfile

EXPOSE 5175
CMD ["pnpm", "exec", "vite", "--host", "0.0.0.0", "--port", "5175"]
