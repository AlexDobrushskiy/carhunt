"""`python -m carhunt.orchestrate …`: this package's CLI groups without the core dispatcher."""
import argparse
import sys

from .cli import register


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="carhunt")
    register(p.add_subparsers(dest="group", required=True))
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
