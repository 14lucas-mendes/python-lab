"""Local echo bot: no accounts, tokens or external messaging services."""

import argparse


def echo(text: str) -> str:
    return f"Eco: {text}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot de eco local")
    parser.add_argument("message", help="Mensagem para responder localmente")
    args = parser.parse_args()
    print(echo(args.message))


if __name__ == "__main__":
    main()
