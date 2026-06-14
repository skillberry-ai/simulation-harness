"""Transport mounting for MCP server."""

from weakref import WeakSet

from fastapi import FastAPI
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport

from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.config.models import MCPConfig, TransportType
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)

# Track which apps have transports mounted (per-app, not global)
_mounted_apps: WeakSet[FastAPI] = WeakSet()


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

    # Create Streamable HTTP transport
    http = StreamableHTTPServerTransport(mcp_session_id=None)

    # Mount HTTP endpoint using the transport's handle method
    @app.post("/mcp")
    async def handle_mcp(request):
        async with http.connect(request.scope, request.receive, request._send) as (
            read_stream,
            write_stream,
        ):
            await wrapper.server.run(
                read_stream,
                write_stream,
                wrapper.server.create_initialization_options(),
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
