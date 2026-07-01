"""Simulation management API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from simulation_harness.api.dependencies import SimulationHostDep, SkillRegistryDep
from simulation_harness.config.models import TransportType
from simulation_harness.config.settings import get_config
from simulation_harness.core.simulation_record import (
    SimulationRecord,
    SimulationStatus,
)
from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.models.requests import (
    CreateSimulationRequest,
    StartSimulationRequest,
)
from simulation_harness.models.responses import (
    ErrorPayload,
    ProgressPayload,
    SimulationResponse,
)
from simulation_harness.openapi.parser import OpenAPISpec, validate_openapi_dict
from simulation_harness.skills.generation.naming import sanitize_skill_name
from simulation_harness.utils.errors import (
    OpenAPIValidationError,
    SimulationAlreadyExistsError,
    SimulationNotReadyError,
)
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


def _build_mcp_url(request: Request, mcp_port: int | None) -> str:
    try:
        transport = get_config().mcp.transport
        mcp_path = "/mcp/sse" if transport == TransportType.SSE else "/mcp"
    except RuntimeError:
        mcp_path = "/mcp/sse"
    if mcp_port is not None:
        host = request.url.hostname
        scheme = request.url.scheme
        return f"{scheme}://{host}:{mcp_port}{mcp_path}"
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{mcp_path}"


def _record_to_response(
    record: SimulationRecord, request: Request
) -> SimulationResponse:
    progress = ProgressPayload(
        phase=record.progress.phase,
        started_at=record.progress.started_at,
        updated_at=record.progress.updated_at,
    )
    error = (
        ErrorPayload(
            code=record.error.code,
            message=record.error.message,
            details=record.error.details,
        )
        if record.error is not None
        else None
    )

    if record.status == SimulationStatus.READY and record.instance is not None:
        return SimulationResponse(
            name=record.name,
            status=record.status.value,
            session_state=record.instance.get_session_state(),
            mcp_url=_build_mcp_url(request, record.instance.mcp_port),
            created_at=record.created_at,
            progress=progress,
            error=error,
        )

    return SimulationResponse(
        name=record.name,
        status=record.status.value,
        session_state=None,
        mcp_url=None,
        created_at=record.created_at,
        progress=progress,
        error=error,
    )


router = APIRouter()

MAX_BODY_SIZE = 10 * 1024 * 1024


async def validate_body_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request body too large. Maximum size is {MAX_BODY_SIZE} bytes.",
        )


@router.post(
    "/simulation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SimulationResponse,
    summary="Create simulation (async)",
    description=(
        "Declare a new simulation. Returns immediately with `status=pending` while skill "
        "generation and agent initialization run in the background. Poll `GET /api/v1/simulation` "
        "until status becomes `ready` or `failed`.\n\n"
        "Only one simulation can be active per process — a second POST while one exists returns 409."
    ),
    responses={
        202: {"description": "Simulation declared; poll GET /simulation for progress"},
        409: {"description": "A simulation already exists — delete it first"},
        413: {"description": "Request body exceeds the 10 MB limit"},
        422: {"description": "Invalid OpenAPI specification"},
    },
)
async def create_simulation(
    request: Request,
    body: CreateSimulationRequest,
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> SimulationResponse:
    await validate_body_size(request)

    try:
        validate_openapi_dict(body.openapi_spec)
        OpenAPISpec(body.openapi_spec)
    except OpenAPIValidationError as e:
        logger.error(f"OpenAPI validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OpenAPI validation failed: {e}",
        )
    except Exception as e:
        logger.error(f"OpenAPI parsing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OpenAPI parsing failed: {e}",
        )

    # The simulation name doubles as the skill directory name and the SKILL.md
    # frontmatter `name`, both of which must satisfy the Agent Skills spec.
    if body.name:
        simulation_name = sanitize_skill_name(body.name)
    else:
        simulation_name = sanitize_skill_name(
            body.openapi_spec.get("info", {}).get("title", "simulation")
        )

    try:
        record = await simulation_host.declare_simulation(
            name=simulation_name,
            openapi_spec=body.openapi_spec,
            regenerate=body.regenerate_skill,
            mcp_port=body.mcp_port,
            skill_registry=skill_registry,
        )
    except SimulationAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return _record_to_response(record, request)


@router.post(
    "/simulation/setup",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SimulationResponse,
    summary="Set up a simulation (generate artifacts, no session)",
    description=(
        "Generate the skill artifacts from an OpenAPI spec without starting a session. "
        "Returns 202 with status=pending; poll GET /simulation until status=generated or failed."
    ),
    responses={
        202: {"description": "Setup declared; poll GET /simulation for progress"},
        409: {"description": "A simulation already exists — delete it first"},
        413: {"description": "Request body exceeds the 10 MB limit"},
        422: {"description": "Invalid OpenAPI specification"},
    },
)
async def setup_simulation(
    request: Request,
    body: CreateSimulationRequest,
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> SimulationResponse:
    await validate_body_size(request)
    try:
        validate_openapi_dict(body.openapi_spec)
        OpenAPISpec(body.openapi_spec)
    except OpenAPIValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )

    if body.name:
        simulation_name = sanitize_skill_name(body.name)
    else:
        simulation_name = sanitize_skill_name(
            body.openapi_spec.get("info", {}).get("title", "simulation")
        )

    record = await simulation_host.setup_simulation(
        name=simulation_name,
        openapi_spec=body.openapi_spec,
        regenerate=body.regenerate_skill,
        skill_registry=skill_registry,
    )
    return _record_to_response(record, request)


@router.post(
    "/simulation/start",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SimulationResponse,
    summary="Start a simulation from baked artifacts",
    description=(
        "Open a session from a skill's existing artifacts (no OpenAPI spec required). "
        "Returns 202 with status=pending; poll GET /simulation until status=ready or failed."
    ),
    responses={
        202: {"description": "Start declared; poll GET /simulation for progress"},
        404: {"description": "No complete artifacts exist for the given name"},
        409: {"description": "A simulation is already running — delete it first"},
    },
)
async def start_simulation(
    request: Request,
    body: StartSimulationRequest,
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> SimulationResponse:
    simulation_name = sanitize_skill_name(body.name)
    record = await simulation_host.start_simulation(
        name=simulation_name,
        mcp_port=body.mcp_port,
        skill_registry=skill_registry,
    )
    return _record_to_response(record, request)


@router.get(
    "/simulation",
    status_code=status.HTTP_200_OK,
    response_model=SimulationResponse,
    summary="Get simulation",
    description=(
        "Return the current simulation record including status, progress, and (when ready) "
        "session counters. Used by clients to poll until status=ready or failed."
    ),
    responses={404: {"description": "No simulation has been declared"}},
)
async def get_simulation(
    request: Request,
    simulation_host: SimulationHostDep,
) -> SimulationResponse:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    return _record_to_response(record, request)


@router.delete(
    "/simulation",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete simulation",
    description=(
        "Cancel in-flight creation or shut down the active simulation. "
        "After this call, `GET /simulation` returns 404."
    ),
    responses={
        204: {"description": "Simulation deleted (or cancelled mid-creation)"},
        404: {"description": "No simulation exists"},
    },
)
async def delete_simulation(
    simulation_host: SimulationHostDep,
) -> Response:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    await simulation_host.delete_simulation()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/simulation/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset session",
    responses={
        404: {"description": "No simulation exists"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def reset_session(
    simulation_host: SimulationHostDep,
) -> dict[str, str]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)
    await record.instance.reset_session()
    return {"message": "Session reset successfully"}


@router.get(
    "/simulation/tools",
    status_code=status.HTTP_200_OK,
    summary="List simulation tools",
    responses={
        404: {"description": "No simulation exists"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def list_simulation_tools(
    simulation_host: SimulationHostDep,
) -> list[dict[str, Any]]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)
    wrapper = MCPServerWrapper(record.instance)
    return await wrapper.list_tools()


@router.get(
    "/simulation/state",
    status_code=status.HTTP_200_OK,
    summary="Get simulation state",
    responses={
        404: {"description": "No simulation exists"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def get_simulation_state(
    simulation_host: SimulationHostDep,
    thread_id: str = "default",
) -> dict[str, Any]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)
    return record.instance.get_state_snapshot(thread_id)


@router.get(
    "/simulation/database",
    status_code=status.HTTP_200_OK,
    summary="Get on-disk database (db.json) for the active skill",
    description=(
        "Return the contents of the active skill's `db.json` file from disk. "
        "This is distinct from `/simulation/state`, which returns the in-memory "
        "store snapshot for a thread. Use this to inspect the seed."
    ),
    responses={
        404: {"description": "No simulation exists"},
        500: {"description": "Skill bundle is incomplete (db.json missing)"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def get_simulation_database(
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> dict[str, Any]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)
    try:
        return skill_registry.read_db(record.name)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Skill bundle is incomplete: {e}",
        )


@router.get(
    "/simulation/schema",
    status_code=status.HTTP_200_OK,
    summary="Get JSON Schema for the active skill's database",
    description=(
        "Return the contents of the active skill's `schema.json`. Read-only. "
        "Clients producing payloads for `PUT /simulation/database` should fetch "
        "this first to learn the expected shape."
    ),
    responses={
        404: {"description": "No simulation exists"},
        500: {"description": "Skill bundle is incomplete (schema.json missing)"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def get_simulation_schema(
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> dict[str, Any]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)
    try:
        return skill_registry.read_schema(record.name)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Skill bundle is incomplete: {e}",
        )


@router.put(
    "/simulation/database",
    status_code=status.HTTP_200_OK,
    summary="Replace on-disk database (db.json) and reset the simulation",
    description=(
        "Atomically overwrite the active skill's `db.json` with the request body. "
        "The body is validated against the skill's `schema.json` before the write; "
        "validation failures return 422 and the file on disk is unchanged. "
        "On success, the running simulation is reset (agent thread and in-memory "
        "stores are cleared) so the next `tools/call` reloads from the new seed.\n\n"
        "Refuses with 409 while tool calls are in flight."
    ),
    responses={
        200: {"description": "Database replaced; simulation reset"},
        404: {"description": "No simulation exists"},
        409: {"description": "Tool calls are in flight; retry"},
        422: {"description": "Body does not validate against schema.json"},
        503: {"description": "Simulation exists but is not ready yet"},
    },
)
async def put_simulation_database(
    body: dict[str, Any],
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> dict[str, str]:
    record = await simulation_host.get_record()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    if record.status != SimulationStatus.READY or record.instance is None:
        raise SimulationNotReadyError(name=record.name, status=record.status.value)

    await simulation_host.replace_database(new_db=body, skill_registry=skill_registry)
    return {"message": "Database replaced; simulation reset"}


# Made with Bob
