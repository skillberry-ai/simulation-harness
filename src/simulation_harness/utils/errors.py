"""Custom exception classes for simulation harness."""


class SessionExpiredError(Exception):
    """Raised when a session has expired due to max_messages or idle_timeout."""

    def __init__(
        self, reason: str, limit: int, observed: int, message: str | None = None
    ):
        """Initialize SessionExpiredError with structured fields.

        Args:
            reason: Reason for expiry (e.g., "max_messages_exceeded", "idle_timeout_exceeded")
            limit: The limit that was exceeded
            observed: The observed value that exceeded the limit
            message: Optional human-readable message
        """
        self.reason = reason
        self.limit = limit
        self.observed = observed
        super().__init__(
            message or f"Session expired: {reason} (limit={limit}, observed={observed})"
        )


class ConcurrentQueueFullError(Exception):
    """Raised when the concurrent execution queue is full."""

    pass


class SimulationAlreadyExistsError(Exception):
    """Raised when attempting to create a simulation that already exists."""

    pass


class SimulationNotFoundError(Exception):
    """Raised when a requested simulation does not exist."""

    pass


class OpenAPIValidationError(Exception):
    """Raised when OpenAPI specification validation fails."""

    pass


class PortInUseError(Exception):
    """Raised when the requested MCP port is already in use."""

    pass


class SimulationNotReadyError(Exception):
    """Raised when an operation requires a ready simulation but one exists in a non-ready state."""

    def __init__(
        self,
        name: str,
        status: str,
        retry_after_seconds: int = 2,
        message: str | None = None,
    ):
        self.name = name
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            message
            or f"Simulation '{name}' is not ready (status={status}); retry in {retry_after_seconds}s."
        )


class CreationTimeoutError(Exception):
    """Raised when simulation creation exceeds the configured wall-clock budget."""

    def __init__(self, limit_seconds: int, message: str | None = None):
        self.limit_seconds = limit_seconds
        super().__init__(
            message or f"Simulation creation exceeded {limit_seconds}s budget."
        )


# Made with Bob
