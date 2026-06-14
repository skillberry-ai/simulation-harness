"""Integration test fixtures and helpers."""

import time

from fastapi.testclient import TestClient


def poll_until_ready(client: TestClient, timeout: float = 30.0) -> dict:
    """Poll GET /api/v1/simulation until status is ready or failed.

    Returns the final response body. Raises AssertionError on timeout.
    """
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/simulation")
        if resp.status_code != 200:
            time.sleep(0.1)
            continue
        last = resp.json()
        if last["status"] in ("ready", "failed"):
            return last
        time.sleep(0.1)
    raise AssertionError(
        f"Simulation did not reach terminal status within {timeout}s; last={last}"
    )
