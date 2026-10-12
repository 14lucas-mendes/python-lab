"""An example command with an explicit entrypoint."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cumprimente alguém.")
    parser.add_argument("--name", default="mundo", help="Nome da pessoa")
    args = parser.parse_args(argv)
    print(f"Olá, {args.name}!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
