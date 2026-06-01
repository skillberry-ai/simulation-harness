"""State management for test client."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class RequestRecord:
    """Record of a request/response."""
    
    timestamp: datetime
    method: str
    endpoint: str
    request_data: Optional[dict[str, Any]]
    response_status: int
    response_data: Optional[dict[str, Any]]
    duration_ms: float
    error: Optional[str] = None


@dataclass
class AppState:
    """Application state container."""
    
    # Connection
    harness_url: str = "http://localhost:8086"
    connected: bool = False
    connection_error: Optional[str] = None
    
    # Current simulation
    simulation_name: Optional[str] = None
    simulation_status: Optional[str] = None
    simulation_created_at: Optional[datetime] = None
    mcp_endpoint: Optional[str] = None
    
    # MCP tools cache
    mcp_tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_tools_loaded: bool = False
    
    # History
    request_history: list[RequestRecord] = field(default_factory=list)
    
    def add_request(
        self,
        method: str,
        endpoint: str,
        request_data: Optional[dict[str, Any]],
        response_status: int,
        response_data: Optional[dict[str, Any]],
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """Add a request to history."""
        record = RequestRecord(
            timestamp=datetime.now(),
            method=method,
            endpoint=endpoint,
            request_data=request_data,
            response_status=response_status,
            response_data=response_data,
            duration_ms=duration_ms,
            error=error,
        )
        self.request_history.append(record)
    
    def clear_history(self) -> None:
        """Clear request history."""
        self.request_history.clear()
    
    def update_simulation(
        self,
        name: Optional[str],
        status: Optional[str],
        created_at: Optional[datetime],
        mcp_endpoint: Optional[str],
    ) -> None:
        """Update current simulation info."""
        self.simulation_name = name
        self.simulation_status = status
        self.simulation_created_at = created_at
        self.mcp_endpoint = mcp_endpoint
    
    def clear_simulation(self) -> None:
        """Clear simulation info."""
        self.simulation_name = None
        self.simulation_status = None
        self.simulation_created_at = None
        self.mcp_endpoint = None
        self.mcp_tools.clear()
        self.mcp_tools_loaded = False


def get_state() -> AppState:
    """Get or create app state from Streamlit session."""
    import streamlit as st
    
    if "app_state" not in st.session_state:
        st.session_state.app_state = AppState()
    
    return st.session_state.app_state

# Made with Bob
