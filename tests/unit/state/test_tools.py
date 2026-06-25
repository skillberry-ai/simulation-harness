"""Tests for state tools."""

import pytest

from simulation_harness.state import StoreRegistry, create_state_tools

# ``skill_dir`` is provided by tests/unit/state/conftest.py.


@pytest.fixture
def registry(skill_dir):
    """Create a StoreRegistry instance."""
    return StoreRegistry(skill_dir)


@pytest.fixture
def mock_config(registry):
    """Create a mock RunnableConfig."""
    return {"configurable": {"store_registry": registry, "thread_id": "test_thread"}}


@pytest.fixture
def tools():
    """Create the state tools."""
    return create_state_tools()


class TestToolCreation:
    """Test tool creation."""

    def test_create_tools(self, tools):
        """Test that create_state_tools returns 6 tools."""
        assert len(tools) == 6

        tool_names = [t.name for t in tools]
        assert "state_get" in tool_names
        assert "state_list" in tool_names
        assert "state_count" in tool_names
        assert "state_insert" in tool_names
        assert "state_update" in tool_names
        assert "state_delete" in tool_names


class TestStateGet:
    """Test state_get tool."""

    def test_get_existing_entity(self, tools, mock_config):
        """Test getting an existing entity."""
        tool = next(t for t in tools if t.name == "state_get")

        result = tool.func(store="restaurants", id="rest_001", config=mock_config)

        assert "error" not in result
        assert result["id"] == "rest_001"
        assert result["name"] == "The Italian Corner"

    def test_get_nonexistent_entity(self, tools, mock_config):
        """Test getting a nonexistent entity returns error."""
        tool = next(t for t in tools if t.name == "state_get")

        result = tool.func(store="restaurants", id="nonexistent", config=mock_config)

        assert "error" in result
        assert result["error"] == "not_found"

    def test_get_unknown_store(self, tools, mock_config):
        """Test getting from unknown store returns error."""
        tool = next(t for t in tools if t.name == "state_get")

        result = tool.func(store="unknown_store", id="some_id", config=mock_config)

        assert "error" in result
        assert result["error"] == "unknown_store"


class TestStateList:
    """Test state_list tool."""

    def test_list_all(self, tools, mock_config):
        """Test listing all entities."""
        tool = next(t for t in tools if t.name == "state_list")

        result = tool.func(store="restaurants", config=mock_config)

        assert isinstance(result, list)
        assert len(result) >= 3

    def test_list_with_filter(self, tools, mock_config):
        """Test listing with a filter."""
        tool = next(t for t in tools if t.name == "state_list")

        result = tool.func(
            store="restaurants", where={"cuisine": "Italian"}, config=mock_config
        )

        assert isinstance(result, list)
        assert all(r["cuisine"] == "Italian" for r in result)

    def test_list_with_sort(self, tools, mock_config):
        """Test listing with sort parameter (verifies list-to-tuple conversion)."""
        tool = next(t for t in tools if t.name == "state_list")

        # Test sorting by name ascending
        result = tool.func(
            store="restaurants", sort=[["name", "asc"]], config=mock_config
        )

        assert isinstance(result, list)
        assert len(result) >= 3
        # Verify sorting worked (names should be in ascending order)
        names = [r["name"] for r in result]
        assert names == sorted(names)

        # Test sorting by rating descending
        result = tool.func(
            store="restaurants", sort=[["rating", "desc"]], config=mock_config
        )

        assert isinstance(result, list)
        ratings = [r["rating"] for r in result]
        assert ratings == sorted(ratings, reverse=True)

    def test_list_with_malformed_sort(self, tools, mock_config):
        """Test that malformed sort parameter returns clear error."""
        tool = next(t for t in tools if t.name == "state_list")

        # Test with single element (missing direction)
        result = tool.func(store="restaurants", sort=[["name"]], config=mock_config)

        assert isinstance(result, dict)
        assert result["error"] == "bad_query"
        assert "must be [field, direction] pairs" in result["message"]

        # Test with too many elements
        result = tool.func(
            store="restaurants", sort=[["name", "asc", "extra"]], config=mock_config
        )

        assert isinstance(result, dict)
        assert result["error"] == "bad_query"
        assert "must be [field, direction] pairs" in result["message"]

    def test_list_with_limit(self, tools, mock_config):
        """Test listing with a limit."""
        tool = next(t for t in tools if t.name == "state_list")

        result = tool.func(store="restaurants", limit=2, config=mock_config)

        assert isinstance(result, list)
        assert len(result) == 2


class TestStateCount:
    """Test state_count tool."""

    def test_count_all(self, tools, mock_config):
        """Test counting all entities."""
        tool = next(t for t in tools if t.name == "state_count")

        result = tool.func(store="restaurants", config=mock_config)

        assert isinstance(result, int)
        assert result >= 3

    def test_count_with_filter(self, tools, mock_config):
        """Test counting with a filter."""
        tool = next(t for t in tools if t.name == "state_count")

        result = tool.func(
            store="restaurants", where={"location.city": "Boston"}, config=mock_config
        )

        assert isinstance(result, int)
        assert result >= 1


