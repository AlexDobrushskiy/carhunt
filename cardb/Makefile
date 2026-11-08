# cardb build for the host (bootstrap: `make -C cardb build`, then `cardb init`). Docker builds use the Dockerfile.
# nodynamic + CGO off: pure-Go binary; the AVIF/HEIC decoders would otherwise dlopen system libs via purego.

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
GO      ?= go
BIN     := bin/cardb

.PHONY: build test clean

build:
	CGO_ENABLED=0 $(GO) build -trimpath -tags nodynamic \
		-ldflags="-s -w -X carhunt/cardb/internal/api.Version=$(VERSION)" -o $(BIN) ./cmd/cardb

test:
	$(GO) test -count=1 ./...

clean:
	rm -rf bin
