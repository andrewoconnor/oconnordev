# Build on the native ARM64 runner, on the same AL2023 ABI as the runtime.
# No build credentials, Node, HTTP server, Lambda Web Adapter or secret fetch.
FROM public.ecr.aws/lambda/provided:al2023@sha256:7a99afa4f62c87e039c95dc3e2d307114f35a148ba5e2eb67287a84082521e44 AS build
RUN dnf install -y gcc glibc-devel binutils make tar gzip xz && dnf clean all
WORKDIR /build
RUN curl -fSL https://static.rust-lang.org/dist/rust-1.90.0-aarch64-unknown-linux-gnu.tar.xz -o rust.tar.xz \
    && echo '59f1883fcdd2d7243d2fd1ed19f22e05219251227abacfa3d656aebfbcc5e838  rust.tar.xz' | sha256sum -c - \
    && tar -xf rust.tar.xz \
    && ./rust-1.90.0-aarch64-unknown-linux-gnu/install.sh --prefix=/opt/rust --components=rustc,cargo,rust-std-aarch64-unknown-linux-gnu --disable-ldconfig \
    && rm -rf rust.tar.xz rust-1.90.0-aarch64-unknown-linux-gnu
ENV PATH="/opt/rust/bin:${PATH}" CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_DEBUG=0
COPY infra/aws/tools/lambdas/thundermail_mcp/Cargo.toml infra/aws/tools/lambdas/thundermail_mcp/Cargo.lock ./
COPY infra/aws/tools/lambdas/thundermail_mcp/src ./src
RUN cargo test --locked && cargo build --locked --release \
    && install -m 755 target/release/thundermail-native-read /build/bootstrap
FROM public.ecr.aws/lambda/provided:al2023@sha256:7a99afa4f62c87e039c95dc3e2d307114f35a148ba5e2eb67287a84082521e44
COPY --from=build /build/bootstrap /var/runtime/bootstrap
COPY infra/aws/tools/lambdas/thundermail_mcp/LICENSE.upstream /usr/share/licenses/thundermail/LICENSE.upstream
COPY infra/aws/tools/lambdas/thundermail_mcp/extraction.json /usr/share/licenses/thundermail/extraction.json
ENTRYPOINT ["/var/runtime/bootstrap"]
