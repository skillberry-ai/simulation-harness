# Simulation Harness Test Client

Interactive Streamlit web client for testing the Simulation Harness API and MCP interface.

## Quick Start

The test client uses its own isolated virtual environment to avoid conflicts with the main project dependencies.

```bash
cd utils/test-client
make setup    # One-time setup
make run      # Start the test client
```

## Installation

### Using Make (Recommended)

```bash
cd utils/test-client
make setup    # Creates venv and installs dependencies
make run      # Starts Streamlit test client
```

Available make targets:
- `make setup` - Create virtual environment and install dependencies
- `make install` - Update dependencies in existing venv
- `make run` - Start the Streamlit test client
- `make clean` - Remove virtual environment
- `make help` - Show all available targets

### Manual Setup with uv

```bash
cd utils/test-client
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
streamlit run app.py
```

### Manual Setup with pip

```bash
cd utils/test-client
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Usage

1. Start the simulation harness (from project root):
```bash
make restart
```

2. In a separate terminal, start the test client:
```bash
cd utils/test-client
make run
```

## Example Workflow

### 1. Start the Harness

```bash
# Terminal 1
python -m simulation_harness
```

### 2. Start the Test Client

```bash
# Terminal 2
cd utils/test-client
make run
```

### 3. Test the API

1. Click "Test Connection" in sidebar
2. Go to "API" tab
3. Click "Load Example Spec"
4. Click "Create Simulation"
5. Wait for success message
6. Click "Get Simulation" to verify

### 4. Test MCP Tools

1. Go to "MCP" tab
2. Click "List Tools"
3. Select a tool from dropdown
4. Fill in parameters
5. Click "Call Tool"
6. View results

### 5. View History

1. Go to "History" tab
2. See all requests and responses
3. Export as JSON if needed

## Troubleshooting

**Connection Failed**
- Verify harness is running: `curl http://localhost:8086/health`
- Check URL in sidebar matches harness port
- Check firewall settings

**Simulation Creation Failed**
- Verify OpenAPI spec is valid YAML/JSON
- Check harness logs for errors
- Try with example spec first

**MCP Tools Not Loading**
- Ensure simulation is created first
- Check harness MCP transport is SSE
- Verify no other simulation is active

## Development

Run tests:
```bash
cd utils/test-client
python -m pytest tests/
```

Format code:
```bash
black lib/ app.py
```

3. Open your browser to http://localhost:8501

## Features

- **Connection Management**: Configure and test harness connection
- **API Testing**: Create/get/delete simulations, reset sessions
- **MCP Testing**: List and call MCP tools
- **History Tracking**: View all requests and responses
- **Real-time Feedback**: Color-coded status and response times

## Configuration

Default harness URL: http://localhost:8086

Override via environment variable:
```bash
export HARNESS_URL=http://custom-host:8086
streamlit run app.py