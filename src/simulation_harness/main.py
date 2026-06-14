"""Main FastAPI application for simulation harness."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from simulation_harness.api.dependencies import get_simulation_host, get_skill_registry
from simulation_harness.api.v1.simulations import router as simulations_router
from simulation_harness.config.settings import (
    ConfigValidationError,
    load_config,
    load_secrets,
)
from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.utils.errors import (
    ConcurrentQueueFullError,
    OpenAPIValidationError,
    PortInUseError,
    SessionExpiredError,
    SimulationAlreadyExistsError,
    SimulationNotFoundError,
)
from simulation_harness.utils.logging import get_logger

# Read HARNESS_CONFIG_PATH from .env if not already in the process env.
# Use dotenv_values (no side-effects) rather than load_dotenv (mutates os.environ).
from dotenv import dotenv_values as _dotenv_values
_dotenv_file_vars = _dotenv_values(".env")
config_path = os.getenv(
    "HARNESS_CONFIG_PATH",
    _dotenv_file_vars.get("HARNESS_CONFIG_PATH", "config/harness.yaml"),
)
del _dotenv_values, _dotenv_file_vars

try:
    config = load_config(config_path)
except (FileNotFoundError, ConfigValidationError) as e:
    print(f"ERROR: Failed to load configuration: {e}")
    raise

# Setup logging based on configuration
log_level = getattr(logging, config.logging.level)
log_dir = Path(config.logging.destination_folder)

# Create logs directory if it doesn't exist
log_dir.mkdir(parents=True, exist_ok=True)

# Generate timestamp-based log filename with PID: YYYY-MM-DD_HH-MM-SS_pid{PID}_simulation-harness.log
# PID ensures unique filenames in multi-process deployments (e.g., uvicorn workers)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
pid = os.getpid()
log_file = log_dir / f"{timestamp}_pid{pid}_simulation-harness.log"

# Configure logging with both console and file handlers
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler(log_file),  # File output
    ],
)

logger = get_logger(__name__)
logger.info(f"Logging configured: level={config.logging.level}, file={log_file}")
logger.info(f"Loading configuration from: {config_path}")
logger.info(f"Configuration loaded successfully: transport={config.mcp.transport}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown.

    Startup:
    - Load secrets (so the module is importable without LLM_API_KEY)
    - Validate config (already done at module level)
    - Create singletons (done via dependency injection)
    - Log startup info

    Shutdown:
    - Cleanup simulation if exists
    - Shutdown agent
    """
    # Startup
    try:
        load_secrets()
    except Exception as e:
        logger.error(
            f"Failed to load secrets: {e}\n"
            "LLM_API_KEY is required (set it in .env for local dev or via "
            "Kubernetes Secret in cluster). See .env.example."
        )
        raise RuntimeError("Missing required secrets — see logs above") from e

    logger.info("=" * 80)
    logger.info("Simulation Harness starting up")
    logger.info(f"Config path: {config_path}")
    logger.info(f"Transport: {config.mcp.transport}")
    logger.info("=" * 80)

    # Initialize singletons (they'll be created on first use via dependency injection)
    simulation_host = get_simulation_host()
    skill_registry = get_skill_registry()

    logger.info("Singletons initialized")
    logger.info(f"Skills folder: {skill_registry.skills_folder}")

    yield

    # Shutdown
    logger.info("=" * 80)
    logger.info("Simulation Harness shutting down")
    logger.info("=" * 80)

    # Cleanup simulation if exists
    try:
        instance = await simulation_host.get_simulation()
        if instance is not None:
            logger.info(f"Cleaning up simulation: {instance.spec.name}")
            await simulation_host.delete_simulation()
            logger.info("Simulation cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during simulation cleanup: {e}", exc_info=True)

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Simulation Harness",
    description=(
        "Spin up a stateful [MCP](https://modelcontextprotocol.io/) server that simulates "
        "any REST API described by an OpenAPI specification — without hitting real backends.\n\n"
        "## Workflow\n\n"
        "1. **Create a simulation** — `POST /api/v1/simulation` with your OpenAPI spec. "
        "The harness validates the spec, generates an LLM skill, and starts an MCP server.\n"
        "2. **Connect your MCP client** — point it at the MCP transport endpoint below.\n"
        "3. **Call tools** — each tool maps 1-to-1 with an OpenAPI operation; responses are "
        "synthesised by an LLM using the spec's schemas and examples.\n"
        "4. **Reset or delete** the simulation when you're done.\n\n"
        "## MCP Transports\n\n"
        "| Transport | Connect | Messages |\n"
        "|-----------|---------|----------|\n"
        "| SSE *(default)* | `GET /mcp/sse` | `POST /mcp/messages` |\n"
        "| Streamable HTTP | `POST /mcp` | — |\n\n"
        "Only **one simulation** can be active at a time."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Simulation Harness"},
    openapi_tags=[
        {
            "name": "simulations",
            "description": "Manage the active simulation lifecycle — create, inspect, reset, and delete.",
        },
        {
            "name": "mcp",
            "description": (
                "MCP transport endpoints. Connect your MCP client here after creating a simulation. "
                "The active transport type is configured in `harness.yaml`."
            ),
        },
        {
            "name": "health",
            "description": "Liveness probe.",
        },
    ],
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set max body size to 10MB
app.router.default_response_class.max_body_size = 10 * 1024 * 1024  # type: ignore[attr-defined]

# Register management API routes
app.include_router(simulations_router, prefix="/api/v1", tags=["simulations"])

# Mount MCP transport endpoints with dynamic routing
# Endpoints check for active simulation and create MCP server wrapper on demand
try:
    from fastapi import Depends
    from simulation_harness.core.simulation_host import SimulationHost

    logger.info(f"Mounting MCP transport: {config.mcp.transport}")

    if config.mcp.transport.value == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.responses import Response

        # Single shared transport instance so connect_sse and handle_post_message
        # operate on the same session registry.
        _sse_transport = SseServerTransport("/mcp/messages")

        @app.get(
            "/mcp/sse",
            tags=["mcp"],
            summary="MCP SSE — connect",
            description=(
                "Open a long-lived Server-Sent Events stream that carries MCP protocol messages. "
                "Keep this connection open for the duration of the MCP session, then send individual "
                "messages via `POST /mcp/messages`.\n\n"
                "Requires an active simulation (created via `POST /api/v1/simulation`)."
            ),
            responses={
                503: {"description": "No simulation is currently active"},
            },
        )
        async def mcp_sse_endpoint(
            request: Request, host: SimulationHost = Depends(get_simulation_host)
        ):
            """MCP SSE transport endpoint."""
            instance = await host.get_simulation()
            if instance is None:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "No simulation active",
                        "message": "Create a simulation via POST /api/v1/simulation first",
                    },
                )

            mcp_server = MCPServerWrapper(instance)

            from starlette.responses import Response as StarletteResponse

            async with _sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as (read_stream, write_stream):
                await mcp_server.server.run(
                    read_stream,
                    write_stream,
                    mcp_server.server.create_initialization_options(),
                )
            return StarletteResponse()

        @app.post(
            "/mcp/messages",
            tags=["mcp"],
            summary="MCP SSE — send message",
            description=(
                "Send a single MCP protocol message over the SSE transport. "
                "Requires an open SSE connection established via `GET /mcp/sse`."
            ),
            responses={
                503: {"description": "No simulation is currently active"},
            },
        )
        async def mcp_messages_endpoint(
            request: Request, host: SimulationHost = Depends(get_simulation_host)
        ):
            """MCP messages endpoint for SSE transport."""
            instance = await host.get_simulation()
            if instance is None:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "No simulation active",
                        "message": "Create a simulation via POST /api/v1/simulation first",
                    },
                )

            # Capture the ASGI messages written by handle_post_message so we can
            # return them as a proper FastAPI Response.  Without this, FastAPI
            # tries to send a second response after the handler returns, causing
            # "Unexpected ASGI message sent after response already completed".
            captured: dict = {"status": 202, "headers": [], "body": b""}

            async def _capture_send(message: dict) -> None:
                if message["type"] == "http.response.start":
                    captured["status"] = message["status"]
                    captured["headers"] = message.get("headers", [])
                elif message["type"] == "http.response.body":
                    captured["body"] = message.get("body", b"")

            await _sse_transport.handle_post_message(
                request.scope, request.receive, _capture_send
            )

            return Response(
                content=captured["body"],
                status_code=captured["status"],
                headers={k.decode(): v.decode() for k, v in captured["headers"]},
            )

        logger.info("SSE transport endpoints mounted at /mcp/sse and /mcp/messages")

    elif config.mcp.transport.value == "streamable_http":

        @app.post(
            "/mcp",
            tags=["mcp"],
            summary="MCP Streamable HTTP",
            description=(
                "Single endpoint for the MCP Streamable HTTP transport. "
                "Each request carries a complete MCP message and the response streams the reply.\n\n"
                "Requires an active simulation (created via `POST /api/v1/simulation`)."
            ),
            responses={
                503: {"description": "No simulation is currently active"},
            },
        )
        async def mcp_streamable_endpoint(
            request: Request, host: SimulationHost = Depends(get_simulation_host)
        ):
            """MCP Streamable HTTP transport endpoint."""
            instance = await host.get_simulation()
            if instance is None:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "No simulation active",
                        "message": "Create a simulation via POST /api/v1/simulation first",
                    },
                )

            # Create MCP server wrapper and handle streamable HTTP
            from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
            from mcp.server.streamable_http import StreamableHTTPServerTransport

            mcp_server = MCPServerWrapper(instance)
            http = StreamableHTTPServerTransport()

            async with http.connect(request.scope, request.receive, request._send) as (
                read_stream,
                write_stream,
            ):
                await mcp_server.server.run(
                    read_stream,
                    write_stream,
                    mcp_server.server.create_initialization_options(),
                )

        logger.info("Streamable HTTP transport endpoint mounted at /mcp")

