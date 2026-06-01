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


# Made with Bob