class TestStateInsert:
    """Test state_insert tool."""

    def test_insert_valid_entity(self, tools, mock_config):
        """Test inserting a valid entity."""
        tool = next(t for t in tools if t.name == "state_insert")

        entity = {
            "id": "rest_test",
            "name": "Test Restaurant",
            "cuisine": "Test",
            "price_tier": 1,
            "rating": 3.0,
            "location": {
                "latitude": 42.0,
                "longitude": -71.0,
                "address": "Test",
                "city": "Test",
                "state": "MA",
                "postal_code": "00000",
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True,
        }

        result = tool.func(store="restaurants", entity=entity, config=mock_config)

        assert "error" not in result
        assert result["id"] == "rest_test"

    def test_insert_duplicate_key(self, tools, mock_config):
        """Test inserting a duplicate key returns error."""
        tool = next(t for t in tools if t.name == "state_insert")

        entity = {
            "id": "rest_001",  # Already exists
            "name": "Duplicate",
            "cuisine": "Test",
            "price_tier": 1,
            "rating": 3.0,
            "location": {
                "latitude": 42.0,
                "longitude": -71.0,
                "address": "Test",
                "city": "Test",
                "state": "MA",
                "postal_code": "00000",
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True,
        }

        result = tool.func(store="restaurants", entity=entity, config=mock_config)

        assert "error" in result
        assert result["error"] == "duplicate_key"

    def test_insert_invalid_entity(self, tools, mock_config):
        """Test inserting an invalid entity returns error."""
        tool = next(t for t in tools if t.name == "state_insert")

        entity = {
            "id": "rest_invalid",
            "name": "Invalid",
            # Missing required fields
        }

        result = tool.func(store="restaurants", entity=entity, config=mock_config)

        assert "error" in result
        assert result["error"] == "validation_error"


class TestStateUpdate:
    """Test state_update tool."""

    def test_update_existing_entity(self, tools, mock_config):
        """Test updating an existing entity."""
        tool = next(t for t in tools if t.name == "state_update")

        result = tool.func(
            store="restaurants",
            id="rest_001",
            patch={"rating": 4.9},
            config=mock_config,
        )

        assert "error" not in result
        assert result["rating"] == 4.9
        assert result["name"] == "The Italian Corner"  # Other fields unchanged

    def test_update_nonexistent_entity(self, tools, mock_config):
        """Test updating a nonexistent entity returns error."""
        tool = next(t for t in tools if t.name == "state_update")

        result = tool.func(
            store="restaurants",
            id="nonexistent",
            patch={"rating": 5.0},
            config=mock_config,
        )

        assert "error" in result
        assert result["error"] == "not_found"


class TestStateDelete:
    """Test state_delete tool."""

    def test_delete_existing_entity(self, tools, mock_config):
        """Test deleting an existing entity."""
        # First insert a test entity
        insert_tool = next(t for t in tools if t.name == "state_insert")
        entity = {
            "id": "rest_delete_test",
            "name": "To Delete",
            "cuisine": "Test",
            "price_tier": 1,
            "rating": 3.0,
            "location": {
                "latitude": 42.0,
                "longitude": -71.0,
                "address": "Test",
                "city": "Test",
                "state": "MA",
                "postal_code": "00000",
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True,
        }
        insert_tool.func(store="restaurants", entity=entity, config=mock_config)

        # Now delete it
        delete_tool = next(t for t in tools if t.name == "state_delete")
        result = delete_tool.func(
            store="restaurants", id="rest_delete_test", config=mock_config
        )

        assert "error" not in result
        assert result["id"] == "rest_delete_test"

        # Verify it's gone
        get_tool = next(t for t in tools if t.name == "state_get")
        get_result = get_tool.func(
            store="restaurants", id="rest_delete_test", config=mock_config
        )
        assert "error" in get_result

    def test_delete_nonexistent_entity(self, tools, mock_config):
        """Test deleting a nonexistent entity returns error."""
        tool = next(t for t in tools if t.name == "state_delete")

        result = tool.func(store="restaurants", id="nonexistent", config=mock_config)

        assert "error" in result
        assert result["error"] == "not_found"


class TestThreadIsolation:
    """Test that tools respect thread isolation."""

    def test_different_threads_see_different_data(self, tools, registry):
        """Test that different threads have isolated data."""
        config1 = {
            "configurable": {"store_registry": registry, "thread_id": "thread_1"}
        }
        config2 = {
            "configurable": {"store_registry": registry, "thread_id": "thread_2"}
        }

        insert_tool = next(t for t in tools if t.name == "state_insert")
        get_tool = next(t for t in tools if t.name == "state_get")

        # Insert into thread 1
        entity = {
            "id": "rest_thread1",
            "name": "Thread 1 Only",
            "cuisine": "Test",
            "price_tier": 1,
            "rating": 3.0,
            "location": {
                "latitude": 42.0,
                "longitude": -71.0,
                "address": "Test",
                "city": "Test",
                "state": "MA",
                "postal_code": "00000",
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True,
        }
        insert_tool.func(store="restaurants", entity=entity, config=config1)

        # Verify it's in thread 1
        result1 = get_tool.func(store="restaurants", id="rest_thread1", config=config1)
        assert "error" not in result1

        # Verify it's NOT in thread 2
        result2 = get_tool.func(store="restaurants", id="rest_thread1", config=config2)
        assert "error" in result2
        assert result2["error"] == "not_found"


# Made with Bob
