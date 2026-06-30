"""Export the FastAPI app's OpenAPI schema as JSON to stdout.

Used by `make openapi` to keep the checked-in `openapi.json` in sync with the
live app. Run: `uv run python -m simulation_harness.openapi_export > openapi.json`
"""

import json
import sys

from simulation_harness.main import app


def main() -> None:
    schema = app.openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
