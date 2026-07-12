"""Transport mounting for MCP server."""

from weakref import WeakSet

from fastapi import FastAPI
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.responses import Response
from starlette.types import Message, Receive, Scope

from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.config.models import MCPConfig, TransportType
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)

# Track which apps have transports mounted (per-app, not global)
_mounted_apps: WeakSet[FastAPI] = WeakSet()


async def handle_streamable_http_request(
    server: Server,
    scope: Scope,
    receive: Receive,
) -> Response:
    """Serve a single MCP Streamable HTTP request through the SDK session manager.

    The MCP SDK's ``StreamableHTTPServerTransport`` requires an ``mcp_session_id``
    and must be driven by ``app.run()`` running concurrently with the request
    handler — coordination that ``StreamableHTTPSessionManager`` owns. We run it
    in **stateless** mode: each request gets a fresh transport with no session
    tracking, which matches the harness model (one global simulation whose
    session state lives on the ``SimulationInstance``, not the MCP transport) and
    avoids cross-request session affinity behind a gateway.

    The session manager writes the full HTTP response via the ASGI ``send``
    callable. We capture those messages and return them as a Starlette
    ``Response`` so the FastAPI route can return it normally — otherwise FastAPI
    would emit a second response ("Received multiple http.response.start"). This
    mirrors the SSE ``/mcp/messages`` handler.

    Args:
        server: The ``mcp.server.Server`` bound to the active simulation.
        scope: ASGI scope.
        receive: ASGI receive callable.

    Returns:
        The MCP response captured from the transport.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    captured: dict = {"status": 200, "headers": [], "body": bytearray()}

    async def _capture_send(message: Message) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            captured["body"].extend(message.get("body", b""))

    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, _capture_send)

    return Response(
        content=bytes(captured["body"]),
        status_code=captured["status"],
        headers={k.decode(): v.decode() for k, v in captured["headers"]},
    )


def mount_sse_transport(app: FastAPI, wrapper: MCPServerWrapper) -> None:
    """Mount SSE transport to FastAPI app.

    Args:
        app: FastAPI application
        wrapper: MCP server wrapper

    Raises:
        ValueError: If a transport is already mounted on this app
    """
    if app in _mounted_apps:
        raise ValueError(
            "A transport is already mounted on this app. Only one transport per instance is allowed."
        )

    # Create SSE transport
    sse = SseServerTransport("/mcp/messages")

    # Mount SSE endpoints using the transport's handle methods
    @app.get("/mcp/sse")
    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as (
            read_stream,
            write_stream,
        ):
            await wrapper.server.run(
                read_stream,
                write_stream,
                wrapper.server.create_initialization_options(),
            )
        # SSE transport handles response internally - no return needed

    @app.post("/mcp/messages")
    async def handle_messages(request):
        # Handle POST message (this already returns a Response internally)
        await sse.handle_post_message(request.scope, request.receive, request._send)

    _mounted_apps.add(app)
    logger.info("SSE transport mounted at /mcp/sse and /mcp/messages")


def mount_streamable_http_transport(app: FastAPI, wrapper: MCPServerWrapper) -> None:
    """Mount Streamable HTTP transport to FastAPI app.

    Args:
        app: FastAPI application
        wrapper: MCP server wrapper

    Raises:
        ValueError: If a transport is already mounted on this app
    """
    if app in _mounted_apps:
        raise ValueError(
            "A transport is already mounted on this app. Only one transport per instance is allowed."
        )

    # Mount HTTP endpoint; the session manager owns transport/session lifecycle.
    @app.post("/mcp")
    async def handle_mcp(request):
        return await handle_streamable_http_request(
            wrapper.server, request.scope, request.receive
        )

    _mounted_apps.add(app)
    logger.info("Streamable HTTP transport mounted at /mcp")


def mount_transport_from_config(
    app: FastAPI,
    wrapper: MCPServerWrapper,
    config: MCPConfig,
) -> None:
    """Mount transport based on MCP configuration.

    Args:
        app: FastAPI application
        wrapper: MCP server wrapper
        config: MCP transport configuration

    Raises:
        ValueError: If transport type is not supported or already mounted
    """
    if config.transport == TransportType.SSE:
        mount_sse_transport(app, wrapper)
    elif config.transport == TransportType.STREAMABLE_HTTP:
        mount_streamable_http_transport(app, wrapper)
    else:
        raise ValueError(f"Unsupported transport type: {config.transport}")

    logger.info(f"Transport mounted from config: {config.transport}")


# Made with Bob
