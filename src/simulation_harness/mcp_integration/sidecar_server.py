"""Sidecar MCP server that runs on a user-specified port."""

import asyncio
import socket as _socket
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request, Response
from starlette.responses import Response as StarletteResponse

from simulation_harness.config.models import MCPConfig, TransportType
from simulation_harness.utils.errors import PortInUseError
from simulation_harness.utils.logging import get_logger

if TYPE_CHECKING:
    from simulation_harness.core.simulation_instance import SimulationInstance

logger = get_logger(__name__)


DEFAULT_SIDECAR_HOST = "localhost"


def _check_port_available(port: int, host: str = DEFAULT_SIDECAR_HOST) -> None:
    """Verify the port is not already bound on the interface we intend to use.

    ``host`` must match the address uvicorn will bind, or the probe stops being
    a meaningful check.

    Raises:
        PortInUseError: If the port is already in use.
    """
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        raise PortInUseError(f"Port {port} is already in use")
    finally:
        sock.close()


class SidecarMCPServer:
    """Runs a minimal FastAPI+uvicorn server with MCP transport on a given port."""

    def __init__(
        self,
        instance: "SimulationInstance",
        port: int,
        mcp_config: MCPConfig,
        host: str = DEFAULT_SIDECAR_HOST,
    ) -> None:
        self._instance = instance
        self._port = port
        self._mcp_config = mcp_config
        self._host = host
        self._uvicorn_server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the sidecar server on the configured port.

        Raises:
            PortInUseError: If the port is already in use.
        """
        _check_port_available(self._port, self._host)

        app = self._create_app()
        config = uvicorn.Config(
            app,
            # Bind address comes from server.host in harness.yaml. Deployments
            # that need the sidecar reachable off-box set 0.0.0.0 there and
            # supply their own network-level isolation (see DESIGN.md); the
            # default keeps it on loopback.
            host=self._host,
            port=self._port,
            log_level="warning",
            log_config=None,
        )
        self._uvicorn_server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._uvicorn_server.serve())

        # Wait for the server to finish startup (or fail)
        deadline = asyncio.get_running_loop().time() + 5.0
        while not self._uvicorn_server.started:
            if self._server_task.done():
                exc = self._server_task.exception()
                if exc:
                    import errno as _errno

                    if isinstance(exc, OSError) and exc.errno in (
                        _errno.EADDRINUSE,
                        _errno.EACCES,
                    ):
                        raise PortInUseError(
                            f"Port {self._port} is already in use"
                        ) from exc
                    raise exc
                break
            if asyncio.get_running_loop().time() > deadline:
                raise RuntimeError(
                    f"Sidecar MCP server on port {self._port} failed to start within 5 s"
                )
            await asyncio.sleep(0.05)

        logger.info(f"Sidecar MCP server started on {self._host}:{self._port}")

    async def stop(self) -> None:
        """Stop the sidecar server."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._server_task.cancel()
        logger.info(f"Sidecar MCP server on port {self._port} stopped")

    def _create_app(self) -> FastAPI:
        """Build a minimal FastAPI app with the configured MCP transport."""
        from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper

        app = FastAPI()

        if self._mcp_config.transport == TransportType.SSE:
            from mcp.server.sse import SseServerTransport

            sse_transport = SseServerTransport("/mcp/messages")
            instance = self._instance

            @app.get("/mcp/sse")
            async def mcp_sse(request: Request):
                wrapper = MCPServerWrapper(instance)
                async with sse_transport.connect_sse(
                    request.scope, request.receive, request._send
                ) as (read_stream, write_stream):
                    await wrapper.server.run(
                        read_stream,
                        write_stream,
                        wrapper.server.create_initialization_options(),
                    )
                return StarletteResponse()

            @app.post("/mcp/messages")
            async def mcp_messages(request: Request):
                captured: dict = {"status": 202, "headers": [], "body": b""}

                async def _capture(message: dict) -> None:
                    if message["type"] == "http.response.start":
                        captured["status"] = message["status"]
                        captured["headers"] = message.get("headers", [])
                    elif message["type"] == "http.response.body":
                        captured["body"] = message.get("body", b"")

                await sse_transport.handle_post_message(
                    request.scope, request.receive, _capture
                )
                return Response(
                    content=captured["body"],
                    status_code=captured["status"],
                    headers={k.decode(): v.decode() for k, v in captured["headers"]},
                )

        elif self._mcp_config.transport == TransportType.STREAMABLE_HTTP:
            from simulation_harness.mcp_integration.transport import (
                handle_streamable_http_request,
            )

            instance = self._instance

            @app.post("/mcp")
            async def mcp_streamable(request: Request):
                wrapper = MCPServerWrapper(instance)
                return await handle_streamable_http_request(
                    wrapper.server, request.scope, request.receive
                )

        return app


# Made with Bob
