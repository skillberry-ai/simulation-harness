"""Pytest configuration for test-client tests."""

import sys
from pathlib import Path

# Add parent directory to path so we can import lib modules
test_client_dir = Path(__file__).parent.parent
sys.path.insert(0, str(test_client_dir))

# Made with Bob
