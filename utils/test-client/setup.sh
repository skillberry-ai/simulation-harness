#!/bin/bash
# Setup script for test client virtual environment

set -e

echo "Setting up test client virtual environment..."

# Check if uv is available
if command -v uv &> /dev/null; then
    echo "Using uv to create virtual environment..."
    uv venv
    source .venv/bin/activate
    echo "Installing dependencies with uv..."
    uv pip install -r requirements.txt
else
    echo "uv not found, using standard venv..."
    python -m venv .venv
    source .venv/bin/activate
    echo "Installing dependencies with pip..."
    pip install -r requirements.txt
fi

echo ""
echo "✓ Setup complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
echo "To start the test client, run:"
echo "  streamlit run app.py"

# Made with Bob
