# ARM64 manifests fetched from the actual registries; SHA256 verified on bytes.
FROM --platform=linux/arm64 public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1@sha256:cd0ad9539cbf223feb1cabd8f4deb7064b6270f185614274b940a36590cdc8f9 AS adapter
FROM --platform=linux/arm64 node:22-bookworm-slim@sha256:b20fe038d9592822dd534600a1ddf467e985178aa3fed60ec441a056c2cc45bd
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=optional --omit=dev --no-audit --no-fund && npm cache clean --force
COPY *.mjs tools-manifest.json ./
ENV NODE_ENV=production AWS_LWA_PORT=8080 AWS_LWA_READINESS_CHECK_PORT=8080 AWS_LWA_READINESS_CHECK_PATH=/health AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS=201 AWS_LWA_INVOKE_MODE=buffered AWS_LWA_ASYNC_INIT=true
USER node
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD node -e "fetch('http://127.0.0.1:8080/health', {signal: AbortSignal.timeout(2000)}).then(r => process.exit(r.status === 200 ? 0 : 1)).catch(() => process.exit(1))"
CMD ["node", "main.mjs"]
