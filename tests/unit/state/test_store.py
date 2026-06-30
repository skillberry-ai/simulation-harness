"""Tests for SimulationStore."""

import pytest

from simulation_harness.state import (
    load_store_from_skill,
    NotFoundError,
    DuplicateKeyError,
    ValidationError,
    UnknownStoreError,
    BadQueryError,
)
from pathlib import Path
from typing import Any

# ``skill_dir`` is provided by tests/unit/state/conftest.py.


@pytest.fixture
def restaurant_store(skill_dir: Path) -> Any:
    """Load the restaurant reservation fixture store."""
    return load_store_from_skill(skill_dir)


class TestStoreBasics:
    """Test basic store operations."""

    def test_load_from_skill(self, restaurant_store: Any) -> None:
        """Test loading a store from a skill directory."""
        assert restaurant_store is not None

        # Check that seed data was loaded
        restaurants = restaurant_store.list("restaurants")
        assert len(restaurants) > 0

        # Check that reservations store exists (even if empty)
        reservations = restaurant_store.list("reservations")
        assert isinstance(reservations, list)

    def test_get_existing_entity(self, restaurant_store: Any) -> None:
        """Test getting an entity by primary key."""
        restaurant = restaurant_store.get("restaurants", "rest_001")
        assert restaurant is not None
        assert restaurant["id"] == "rest_001"
        assert restaurant["name"] == "The Italian Corner"

    def test_get_nonexistent_entity(self, restaurant_store: Any) -> None:
        """Test getting a nonexistent entity returns None."""
        result = restaurant_store.get("restaurants", "nonexistent")
        assert result is None

    def test_get_unknown_store(self, restaurant_store: Any) -> None:
        """Test getting from an unknown store raises error."""
        with pytest.raises(UnknownStoreError) as exc_info:
            restaurant_store.get("unknown_store", "some_id")

        assert "unknown_store" in str(exc_info.value)
        assert "restaurants" in str(exc_info.value)


class TestList:
    """Test list operations with filtering and sorting."""

    def test_list_all(self, restaurant_store: Any) -> None:
        """Test listing all entities in a store."""
        restaurants = restaurant_store.list("restaurants")
        assert len(restaurants) >= 3

        # Check that results are sorted by PK by default
        ids = [r["id"] for r in restaurants]
        assert ids == sorted(ids)

    def test_list_with_equality_filter(self, restaurant_store: Any) -> None:
        """Test filtering with exact equality."""
        results = restaurant_store.list("restaurants", where={"cuisine": "Italian"})
        assert len(results) >= 1
        assert all(r["cuisine"] == "Italian" for r in results)

    def test_list_with_case_insensitive_filter(self, restaurant_store: Any) -> None:
        """Test filtering with case-insensitive equality."""
        results = restaurant_store.list(
            "restaurants", where={"location.city": {"$ieq": "boston"}}
        )
        assert len(results) >= 1
        assert all(r["location"]["city"].lower() == "boston" for r in results)

    def test_list_with_in_filter(self, restaurant_store: Any) -> None:
        """Test filtering with $in operator."""
        results = restaurant_store.list(
            "restaurants", where={"price_tier": {"$in": [2, 3]}}
        )
        assert len(results) >= 1
        assert all(r["price_tier"] in [2, 3] for r in results)

    def test_list_with_range_filters(self, restaurant_store: Any) -> None:
        """Test filtering with range operators."""
        # Greater than or equal
        results = restaurant_store.list("restaurants", where={"rating": {"$gte": 4.5}})
        assert len(results) >= 1
        assert all(r["rating"] >= 4.5 for r in results)

        # Less than
        results = restaurant_store.list("restaurants", where={"price_tier": {"$lt": 3}})
        assert len(results) >= 1
        assert all(r["price_tier"] < 3 for r in results)

    def test_list_with_nested_path(self, restaurant_store: Any) -> None:
        """Test filtering on nested object fields."""
        results = restaurant_store.list(
            "restaurants", where={"location.city": "Boston"}
        )
        assert len(results) >= 1
        assert all(r["location"]["city"] == "Boston" for r in results)

    def test_list_with_multiple_filters(self, restaurant_store: Any) -> None:
        """Test that multiple filters are ANDed together."""
        results = restaurant_store.list(
            "restaurants", where={"location.city": "Boston", "price_tier": {"$lte": 3}}
        )
        assert all(
            r["location"]["city"] == "Boston" and r["price_tier"] <= 3 for r in results
        )

    def test_list_with_sort(self, restaurant_store: Any) -> None:
        """Test sorting results."""
        results = restaurant_store.list("restaurants", sort=[("rating", "desc")])
        ratings = [r["rating"] for r in results]
        assert ratings == sorted(ratings, reverse=True)

    def test_list_with_limit(self, restaurant_store: Any) -> None:
        """Test limiting results."""
        results = restaurant_store.list("restaurants", limit=2)
        assert len(results) == 2


