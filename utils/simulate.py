#!/usr/bin/env python3
"""CLI to create a simulation in the harness."""

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a simulation in the harness from an OpenAPI JSON file."
    )
    parser.add_argument("openapi_file", type=Path, help="Path to OpenAPI JSON file")
    parser.add_argument("--name", help="Simulation name override (default: spec info.title)")
    parser.add_argument(
        "--regenerate-skill",
        action="store_true",
        help="Force skill regeneration even if one already exists",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to harness.yaml (default: config/harness.yaml relative to project root)",
    )
    args = parser.parse_args()

    config_path: Path = (
        args.config if args.config else Path(__file__).parent.parent / "config" / "harness.yaml"
    )

    if not config_path.exists():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if not args.openapi_file.exists():
        print(f"Error: OpenAPI file not found: {args.openapi_file}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)
    server_url = get_server_url(config)

    with open(args.openapi_file) as f:
        openapi_spec = json.load(f)

    body: dict = {"openapi_spec": openapi_spec, "regenerate_skill": args.regenerate_skill}
    if args.name:
        body["name"] = args.name

    url = f"{server_url}/api/v1/simulation"
    data = json.dumps(body).encode("utf-8")
    import time

    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req) as response:
            declared = json.loads(response.read())
            print(f"Declared: {declared['name']} status={declared['status']}")
    except HTTPError as e:
        body_text = e.read().decode("utf-8")
        print(f"Error {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)

    # Poll until ready or failed
    poll_url = f"{server_url}/api/v1/simulation"
    deadline = time.monotonic() + 180  # 3 min cap
    while time.monotonic() < deadline:
        try:
            with urlopen(Request(poll_url, method="GET")) as resp:
                data = json.loads(resp.read())
                sim_status = data.get("status")
                phase = (data.get("progress") or {}).get("phase")
                print(f"  status={sim_status} phase={phase}")
                if sim_status == "ready":
                    print(json.dumps(data, indent=2))
                    break
                if sim_status == "failed":
                    err = data.get("error") or {}
                    print(
                        f"Simulation creation failed: {err.get('code', 'unknown')} — {err.get('message', '')}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
        except HTTPError as e:
            print(f"Poll error {e.code}: {e.read().decode()}", file=sys.stderr)
            sys.exit(1)
        except URLError as e:
            print(f"Connection error while polling: {e.reason}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
    else:
        print("Simulation did not reach ready within 180s", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
