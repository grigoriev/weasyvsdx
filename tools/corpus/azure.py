"""The Visio diagrams of the Azure Architecture Center, kept outside the repository.

Usage: azure.py list CHECKOUT    write corpus/azure.json from a checkout of MicrosoftDocs/architecture-center
       azure.py fetch [--only TEXT]  download the diagrams of corpus/azure.json into the cache

The documentation links each diagram on arch-center.azureedge.net; the files are not in its repository, and
the Azure icons inside them may be copied for diagrams and documentation only. So the repository holds only
the list, with the SHA-256 of each file, and fetch keeps the files in the cache: WEASYVSDX_CACHE, by default
~/.cache/weasyvsdx. A file in the cache with the right hash is never downloaded again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "corpus" / "azure.json"
LINK = re.compile(r"https://arch-center\.azureedge\.net/[A-Za-z0-9._/-]+\.vsdx")
TIMEOUT = 60  # seconds per download


def cache() -> Path:
    """The cache directory of the downloaded diagrams and their references."""
    return Path(os.environ.get("WEASYVSDX_CACHE") or Path.home() / ".cache" / "weasyvsdx")


def download(url: str) -> bytes:
    if not url.startswith("https://arch-center.azureedge.net/"):
        raise SystemExit(f"not a diagram of the Architecture Center: {url}")
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        data: bytes = response.read()
        return data


def name(url: str) -> str:
    """The corpus name of a diagram: azure- and its file name, without the suffix."""
    return "azure-" + url.rsplit("/", 1)[1].removesuffix(".vsdx")


def make_list(checkout: Path) -> int:
    """Every diagram the documentation links, with its hash, downloaded into the cache on the way."""
    docs = checkout / "docs"
    urls = sorted({match for path in docs.rglob("*") if path.suffix in (".md", ".yml") for match in LINK.findall(path.read_text(errors="replace"))})
    target = cache() / "azure"
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for url in urls:
        try:
            data = download(url)
        except OSError as e:
            print(f"{url}: {e}", file=sys.stderr)
            continue
        (target / f"{name(url)}.vsdx").write_bytes(data)
        entries.append({"name": name(url), "url": url, "sha256": hashlib.sha256(data).hexdigest()})
        print(f"{name(url)}: {len(data)} bytes", flush=True)
    LIST.write_text(json.dumps(entries, indent=1) + "\n")
    print(f"{len(entries)} of {len(urls)} diagrams in {LIST.relative_to(ROOT)}")
    return 0


def fetch(only: str) -> int:
    """Download each diagram of the list that the cache lacks or holds with another hash."""
    target = cache() / "azure"
    target.mkdir(parents=True, exist_ok=True)
    failed = 0
    for entry in json.loads(LIST.read_text()):
        if only not in entry["name"]:
            continue
        path = target / f"{entry['name']}.vsdx"
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
            continue
        try:
            data = download(entry["url"])
        except OSError as e:
            print(f"{entry['name']}: {e}", file=sys.stderr)
            failed += 1
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            # Microsoft updates a diagram now and then: azure.py list takes the new version
            print(f"{entry['name']}: the hash differs from corpus/azure.json, skipped", file=sys.stderr)
            failed += 1
            continue
        path.write_bytes(data)
        print(f"{entry['name']}: downloaded", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="write corpus/azure.json")
    listing.add_argument("checkout", type=Path, help="a checkout of MicrosoftDocs/architecture-center")
    fetching = commands.add_parser("fetch", help="download the diagrams into the cache")
    fetching.add_argument("--only", default="", help="fetch only the names that contain this text")
    args = parser.parse_args()
    if args.command == "list":
        return make_list(args.checkout)
    return fetch(args.only)


if __name__ == "__main__":
    sys.exit(main())
