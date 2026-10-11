"""Bound CI failure details before GitHub workflow-command escaping."""

import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"(.)\1{79,}", lambda match: match.group(1) * 20 + "[repeated]", text)
    lines = [line[:240] for line in text.splitlines()]
    return "\n".join(lines)[:limit]


def summarize(log: Path, junit: Path | None = None) -> str:
    sections = []
    if junit is not None:
        try:
            tree = ET.parse(junit)
            for case in tree.iter("testcase"):
                for failure in list(case.findall("failure")) + list(case.findall("error")):
                    name = case.get("classname", "") + "::" + case.get("name", "")
                    sections.append(_compact(name, 240) + "\n" + _compact(failure.get("message", ""), 400)
                                    + "\n" + _compact(failure.text or "", 450))
                    if len(sections) == 4:
                        break
                if len(sections) == 4:
                    break
        except (OSError, ET.ParseError):
            pass  # A failed/crashed pytest run may not finish its XML report.
    output = log.read_text(encoding="utf-8", errors="replace")
    failures = [line for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))]
    sections.append("Failure summary:\n" + _compact("\n".join(failures[:8]), 1200))
    sections.append("Log tail:\n" + _compact("\n".join(output.splitlines()[-25:]), 1800))
    return "\n".join(sections)[:6000]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args()
    print(summarize(args.log, args.junit))


if __name__ == "__main__":
    main()
