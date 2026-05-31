"""Tests for custom exception classes."""

import pytest

from simulation_harness.utils.errors import (
    ConcurrentQueueFullError,
    OpenAPIValidationError,
    SessionExpiredError,
    SimulationAlreadyExistsError,
    SimulationNotFoundError,
)


class TestSessionExpiredError:
    """Tests for SessionExpiredError exception."""

    def test_can_be_raised(self):
        """Test that SessionExpiredError can be raised."""
        with pytest.raises(SessionExpiredError) as exc_info:
            raise SessionExpiredError(
                reason="max_messages_exceeded",
                limit=100,
                observed=101
            )
        
        assert "max_messages" in str(exc_info.value)

    def test_inherits_from_exception(self):
        """Test that SessionExpiredError inherits from Exception."""
        error = SessionExpiredError(
            reason="test_reason",
            limit=10,
            observed=11
        )
        assert isinstance(error, Exception)

    def test_can_have_custom_message(self):
        """Test that SessionExpiredError can have a custom message."""
        message = "Session expired: idle timeout of 300 seconds exceeded"
        error = SessionExpiredError(
            reason="idle_timeout_exceeded",
            limit=300,
            observed=350,
            message=message
        )
        assert str(error) == message

    def test_structured_fields_max_messages(self):
        """Test that SessionExpiredError has structured fields for max_messages."""
        error = SessionExpiredError(
            reason="max_messages_exceeded",
            limit=100,
            observed=101
        )
        
        assert error.reason == "max_messages_exceeded"
        assert error.limit == 100
        assert error.observed == 101
        assert "max_messages_exceeded" in str(error)
        assert "limit=100" in str(error)
        assert "observed=101" in str(error)

    def test_structured_fields_idle_timeout(self):
        """Test that SessionExpiredError has structured fields for idle_timeout."""
        error = SessionExpiredError(
            reason="idle_timeout_exceeded",
            limit=300,
            observed=350
        )
        
        assert error.reason == "idle_timeout_exceeded"
        assert error.limit == 300
        assert error.observed == 350
        assert "idle_timeout_exceeded" in str(error)

    def test_structured_fields_with_custom_message(self):
        """Test that SessionExpiredError can have custom message with structured fields."""
        custom_msg = "Custom expiry message"
        error = SessionExpiredError(
            reason="max_messages_exceeded",
            limit=50,
            observed=51,
            message=custom_msg
        )
        
        assert error.reason == "max_messages_exceeded"
        assert error.limit == 50
        assert error.observed == 51
        assert str(error) == custom_msg


class TestConcurrentQueueFullError:
    """Tests for ConcurrentQueueFullError exception."""

    def test_can_be_raised(self):
        """Test that ConcurrentQueueFullError can be raised."""
        with pytest.raises(ConcurrentQueueFullError) as exc_info:
            raise ConcurrentQueueFullError("Queue is full")
        
        assert "Queue is full" in str(exc_info.value)

    def test_inherits_from_exception(self):
        """Test that ConcurrentQueueFullError inherits from Exception."""
        error = ConcurrentQueueFullError("test")
        assert isinstance(error, Exception)

    def test_can_have_custom_message(self):
        """Test that ConcurrentQueueFullError can have a custom message."""
        message = "Concurrent queue full: 10/10 slots occupied"
        error = ConcurrentQueueFullError(message)
        assert str(error) == message


class TestSimulationAlreadyExistsError:
    """Tests for SimulationAlreadyExistsError exception."""

    def test_can_be_raised(self):
        """Test that SimulationAlreadyExistsError can be raised."""
        with pytest.raises(SimulationAlreadyExistsError) as exc_info:
            raise SimulationAlreadyExistsError("Simulation already exists")
        
        assert "already exists" in str(exc_info.value)

    def test_inherits_from_exception(self):
        """Test that SimulationAlreadyExistsError inherits from Exception."""
        error = SimulationAlreadyExistsError("test")
        assert isinstance(error, Exception)

    def test_can_have_simulation_name(self):
        """Test that SimulationAlreadyExistsError can include simulation name."""
        message = "Simulation 'test-sim' already exists"
        error = SimulationAlreadyExistsError(message)
        assert "test-sim" in str(error)


class TestSimulationNotFoundError:
    """Tests for SimulationNotFoundError exception."""

    def test_can_be_raised(self):
        """Test that SimulationNotFoundError can be raised."""
        with pytest.raises(SimulationNotFoundError) as exc_info:
            raise SimulationNotFoundError("Simulation not found")
        
        assert "not found" in str(exc_info.value)

    def test_inherits_from_exception(self):
        """Test that SimulationNotFoundError inherits from Exception."""
        error = SimulationNotFoundError("test")
        assert isinstance(error, Exception)

    def test_can_have_simulation_name(self):
        """Test that SimulationNotFoundError can include simulation name."""
        message = "Simulation 'missing-sim' not found"
        error = SimulationNotFoundError(message)
        assert "missing-sim" in str(error)


class TestOpenAPIValidationError:
    """Tests for OpenAPIValidationError exception."""

    def test_can_be_raised(self):
        """Test that OpenAPIValidationError can be raised."""
        with pytest.raises(OpenAPIValidationError) as exc_info:
            raise OpenAPIValidationError("Invalid OpenAPI spec")
        
        assert "Invalid" in str(exc_info.value)

    def test_inherits_from_exception(self):
        """Test that OpenAPIValidationError inherits from Exception."""
        error = OpenAPIValidationError("test")
        assert isinstance(error, Exception)

    def test_can_have_validation_details(self):
        """Test that OpenAPIValidationError can include validation details."""
        message = "OpenAPI validation failed: missing 'info' field"
        error = OpenAPIValidationError(message)
        assert "missing 'info' field" in str(error)


class TestExceptionHierarchy:
    """Tests for exception hierarchy and relationships."""

    def test_all_exceptions_are_distinct(self):
        """Test that all custom exceptions are distinct types."""
        exceptions = [
            SessionExpiredError(reason="test", limit=1, observed=2),
            ConcurrentQueueFullError("test"),
            SimulationAlreadyExistsError("test"),
            SimulationNotFoundError("test"),
            OpenAPIValidationError("test"),
        ]
        
        # Check that each exception is a different type
        types = [type(e) for e in exceptions]
        assert len(types) == len(set(types))

    def test_all_exceptions_inherit_from_exception(self):
        """Test that all custom exceptions inherit from Exception."""
        exceptions = [
            SessionExpiredError,
            ConcurrentQueueFullError,
            SimulationAlreadyExistsError,
            SimulationNotFoundError,
            OpenAPIValidationError,
        ]
        
        for exc_class in exceptions:
            assert issubclass(exc_class, Exception)

# Made with Bob
