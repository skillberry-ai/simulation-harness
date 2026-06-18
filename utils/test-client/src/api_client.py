"""REST API client for simulation harness."""

import time
from typing import Any, Optional

import httpx
from pydantic import BaseModel


class APIResponse(BaseModel):
    """Standardized API response."""
    
    success: bool
    status_code: int
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float


class HarnessAPIClient:
    """Client for harness REST API."""
    
    def __init__(self, base_url: str, timeout: float = 600.0):
        """Initialize API client.

        Args:
            base_url: Base URL of harness (e.g., http://localhost:8086)
            timeout: Request timeout in seconds (default: 600.0 for skill generation)
        """
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def health_check(self) -> APIResponse:
        """Check harness health.
        
        Returns:
            APIResponse with health status
        """
        start = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/health")
            duration_ms = (time.time() - start) * 1000
            
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def create_simulation(
        self,
        openapi_spec: dict[str, Any],
        name: str | None = None,
        regenerate_skill: bool = False,
    ) -> APIResponse:
        """Create a new simulation.
        
        Args:
            openapi_spec: OpenAPI specification dictionary
            regenerate_skill: Whether to regenerate skill
            
        Returns:
            APIResponse with simulation details
        """
        start = time.time()
        try:
            payload: dict[str, Any] = {
                "openapi_spec": openapi_spec,
                "regenerate_skill": regenerate_skill,
            }
            if name:
                payload["name"] = name
            response = await self.client.post(
                f"{self.base_url}/api/v1/simulation",
                json=payload,
            )
            duration_ms = (time.time() - start) * 1000
            
            return APIResponse(
                success=response.status_code == 202,
                status_code=response.status_code,
                data=response.json() if response.status_code == 202 else None,
                error=None if response.status_code == 202 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def get_simulation(self) -> APIResponse:
        """Get current simulation status.
        
        Returns:
            APIResponse with simulation details
        """
        start = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/simulation")
            duration_ms = (time.time() - start) * 1000
            
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def delete_simulation(self) -> APIResponse:
        """Delete current simulation.
        
        Returns:
            APIResponse with deletion status
        """
        start = time.time()
        try:
            response = await self.client.delete(f"{self.base_url}/api/v1/simulation")
            duration_ms = (time.time() - start) * 1000
            
            return APIResponse(
                success=response.status_code == 204,
                status_code=response.status_code,
                data=None,
                error=None if response.status_code == 204 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def reset_session(self) -> APIResponse:
        """Reset simulation session.
        
        Returns:
            APIResponse with reset status
        """
        start = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/simulation/reset"
            )
            duration_ms = (time.time() - start) * 1000
            
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def get_simulation_state(self, thread_id: str = "default") -> APIResponse:
        """Get current simulation state snapshot.
        
        Args:
            thread_id: Thread identifier to get state for
        
        Returns:
            APIResponse with simulation state data
        """
        start = time.time()
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/simulation/state",
                params={"thread_id": thread_id},
            )
            duration_ms = (time.time() - start) * 1000

            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False,
                status_code=0,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )
    
    async def get_simulation_schema(self) -> APIResponse:
        """Get JSON Schema for the active skill's database.

        Returns:
            APIResponse with schema dict
        """
        start = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/simulation/schema")
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False, status_code=0, data=None, error=str(e), duration_ms=duration_ms
            )

    async def get_simulation_database(self) -> APIResponse:
        """Get on-disk database (db.json) for the active skill.

        Returns:
            APIResponse with database dict
        """
        start = time.time()
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/simulation/database")
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False, status_code=0, data=None, error=str(e), duration_ms=duration_ms
            )

    async def put_simulation_database(self, data: dict) -> APIResponse:
        """Replace on-disk database (db.json) and reset the simulation.

        Args:
            data: New database content; must validate against the skill's schema.json

        Returns:
            APIResponse with confirmation message
        """
        start = time.time()
        try:
            response = await self.client.put(
                f"{self.base_url}/api/v1/simulation/database",
                json=data,
            )
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=response.status_code == 200,
                status_code=response.status_code,
                data=response.json() if response.status_code == 200 else None,
                error=None if response.status_code == 200 else response.text,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return APIResponse(
                success=False, status_code=0, data=None, error=str(e), duration_ms=duration_ms
            )

    async def poll_until_ready(self, timeout: float = 60.0) -> APIResponse:
        """Poll GET /simulation until status is ready or failed.

        Args:
            timeout: Maximum seconds to wait before raising TimeoutError

        Returns:
            APIResponse with final simulation details (status ready or failed)

        Raises:
            TimeoutError: If simulation does not reach ready/failed within timeout
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = await self.get_simulation()
            if resp.data and resp.data.get("status") in ("ready", "failed"):
                return resp
            time.sleep(0.5)
        raise TimeoutError(f"Simulation did not reach ready/failed within {timeout}s")

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

# Made with Bob
