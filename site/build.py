"""Assemble the Pages artifact: the product page, the docs and the redirects.

    quarto render docs
    python site/build.py public

public/ gets site/ (without its tooling), docs/_site/ as public/docs/, one
redirect page per line of site/redirects.txt, the version from pyproject.toml
and a CNAME. Every link is relative, so the same artifact works at the custom
domain and under the organisation's project path.
"""

import html
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DOMAIN = "beaver.syalia.com"
TOOLING = {"build.py", "check_snippets.py", "redirects.txt"}

REDIRECT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Moved to {new}</title>
<link rel="canonical" href="https://{domain}/{new}">
<meta http-equiv="refresh" content="0; url={new}">
<meta name="robots" content="noindex">
<script>location.replace("{new}" + location.hash)</script>
</head>
<body>
<p>This page moved to <a href="{new}">{new}</a>.</p>
</body>
</html>
"""


def main(out: Path) -> None:
    docs = ROOT / "docs" / "_site"
    if not (docs / "index.html").exists():
        sys.exit("docs/_site/index.html is missing: run `quarto render docs` first")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE, out, ignore=lambda d, names: TOOLING & set(names))
    shutil.copytree(docs, out / "docs")

    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    index = out / "index.html"
    page, count = re.subn(
        r"(<span data-version>)[^<]*(</span>)",
        rf"\g<1>{version}\g<2>",
        index.read_text(),
    )
    index.write_text(page)

    redirects = 0
    for line in (SITE / "redirects.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        old, new = line.split()
        target = out / old
        if target.exists():
            sys.exit(f"redirect {old} would overwrite a real page")
        target.write_text(REDIRECT.format(new=html.escape(new), domain=DOMAIN))
        redirects += 1

    (out / "CNAME").write_text(DOMAIN + "\n")
    (out / ".nojekyll").write_text("")
    print(f"{out}: version {version} in {count} places, {redirects} redirects")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "public").resolve())