class TestCount:
    """Test count operations."""

    def test_count_all(self, restaurant_store: Any) -> None:
        """Test counting all entities."""
        count = restaurant_store.count("restaurants")
        assert count >= 3

    def test_count_with_filter(self, restaurant_store: Any) -> None:
        """Test counting with a filter."""
        count = restaurant_store.count("restaurants", where={"location.city": "Boston"})
        assert count >= 1


class TestInsert:
    """Test insert operations."""

    def test_insert_valid_entity(self, restaurant_store: Any) -> None:
        """Test inserting a valid entity."""
        new_restaurant = {
            "id": "rest_999",
            "name": "Test Restaurant",
            "cuisine": "American",
            "price_tier": 2,
            "rating": 4.0,
            "location": {
                "latitude": 42.3601,
                "longitude": -71.0589,
                "address": "123 Test St",
                "city": "Boston",
                "state": "MA",
                "postal_code": "02108",
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True,
        }

        result = restaurant_store.insert("restaurants", new_restaurant)
        assert result["id"] == "rest_999"

        # Verify it was inserted
        retrieved = restaurant_store.get("restaurants", "rest_999")
        assert retrieved is not None
        assert retrieved["name"] == "Test Restaurant"

    def test_insert_duplicate_key(self, restaurant_store: Any) -> None:
        """Test that inserting a duplicate key raises error."""
        duplicate = {
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

        with pytest.raises(DuplicateKeyError) as exc_info:
            restaurant_store.insert("restaurants", duplicate)

        assert "rest_001" in str(exc_info.value)

    def test_insert_missing_required_field(self, restaurant_store: Any) -> None:
        """Test that inserting without required fields raises validation error."""
        invalid = {
            "id": "rest_998",
            "name": "Incomplete Restaurant",
            # Missing required fields like cuisine, price_tier, etc.
        }

        with pytest.raises(ValidationError) as exc_info:
            restaurant_store.insert("restaurants", invalid)

        assert "required" in str(exc_info.value).lower()

    def test_insert_missing_primary_key(self, restaurant_store: Any) -> None:
        """Test that inserting without primary key raises validation error."""
        invalid = {
            # Missing "id" field
            "name": "No ID Restaurant",
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

        with pytest.raises(ValidationError) as exc_info:
            restaurant_store.insert("restaurants", invalid)

        assert "primary key" in str(exc_info.value).lower()


class TestUpdate:
    """Test update operations."""

    def test_update_existing_entity(self, restaurant_store: Any) -> None:
        """Test updating an existing entity."""
        result = restaurant_store.update("restaurants", "rest_001", {"rating": 4.8})

        assert result["rating"] == 4.8
        assert result["name"] == "The Italian Corner"  # Other fields unchanged

        # Verify the update persisted
        retrieved = restaurant_store.get("restaurants", "rest_001")
        assert retrieved["rating"] == 4.8

    def test_update_nonexistent_entity(self, restaurant_store: Any) -> None:
        """Test updating a nonexistent entity raises error."""
        with pytest.raises(NotFoundError) as exc_info:
            restaurant_store.update("restaurants", "nonexistent", {"rating": 5.0})

        assert "nonexistent" in str(exc_info.value)

    def test_update_with_invalid_data(self, restaurant_store: Any) -> None:
        """Test that update validates the merged entity."""
        with pytest.raises(ValidationError):
            restaurant_store.update(
                "restaurants",
                "rest_001",
                {"rating": 10.0},  # Exceeds maximum of 5
            )


class TestDelete:
    """Test delete operations."""

    def test_delete_existing_entity(self, restaurant_store: Any) -> None:
        """Test deleting an existing entity."""
        # First insert a test entity
        test_entity = {
            "id": "rest_delete_test",
            "name": "To Be Deleted",
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
        restaurant_store.insert("restaurants", test_entity)

        # Delete it
        deleted = restaurant_store.delete("restaurants", "rest_delete_test")
        assert deleted["id"] == "rest_delete_test"

        # Verify it's gone
        result = restaurant_store.get("restaurants", "rest_delete_test")
        assert result is None

    def test_delete_nonexistent_entity(self, restaurant_store: Any) -> None:
        """Test deleting a nonexistent entity raises error."""
        with pytest.raises(NotFoundError) as exc_info:
            restaurant_store.delete("restaurants", "nonexistent")

        assert "nonexistent" in str(exc_info.value)


class TestReset:
    """Test reset functionality."""

    def test_reset_restores_seed(self, restaurant_store: Any) -> None:
        """Test that reset restores the store to seed state."""
        # Make some changes
        restaurant_store.insert(
            "restaurants",
            {
                "id": "rest_temp",
                "name": "Temporary",
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
            },
        )
        restaurant_store.update("restaurants", "rest_001", {"rating": 5.0})

        # Reset
        restaurant_store.reset()

        # Verify temp entity is gone
        assert restaurant_store.get("restaurants", "rest_temp") is None

        # Verify original entity is restored
        original = restaurant_store.get("restaurants", "rest_001")
        assert original["rating"] == 4.5  # Original value


class TestSnapshot:
    """Test snapshot functionality."""

    def test_snapshot_returns_all_data(self, restaurant_store: Any) -> None:
        """Test that snapshot returns complete state."""
        snapshot = restaurant_store.snapshot()

        assert "restaurants" in snapshot
        assert "reservations" in snapshot
        assert "cancellations" in snapshot

        assert len(snapshot["restaurants"]) >= 3
        assert isinstance(snapshot["restaurants"], list)


class TestIsolation:
    """Test that returned entities are isolated from internal state."""

    def test_get_returns_copy(self, restaurant_store: Any) -> None:
        """Test that get returns a deep copy."""
        entity1 = restaurant_store.get("restaurants", "rest_001")
        entity2 = restaurant_store.get("restaurants", "rest_001")

        # Modify one
        entity1["name"] = "Modified"

        # Other should be unchanged
        assert entity2["name"] == "The Italian Corner"

        # Store should be unchanged
        entity3 = restaurant_store.get("restaurants", "rest_001")
        assert entity3["name"] == "The Italian Corner"

    def test_list_returns_copies(self, restaurant_store: Any) -> None:
        """Test that list returns deep copies."""
        entities1 = restaurant_store.list("restaurants")
        entities2 = restaurant_store.list("restaurants")

        # Modify one
        entities1[0]["name"] = "Modified"

        # Other should be unchanged
        assert entities2[0]["name"] != "Modified"


class TestBadQueries:
    """Test error handling for malformed queries."""

    def test_unknown_operator(self, restaurant_store: Any) -> None:
        """Test that unknown operators raise BadQueryError."""
        with pytest.raises(BadQueryError):
            restaurant_store.list("restaurants", where={"name": {"$unknown": "value"}})

    def test_invalid_sort_field(self, restaurant_store: Any) -> None:
        """Test that sorting on nonexistent field raises error."""
        with pytest.raises(BadQueryError):
            restaurant_store.list("restaurants", sort=[("nonexistent_field", "asc")])


# Made with Bob
