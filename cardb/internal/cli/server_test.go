package cli_test

import (
	"io"
	"log/slog"
	"net/http/httptest"
	"testing"

	"carhunt/cardb/internal/server"
	"carhunt/cardb/internal/store"
)

// startServer runs the real API over a temp data dir and returns its URL and token.
func startServer(t *testing.T) (string, string) {
	t.Helper()
	slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	st, err := store.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(server.NewHandler(st, map[string]string{"agents": "tok-cli-agents"}))
	t.Cleanup(func() {
		srv.Close()
		st.Close()
	})
	return srv.URL, "tok-cli-agents"
}
