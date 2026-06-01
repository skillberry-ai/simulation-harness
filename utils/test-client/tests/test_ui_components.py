"""Tests for UI components."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import yaml

from src.ui_components import load_spec_from_file


class TestLoadSpecFromFile:
    """Tests for load_spec_from_file function."""
    
    def test_loads_yaml_file_successfully(self):
        """Test loading a valid YAML file."""
        yaml_content = """
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths:
  /test:
    get:
      summary: Test endpoint
"""
        expected_spec = yaml.safe_load(yaml_content)
        
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            result = load_spec_from_file("/path/to/spec.yaml")
        
        assert result == expected_spec
    
    def test_loads_json_file_successfully(self):
        """Test loading a valid JSON file."""
        json_content = {
            "openapi": "3.0.0",
            "info": {
                "title": "Test API",
                "version": "1.0.0"
            },
            "paths": {
                "/test": {
                    "get": {
                        "summary": "Test endpoint"
                    }
                }
            }
        }
        json_str = json.dumps(json_content)
        
        with patch("builtins.open", mock_open(read_data=json_str)):
            result = load_spec_from_file("/path/to/spec.json")
        
        assert result == json_content
    
    def test_returns_none_for_invalid_yaml(self):
        """Test that invalid YAML returns None."""
        invalid_yaml = "invalid: yaml: content: [unclosed"
        
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            result = load_spec_from_file("/path/to/spec.yaml")
        
        assert result is None
    
    def test_returns_none_for_invalid_json(self):
        """Test that invalid JSON returns None."""
        invalid_json = '{"invalid": json content'
        
        with patch("builtins.open", mock_open(read_data=invalid_json)):
            result = load_spec_from_file("/path/to/spec.json")
        
        assert result is None
    
    def test_returns_none_for_nonexistent_file(self):
        """Test that nonexistent file returns None."""
        with patch("builtins.open", side_effect=FileNotFoundError()):
            result = load_spec_from_file("/path/to/nonexistent.yaml")
        
        assert result is None
    
    def test_returns_none_for_permission_error(self):
        """Test that permission error returns None."""
        with patch("builtins.open", side_effect=PermissionError()):
            result = load_spec_from_file("/path/to/spec.yaml")
        
        assert result is None
    
    def test_returns_none_for_os_error(self):
        """Test that OS error returns None."""
        with patch("builtins.open", side_effect=OSError("Disk error")):
            result = load_spec_from_file("/path/to/spec.yaml")
        
        assert result is None

# Made with Bob
