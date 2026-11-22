# The hosted Vyomi MCP server (https://vyomi.cloud/mcp), as the /mcp component of the portal's DigitalOcean app
# (HOSTED-MCP-DESIGN.md §5, D-H2 = B'). Published to ghcr.io/vyomi-cloud/mcp-hosted:<version>, linux/amd64 only
# (App Platform runs amd64).
#
#   docker build -f deploy/mcp-hosted/Dockerfile -t mcp-hosted:dev .          # from the repo root
#   docker run --rm -p 8080:8080 mcp-hosted:dev
#   tools/mcp-hosted-smoke.sh http://localhost:8080/mcp
#
# The image carries the MCP server and nothing else: no shell, no package manager, no writable layer it uses, and
# a non-root user. The server itself has no outbound network and no file access (plan §4), so the only thing it
# needs is the embedded knowledge, which is compiled in by go:embed.

# ── build ────────────────────────────────────────────────────────────────────
FROM golang:1.26-bookworm AS build
WORKDIR /src

# The Go module is cmd/vyomi (there is no module at the repo root), and it is stdlib-only: no go.sum, nothing to
# download, so the whole build is this one copy plus one compile.
COPY cmd/vyomi/ ./cmd/vyomi/
WORKDIR /src/cmd/vyomi
ARG VERSION=dev
ARG REVISION=unknown
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/vyomi .

# A build that cannot serve is not worth pushing: check the binary answers before it reaches the runtime stage.
RUN /out/vyomi mcp --help | grep -q -- --hosted

# ── runtime ──────────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static-debian12:nonroot
ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="Vyomi hosted MCP server" \
      org.opencontainers.image.description="Read-only Model Context Protocol server for the Vyomi local cloud simulator, over Streamable HTTP." \
      org.opencontainers.image.source="https://github.com/vyomi-cloud/appliance" \
      org.opencontainers.image.url="https://vyomi.cloud/mcp" \
      org.opencontainers.image.licenses="Proprietary" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
COPY --from=build /out/vyomi /vyomi
USER nonroot:nonroot
EXPOSE 8080
# App Platform sets PORT; --listen falls back to :$PORT and then :8080, so both work.
ENTRYPOINT ["/vyomi", "mcp", "--hosted"]
