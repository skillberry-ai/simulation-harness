"""Tests for StoreRegistry."""

import pytest
from pathlib import Path

from simulation_harness.state import StoreRegistry


@pytest.fixture
def skill_dir():
    """Path to the restaurant reservation skill."""
    return Path("skills-store/restaurant-reservation-api")


@pytest.fixture
def registry(skill_dir):
    """Create a StoreRegistry instance."""
    return StoreRegistry(skill_dir)


class TestRegistryBasics:
    """Test basic registry operations."""
    
    def test_create_registry(self, skill_dir):
        """Test creating a registry."""
        registry = StoreRegistry(skill_dir)
        assert registry is not None
        assert registry.thread_count() == 0
    
    def test_for_thread_creates_store(self, registry):
        """Test that for_thread creates a store on first access."""
        assert registry.thread_count() == 0
        
        store = registry.for_thread("thread_1")
        assert store is not None
        assert registry.thread_count() == 1
    
    def test_for_thread_returns_same_store(self, registry):
        """Test that for_thread returns the same store for the same thread."""
        store1 = registry.for_thread("thread_1")
        store2 = registry.for_thread("thread_1")
        
        assert store1 is store2
        assert registry.thread_count() == 1


class TestThreadIsolation:
    """Test that threads have isolated stores."""
    
    def test_different_threads_get_different_stores(self, registry):
        """Test that different threads get different store instances."""
        store1 = registry.for_thread("thread_1")
        store2 = registry.for_thread("thread_2")
        
        assert store1 is not store2
        assert registry.thread_count() == 2
    
    def test_writes_are_isolated(self, registry):
        """Test that writes to one thread don't affect another."""
        store1 = registry.for_thread("thread_1")
        store2 = registry.for_thread("thread_2")
        
        # Insert into thread 1
        store1.insert("restaurants", {
            "id": "rest_thread1",
            "name": "Thread 1 Restaurant",
            "cuisine": "Test",
            "price_tier": 1,
            "rating": 3.0,
            "location": {
                "latitude": 42.0,
                "longitude": -71.0,
                "address": "Test",
                "city": "Test",
                "state": "MA",
                "postal_code": "00000"
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True
        })
        
        # Verify it's in thread 1
        assert store1.get("restaurants", "rest_thread1") is not None
        
        # Verify it's NOT in thread 2
        assert store2.get("restaurants", "rest_thread1") is None


class TestReset:
    """Test reset functionality."""
    
    def test_reset_restores_seed(self, registry):
        """Test that reset restores a thread's store to seed state."""
        store = registry.for_thread("thread_1")
        
        # Make a change
        store.insert("restaurants", {
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
                "postal_code": "00000"
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True
        })
        
        # Verify it exists
        assert store.get("restaurants", "rest_temp") is not None
        
        # Reset
        registry.reset("thread_1")
        
        # Verify it's gone
        store_after = registry.for_thread("thread_1")
        assert store_after.get("restaurants", "rest_temp") is None
    
    def test_reset_nonexistent_thread(self, registry):
        """Test that resetting a nonexistent thread doesn't crash."""
        # Should not raise
        registry.reset("nonexistent_thread")


class TestDrop:
    """Test drop functionality."""
    
    def test_drop_removes_store(self, registry):
        """Test that drop removes a thread's store."""
        store = registry.for_thread("thread_1")
        assert registry.thread_count() == 1
        
        registry.drop("thread_1")
        assert registry.thread_count() == 0
    
    def test_drop_nonexistent_thread(self, registry):
        """Test that dropping a nonexistent thread doesn't crash."""
        # Should not raise
        registry.drop("nonexistent_thread")
    
    def test_drop_recreates_fresh_store(self, registry):
        """Test that accessing a dropped thread creates a fresh store."""
        store1 = registry.for_thread("thread_1")
        
        # Make a change
        store1.insert("restaurants", {
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
                "postal_code": "00000"
            },
            "phone": "+1-555-000-0000",
            "accepts_reservations": True
        })
        
        # Drop
        registry.drop("thread_1")
        
        # Access again - should get fresh store
        store2 = registry.for_thread("thread_1")
        assert store2.get("restaurants", "rest_temp") is None


class TestDropAll:
    """Test drop_all functionality."""
    
    def test_drop_all_removes_all_stores(self, registry):
        """Test that drop_all removes all stores."""
        registry.for_thread("thread_1")
        registry.for_thread("thread_2")
        registry.for_thread("thread_3")
        
        assert registry.thread_count() == 3
        
        registry.drop_all()
        assert registry.thread_count() == 0

# Made with Bob
