# Build on the native ARM64 runner, on the same AL2023 ABI as the runtime.
# No build credentials, Node, HTTP server, Lambda Web Adapter or secret fetch.
FROM public.ecr.aws/lambda/provided:al2023@sha256:7a99afa4f62c87e039c95dc3e2d307114f35a148ba5e2eb67287a84082521e44 AS build
RUN dnf install -y gcc glibc-devel binutils make tar gzip xz && dnf clean all
WORKDIR /build
RUN curl -fSL https://github.com/jdx/mise/releases/download/v2026.10.3/mise-v2026.10.3-linux-arm64-musl -o /usr/local/bin/mise \
    && echo '1b849098a23ca0b7ec2733bddf243e9d29507779bba4e0e1101eec3c518bc542  /usr/local/bin/mise' | sha256sum -c - \
    && chmod 0755 /usr/local/bin/mise
COPY mise.toml mise.lock ./
ENV MISE_TRUSTED_CONFIG_PATHS=/build MISE_RUSTUP_HOME=/opt/rustup MISE_CARGO_HOME=/opt/cargo
RUN mise install rust
ENV CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_DEBUG=0
COPY infra/aws/tools/lambdas/thundermail_mcp/Cargo.toml infra/aws/tools/lambdas/thundermail_mcp/Cargo.lock ./
COPY infra/aws/tools/lambdas/thundermail_mcp/src ./src
RUN mise exec rust -- cargo test --locked && mise exec rust -- cargo build --locked --release \
    && install -m 755 target/release/thundermail-native-read /build/bootstrap
# checkov:skip=CKV_DOCKER_2:Native Lambda Runtime API client has no listener; Docker health is not Lambda readiness. See README.md.
FROM public.ecr.aws/lambda/provided:al2023@sha256:7a99afa4f62c87e039c95dc3e2d307114f35a148ba5e2eb67287a84082521e44
COPY --chmod=0755 --from=build /build/bootstrap /var/runtime/bootstrap
COPY --chmod=0644 infra/aws/tools/lambdas/thundermail_mcp/LICENSE.upstream /usr/share/licenses/thundermail/LICENSE.upstream
COPY --chmod=0644 infra/aws/tools/lambdas/thundermail_mcp/extraction.json /usr/share/licenses/thundermail/extraction.json
# COPY's numeric chmod also creates missing destination parents with 0644.
# Only this new notice directory needs traversal; AL2023 ancestors are 0755.
RUN chmod 0755 /usr/share/licenses/thundermail
# Local Docker defaults to non-root; world-readable/executable files also allow Lambda's assigned UID.
USER 10001:10001
ENTRYPOINT ["/var/runtime/bootstrap"]
