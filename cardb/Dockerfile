# Builds natively on the build host and cross-compiles for the target (default linux/amd64).
FROM --platform=$BUILDPLATFORM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY api ./api
COPY cmd ./cmd
COPY internal ./internal
ARG TARGETOS=linux
ARG TARGETARCH=amd64
# Pass e.g. --build-arg VERSION=$(git describe --tags --always): the build context has no .git.
ARG VERSION=dev
# nodynamic: the AVIF/HEIC decoders would otherwise dlopen system libs via purego, which makes the
# binary dynamically linked (it then can't start on distroless/static). The guard fails the build if that regresses.
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -tags nodynamic \
      -ldflags="-s -w -X ev-listings/internal/api.Version=${VERSION}" -o /out/cardb ./cmd/cardb \
 && if readelf -l /out/cardb | grep -q INTERP; then echo "cardb is dynamically linked" >&2; exit 1; fi \
 && mkdir -p /out/data

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/cardb /usr/local/bin/cardb
COPY --from=build --chown=10001:10001 /out/data /data
ENV CARDB_DATA_DIR=/data \
    CARDB_LISTEN=:8480
USER 10001
EXPOSE 8480
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["cardb", "healthcheck"]
ENTRYPOINT ["cardb"]
CMD ["serve"]
