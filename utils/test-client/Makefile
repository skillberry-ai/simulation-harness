.PHONY: help setup install run clean

# Default target
help:
	@echo "Test Client Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make setup    - Create virtual environment and install dependencies"
	@echo "  make install  - Install/update dependencies (venv must exist)"
	@echo "  make run      - Start the Streamlit test client"
	@echo "  make clean    - Remove virtual environment"
	@echo ""

# Create virtual environment and install dependencies
setup:
	@echo "Creating virtual environment..."
	@if command -v uv >/dev/null 2>&1; then \
		echo "Using uv..."; \
		uv venv; \
		. .venv/bin/activate && uv pip install -r requirements.txt; \
	else \
		echo "Using standard venv..."; \
		python -m venv .venv; \
		. .venv/bin/activate && pip install -r requirements.txt; \
	fi
	@echo ""
	@echo "✓ Setup complete!"
	@echo "Run 'make run' to start the test client"

# Install/update dependencies in existing venv
install:
	@if [ ! -d ".venv" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "Installing dependencies..."
	@if command -v uv >/dev/null 2>&1; then \
		. .venv/bin/activate && uv pip install -r requirements.txt; \
	else \
		. .venv/bin/activate && pip install -r requirements.txt; \
	fi
	@echo "✓ Dependencies installed"

# Start the Streamlit test client
run:
	@if [ ! -d ".venv" ]; then \
		echo "Error: Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "Starting test client..."
	@. .venv/bin/activate && streamlit run app.py

# Remove virtual environment
clean:
	@echo "Removing virtual environment..."
	@rm -rf .venv
	@echo "✓ Cleaned"

# Made with Bob
