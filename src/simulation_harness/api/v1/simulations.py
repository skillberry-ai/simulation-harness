"""Simulation management API routes."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from simulation_harness.api.dependencies import SimulationHostDep, SkillRegistryDep
from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.models.domain import SimulationSpec
from simulation_harness.models.requests import CreateSimulationRequest
from simulation_harness.models.responses import SimulationResponse
from simulation_harness.openapi.parser import OpenAPISpec, validate_openapi_dict
from simulation_harness.utils.errors import (
    SimulationAlreadyExistsError,
    OpenAPIValidationError,
)
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 10MB body size limit
MAX_BODY_SIZE = 10 * 1024 * 1024


async def validate_body_size(request: Request) -> None:
    """Validate request body size doesn't exceed 10MB.
    
    Args:
        request: FastAPI request
        
    Raises:
        HTTPException: If body size exceeds limit
    """
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request body too large. Maximum size is {MAX_BODY_SIZE} bytes.",
        )


@router.post(
    "/simulation",
    status_code=status.HTTP_201_CREATED,
    response_model=SimulationResponse,
)
async def create_simulation(
    request: Request,
    body: CreateSimulationRequest,
    simulation_host: SimulationHostDep,
    skill_registry: SkillRegistryDep,
) -> SimulationResponse:
    """Create a new simulation.
    
    Args:
        request: FastAPI request
        body: Create simulation request
        simulation_host: SimulationHost dependency
        skill_registry: SkillRegistry dependency
        
    Returns:
        Simulation response with status
        
    Raises:
        HTTPException: 409 if simulation exists, 422 if validation fails
    """
    # Validate body size
    await validate_body_size(request)
    
    try:
        # Validate OpenAPI spec
        try:
            validate_openapi_dict(body.openapi_spec)
            parsed_spec = OpenAPISpec(body.openapi_spec)
        except OpenAPIValidationError as e:
            logger.error(f"OpenAPI validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"OpenAPI validation failed: {str(e)}",
            )
        except Exception as e:
            logger.error(f"OpenAPI parsing failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"OpenAPI parsing failed: {str(e)}",
            )
        
        # Derive simulation name from override or spec title
        if body.name:
            simulation_name = body.name.lower().replace(" ", "-")
        else:
            simulation_name = body.openapi_spec.get("info", {}).get("title", "simulation")
            simulation_name = simulation_name.lower().replace(" ", "-")
        
        # Ensure skill exists
        try:
            await skill_registry.ensure_skill(
                simulation_name=simulation_name,
                openapi_spec=body.openapi_spec,
                regenerate=body.regenerate_skill,
            )
        except Exception as e:
            logger.error(f"Skill generation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Skill generation failed: {str(e)}",
            )
        
        # Create simulation spec
        spec = SimulationSpec(
            name=simulation_name,
            openapi_spec=body.openapi_spec,
        )
        
        # Create simulation instance
        try:
            instance = await simulation_host.create_simulation(spec)
        except SimulationAlreadyExistsError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        
        # Build response
        session_state = instance.get_session_state()
        
        return SimulationResponse(
            name=simulation_name,
            status="active",
            session_state=session_state,
            mcp_endpoint=f"/mcp/{simulation_name}",
            created_at=instance.created_at,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating simulation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.get(
    "/simulation",
    status_code=status.HTTP_200_OK,
    response_model=SimulationResponse,
)
async def get_simulation(
    simulation_host: SimulationHostDep,
) -> SimulationResponse:
    """Get current simulation status.
    
    Args:
        simulation_host: SimulationHost dependency
        
    Returns:
        Simulation response with status
        
    Raises:
        HTTPException: 404 if no simulation exists
    """
    instance = await simulation_host.get_simulation()
    
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    
    # Build response
    session_state = instance.get_session_state()
    
    return SimulationResponse(
        name=instance.spec.name,
        status="active",
        session_state=session_state,
        mcp_endpoint=f"/mcp/{instance.spec.name}",
        created_at=instance.created_at,
    )


@router.delete(
    "/simulation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_simulation(
    simulation_host: SimulationHostDep,
) -> Response:
    """Delete current simulation.
    
    Args:
        simulation_host: SimulationHost dependency
        
    Returns:
        Empty response
        
    Raises:
        HTTPException: 404 if no simulation exists
    """
    instance = await simulation_host.get_simulation()
    
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    
    await simulation_host.delete_simulation()
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/simulation/reset",
    status_code=status.HTTP_200_OK,
)
async def reset_session(
    simulation_host: SimulationHostDep,
) -> dict[str, str]:
    """Reset simulation session.
    
    Args:
        simulation_host: SimulationHost dependency
        
    Returns:
        Success message
        
    Raises:
        HTTPException: 404 if no simulation exists
    """
    instance = await simulation_host.get_simulation()
    
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No simulation found",
        )
    
    await instance.reset_session()
    
    return {"message": "Session reset successfully"}


@router.get(
    "/simulation/tools",
    status_code=status.HTTP_200_OK,
)
async def list_simulation_tools(
    simulation_host: SimulationHostDep,
) -> list[dict[str, Any]]:
    """List MCP tools for current simulation.
    
    This is a simple REST endpoint that returns the list of available MCP tools
    without requiring an SSE connection. Useful for testing and simple clients.
    
    Args:
        simulation_host: SimulationHost dependency
        
    Returns:
        List of tool schemas
        
    Raises:
        HTTPException: 503 if no simulation exists
    """
    instance = await simulation_host.get_simulation()
    
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No simulation found",
        )
    
    # Create MCP server wrapper and list tools
    wrapper = MCPServerWrapper(instance)
    tools = await wrapper.list_tools()
    
    return tools


# Made with Bob