// Command cardb is the ev-listings server and its CLI client in one binary.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"carhunt/cardb/internal/cli"
	"carhunt/cardb/internal/server"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	os.Exit(run(ctx, os.Args[1:]))
}

func run(ctx context.Context, args []string) int {
	if len(args) > 0 {
		var err error
		switch args[0] {
		case "serve":
			err = server.Main(ctx, args[1:])
		case "backup":
			err = server.Backup(args[1:])
		case "healthcheck":
			err = server.Healthcheck()
		default:
			return cli.Run(ctx, args, os.Stdout, os.Stderr)
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "cardb %s: %v\n", args[0], err)
			return cli.ExitError
		}
		return cli.ExitOK
	}
	return cli.Run(ctx, args, os.Stdout, os.Stderr)
}
