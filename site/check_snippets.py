"""Run every snippet on the product page and compare it with the output shown.

Each <pre data-snippet="name"> in site/index.html runs as is, in its own empty
directory, with the Python running this script. Its stdout must equal the text
of the <div data-out="name"> beside it. Exit code 1 lists the ones that differ.
"""

import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PAGE = Path(__file__).with_name("index.html")
TIMEOUT = 60


def text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def main() -> int:
    page = PAGE.read_text()
    snippets = dict(
        re.findall(r'<pre[^>]*data-snippet="(\w+)"[^>]*>(.*?)</pre>', page, re.S)
    )
    outputs = dict(
        re.findall(r'<div[^>]*data-out="(\w+)"[^>]*>(.*?)</div>', page, re.S)
    )
    if not snippets or snippets.keys() != outputs.keys():
        print(f"snippets {sorted(snippets)} and outputs {sorted(outputs)} do not match")
        return 1
    failed = []
    for name, code in snippets.items():
        expected = text(outputs[name]).strip()
        with tempfile.TemporaryDirectory() as cwd:
            try:
                run = subprocess.run(
                    [sys.executable, "-I", "-c", text(code)],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT,
                )
                got, err = run.stdout.strip(), run.stderr.strip()
                ok = run.returncode == 0 and got == expected
            except subprocess.TimeoutExpired:
                got, err, ok = "", f"timed out after {TIMEOUT} s", False
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            failed.append(name)
            print(
                f"  expected: {expected!r}\n  got:      {got!r}\n  stderr:   {err[-2000:]}"
            )
    print(f"{len(snippets) - len(failed)} of {len(snippets)} snippets match")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
