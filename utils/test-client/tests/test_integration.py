"""Integration tests for test client functionality."""

import json
from pathlib import Path

import pytest
import yaml

from src.ui_components import load_spec_from_file


class TestExampleFilesIntegration:
    """Integration tests for loading example files."""
    
    def test_load_sample_yaml_file(self):
        """Test loading the actual sample YAML file."""
        file_path = Path("examples/sample_openapi.yaml")
        
        # Skip if file doesn't exist (CI environment)
        if not file_path.exists():
            pytest.skip("Example file not found")
        
        spec = load_spec_from_file(str(file_path))
        
        assert spec is not None
        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Sample Calculator API"
        assert "/add" in spec["paths"]
        assert "/multiply" in spec["paths"]
    
    def test_load_sample_json_file(self):
        """Test loading the actual sample JSON file."""
        file_path = Path("examples/sample_openapi.json")
        
        # Skip if file doesn't exist (CI environment)
        if not file_path.exists():
            pytest.skip("Example file not found")
        
        spec = load_spec_from_file(str(file_path))
        
        assert spec is not None
        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Sample Calculator API"
        assert "/add" in spec["paths"]
        assert "/multiply" in spec["paths"]
    
    def test_yaml_and_json_produce_same_spec(self):
        """Test that YAML and JSON versions produce equivalent specs."""
        yaml_path = Path("examples/sample_openapi.yaml")
        json_path = Path("examples/sample_openapi.json")
        
        # Skip if files don't exist
        if not yaml_path.exists() or not json_path.exists():
            pytest.skip("Example files not found")
        
        yaml_spec = load_spec_from_file(str(yaml_path))
        json_spec = load_spec_from_file(str(json_path))
        
        assert yaml_spec is not None
        assert json_spec is not None
        
        # Compare key fields
        assert yaml_spec["openapi"] == json_spec["openapi"]
        assert yaml_spec["info"] == json_spec["info"]
        assert set(yaml_spec["paths"].keys()) == set(json_spec["paths"].keys())

# Made with Bob
