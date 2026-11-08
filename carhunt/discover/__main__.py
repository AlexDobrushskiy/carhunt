"""`python -m carhunt.discover sweep …` — same as `carhunt sweep …` (works before core's dispatcher is installed)."""
import argparse
import sys

from carhunt.discover import cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="carhunt")
    cli.register(p.add_subparsers(dest="group", required=True))
    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
