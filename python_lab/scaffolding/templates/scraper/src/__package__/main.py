"""Extract a title from local HTML using only the standard library."""

import argparse
from html.parser import HTMLParser
from pathlib import Path


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._inside_title = False
        self._complete = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and not self._complete:
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._inside_title:
            self._inside_title = False
            self._complete = True

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.parts.append(data)


def extract_title(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrair título de HTML local")
    parser.add_argument("path", type=Path, help="Arquivo HTML local em UTF-8")
    args = parser.parse_args()
    print(extract_title(args.path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
