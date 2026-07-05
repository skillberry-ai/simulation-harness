#!/usr/bin/env python3
"""CLI to export the full generated skill bundle from the harness.

Calls ``GET /api/v1/simulation/bundle`` for the active simulation and prints the
JSON envelope (name + verbatim files + per-file uncompressed sizes) to stdout.

With ``--gzip`` it requests a compressed response (``Accept-Encoding: gzip``),
reports the compression ratio on stderr, then decompresses and proceeds. With
``--output-dir`` it also reconstructs the verbatim files under ``<dir>/<name>/``
(the round-trip / restore use case).
"""

import argparse
import gzip
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_server_url(config: dict) -> str:
    host = config.get("server", {}).get("host", "localhost")
    port = config.get("server", {}).get("port", 8086)
    if host == "0.0.0.0":
        host = "localhost"
    return f"http://{host}:{port}"


def human_size(n: int) -> str:
    """Human-readable byte count, e.g. 61.0 KB / 1.4 MB."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{n} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def write_bundle_files(bundle: dict, output_dir: Path) -> Path:
    """Write each verbatim file to ``<output_dir>/<name>/<filename>``.

    Returns the directory written to.
    """
    target = output_dir / bundle["name"]
    target.mkdir(parents=True, exist_ok=True)
    for filename, contents in bundle["files"].items():
        (target / filename).write_text(contents)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the full generated skill bundle for the active simulation."
    )
    parser.add_argument(
        "--gzip",
        action="store_true",
        help="Request a gzip-compressed response and report the compression ratio",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Reconstruct the bundle's verbatim files under <output-dir>/<name>/",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to harness.yaml (default: config/harness.yaml relative to project root)",
    )
    args = parser.parse_args()

    config_path: Path = (
        args.config
        if args.config
        else Path(__file__).parent.parent / "config" / "harness.yaml"
    )

    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)
    server_url = get_server_url(config)

    url = f"{server_url}/api/v1/simulation/bundle"
    # urllib does NOT auto-decompress, so we only advertise gzip when asked and
    # decompress the body ourselves below.
    accept_encoding = "gzip" if args.gzip else "identity"
    req = Request(url, headers={"Accept-Encoding": accept_encoding}, method="GET")
    try:
        with urlopen(req) as response:
            raw = response.read()
            content_encoding = response.headers.get("Content-Encoding", "")
    except HTTPError as e:
        print(f"Error {e.code}: {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)

    if content_encoding == "gzip":
        payload = gzip.decompress(raw)
        ratio = len(payload) / len(raw) if raw else 0.0
        print(
            f"gzip: {human_size(len(raw))} compressed  <-  "
            f"{human_size(len(payload))} uncompressed  ({ratio:.1f}x)",
            file=sys.stderr,
        )
    else:
        if args.gzip:
            print("note: server returned an uncompressed response", file=sys.stderr)
        payload = raw

    bundle = json.loads(payload)
    print(json.dumps(bundle, indent=2))

    if args.output_dir:
        target = write_bundle_files(bundle, args.output_dir)
        print(f"wrote {len(bundle['files'])} files to {target}/", file=sys.stderr)


if __name__ == "__main__":
    main()