except Exception as e:
    logger.error(f"Failed to mount MCP transport: {e}", exc_info=True)
    raise


# Error handlers
@app.exception_handler(SimulationAlreadyExistsError)
async def simulation_already_exists_handler(
    request: Request, exc: SimulationAlreadyExistsError
) -> JSONResponse:
    """Handle SimulationAlreadyExistsError with 409 Conflict."""
    logger.warning(f"Simulation already exists: {exc}")
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(PortInUseError)
async def port_in_use_handler(
    request: Request, exc: PortInUseError
) -> JSONResponse:
    """Handle PortInUseError with 409 Conflict."""
    logger.warning(f"MCP port already in use: {exc}")
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(SimulationNotFoundError)
async def simulation_not_found_handler(
    request: Request, exc: SimulationNotFoundError
) -> JSONResponse:
    """Handle SimulationNotFoundError with 404 Not Found."""
    logger.warning(f"Simulation not found: {exc}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(OpenAPIValidationError)
async def openapi_validation_error_handler(
    request: Request, exc: OpenAPIValidationError
) -> JSONResponse:
    """Handle OpenAPIValidationError with 422 Unprocessable Entity."""
    logger.error(f"OpenAPI validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(ConfigValidationError)
async def config_validation_error_handler(
    request: Request, exc: ConfigValidationError
) -> JSONResponse:
    """Handle ConfigValidationError with 500 Internal Server Error."""
    logger.error(f"Configuration validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Configuration error: {str(exc)}"},
    )


@app.exception_handler(SessionExpiredError)
async def session_expired_error_handler(
    request: Request, exc: SessionExpiredError
) -> JSONResponse:
    """Handle SessionExpiredError with 410 Gone."""
    logger.warning(f"Session expired: {exc}")
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"detail": str(exc)},
    )


@app.exception_handler(ConcurrentQueueFullError)
async def concurrent_queue_full_error_handler(
    request: Request, exc: ConcurrentQueueFullError
) -> JSONResponse:
    """Handle ConcurrentQueueFullError with 503 Service Unavailable."""
    logger.warning(f"Concurrent queue full: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic exceptions with 500 Internal Server Error."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


logger.info("FastAPI application initialized")

# Made with Bob
