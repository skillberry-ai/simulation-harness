"""Agent module for simulation harness."""

# Avoid circular imports - import only when needed
__all__ = ["DeepAgent", "SessionManager"]


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name == "DeepAgent":
        from simulation_harness.agent.deep_agent import DeepAgent
        return DeepAgent
    elif name == "SessionManager":
        from simulation_harness.agent.session_manager import SessionManager
        return SessionManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Made with Bob
