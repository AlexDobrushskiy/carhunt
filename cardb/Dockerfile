# cardb: static pure-Go binary on distroless. Build context = this directory (cardb/).
# Base images are pinned by tag + digest: compose builds from cached layers without pulling, so a floating tag goes stale.
# Bump: docker buildx imagetools inspect <image:tag> → copy the index digest.

# Builds natively on the build host and cross-compiles for the target platform (BuildKit sets TARGETOS/TARGETARCH).
FROM --platform=$BUILDPLATFORM golang:1.26.10-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY api ./api
COPY cmd ./cmd
COPY internal ./internal
ARG TARGETOS
ARG TARGETARCH
# Pass e.g. --build-arg VERSION=$(git describe --tags --always): the build context has no .git.
ARG VERSION=dev
# nodynamic: the AVIF/HEIC decoders would otherwise dlopen system libs via purego, which makes the
# binary dynamically linked (it then can't start on distroless/static). The guard fails the build if that regresses.
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -tags nodynamic \
      -ldflags="-s -w -X carhunt/cardb/internal/api.Version=${VERSION}" -o /out/cardb ./cmd/cardb \
 && if readelf -l /out/cardb | grep -q INTERP; then echo "cardb is dynamically linked" >&2; exit 1; fi \
 && mkdir -p /out/data

FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
COPY --from=build /out/cardb /usr/local/bin/cardb
COPY --from=build --chown=10001:10001 /out/data /data
# Inside the container cardb listens on all interfaces; compose publishes the port on 127.0.0.1 only.
ENV CARDB_DATA_DIR=/data \
    CARDB_LISTEN=0.0.0.0:8484
USER 10001:10001
EXPOSE 8484
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["cardb", "healthcheck"]
ENTRYPOINT ["cardb"]
CMD ["serve"]
