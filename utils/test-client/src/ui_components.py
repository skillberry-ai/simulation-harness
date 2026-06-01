"""Reusable UI components for test client."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import streamlit as st
import yaml


def load_spec_from_file(file_path: str) -> Optional[dict[str, Any]]:
    """Load OpenAPI spec from a file.
    
    Args:
        file_path: Path to the spec file (YAML or JSON)
        
    Returns:
        Parsed spec dictionary or None if loading fails
    """
    try:
        with open(file_path, "r") as f:
            content = f.read()
        
        # Try YAML first
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError:
            # Try JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def render_connection_status(connected: bool, error: Optional[str] = None) -> None:
    """Render connection status indicator.
    
    Args:
        connected: Whether connected to harness
        error: Optional error message
    """
    if connected:
        st.success("✅ Connected to harness")
    elif error:
        st.error(f"❌ Connection failed: {error}")
    else:
        st.warning("⚠️ Not connected")


def render_json_viewer(data: dict[str, Any], title: str = "Response") -> None:
    """Render JSON data in an expandable viewer.
    
    Args:
        data: JSON data to display
        title: Title for the expander
    """
    with st.expander(title, expanded=True):
        st.json(data)


def render_response_metrics(
    status_code: int,
    duration_ms: float,
    success: bool,
) -> None:
    """Render response metrics.
    
    Args:
        status_code: HTTP status code
        duration_ms: Response time in milliseconds
        success: Whether request was successful
    """
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if success:
            st.metric("Status", f"✅ {status_code}")
        else:
            st.metric("Status", f"❌ {status_code}")
    
    with col2:
        st.metric("Duration", f"{duration_ms:.2f} ms")
    
    with col3:
        st.metric("Success", "Yes" if success else "No")


def render_openapi_editor() -> Optional[dict[str, Any]]:
    """Render OpenAPI spec editor.
    
    Returns:
        Parsed OpenAPI spec or None if invalid
    """
    st.subheader("OpenAPI Specification")
    
    # Get list of example files
    examples_dir = Path("examples")
    example_files = []
    if examples_dir.exists():
        example_files = sorted([
            f.name for f in examples_dir.iterdir()
            if f.is_file() and f.suffix in ['.json', '.yaml', '.yml']
        ])
    
    # Option to load example with file selector
    col1, col2 = st.columns([3, 1])
    with col1:
        if example_files:
            selected_file = st.selectbox(
                "Select example spec",
                options=[""] + example_files,
                format_func=lambda x: "Choose a file..." if x == "" else x,
                key="example_file_selector"
            )
        else:
            st.info("No example files found in examples/ directory")
            selected_file = ""
    
    with col2:
        load_button = st.button(
            "Load Example Spec",
            disabled=not selected_file,
            use_container_width=True
        )
    
    if load_button and selected_file:
        try:
            file_path = examples_dir / selected_file
            spec = load_spec_from_file(str(file_path))
            if spec:
                # Convert to YAML string for display
                spec_text = yaml.dump(spec, default_flow_style=False, sort_keys=False)
                st.session_state.openapi_text = spec_text
                st.success(f"✅ Loaded {selected_file}")
                st.rerun()
            else:
                st.error(f"Failed to parse {selected_file}")
        except Exception as e:
            st.error(f"Failed to load example: {e}")
    
    # Text area for spec
    spec_text = st.text_area(
        "Paste OpenAPI spec (YAML or JSON)",
        value=st.session_state.get("openapi_text", ""),
        height=300,
    )
    
    if not spec_text:
        return None
    
    # Try to parse
    try:
        # Try YAML first
        spec = yaml.safe_load(spec_text)
        st.success("✅ Valid OpenAPI spec")
        return spec
    except yaml.YAMLError:
        # Try JSON
        try:
            spec = json.loads(spec_text)
            st.success("✅ Valid OpenAPI spec")
            return spec
        except json.JSONDecodeError as e:
            st.error(f"❌ Invalid spec: {e}")
            return None


def render_tool_form(tool: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Render dynamic form for tool arguments.
    
    Args:
        tool: Tool schema
        
    Returns:
        Arguments dictionary or None if form not submitted
    """
    st.subheader(f"Call Tool: {tool['name']}")
    st.write(tool.get("description", "No description"))
    
    # Extract schema
    input_schema = tool.get("inputSchema", {})
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    
    if not properties:
        st.info("This tool has no parameters")
        if st.button("Call Tool"):
            return {}
        return None
    
    # Build form
    with st.form(key=f"tool_form_{tool['name']}"):
        arguments = {}
        
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "string")
            prop_desc = prop_schema.get("description", "")
            is_required = prop_name in required
            
            label = f"{prop_name} {'*' if is_required else ''}"
            
            if prop_type == "string":
                value = st.text_input(label, help=prop_desc)
                if value or is_required:
                    arguments[prop_name] = value

            elif prop_type == "number":
                if is_required:
                    arguments[prop_name] = st.number_input(label, help=prop_desc, value=0.0)
                else:
                    raw = st.text_input(label, help=f"{prop_desc} (optional — leave blank to omit)")
                    if raw.strip():
                        try:
                            arguments[prop_name] = float(raw)
                        except ValueError:
                            st.warning(f"{prop_name}: expected a number")

            elif prop_type == "integer":
                if is_required:
                    arguments[prop_name] = int(st.number_input(label, help=prop_desc, value=0, step=1))
                else:
                    raw = st.text_input(label, help=f"{prop_desc} (optional — leave blank to omit)")
                    if raw.strip():
                        try:
                            arguments[prop_name] = int(raw)
                        except ValueError:
                            st.warning(f"{prop_name}: expected an integer")

            elif prop_type == "boolean":
                if is_required:
                    arguments[prop_name] = st.checkbox(label, help=prop_desc)
                else:
                    choice = st.selectbox(
                        label,
                        options=["(omit)", "true", "false"],
                        help=f"{prop_desc} (optional)",
                    )
                    if choice != "(omit)":
                        arguments[prop_name] = choice == "true"

            else:
                # Fallback to text input
                value = st.text_input(label, help=f"{prop_desc} (type: {prop_type})")
                if value:
                    arguments[prop_name] = value
        
        submitted = st.form_submit_button("Call Tool")
        
        if submitted:
            # Validate required fields
            missing = [r for r in required if r not in arguments or not arguments[r]]
            if missing:
                st.error(f"Missing required fields: {', '.join(missing)}")
                return None
            return arguments
    
    return None


def render_history_table(history: list) -> None:
    """Render request history table.
    
    Args:
        history: List of RequestRecord objects
    """
    if not history:
        st.info("No requests yet")
        return
    
    # Build table data
    table_data = []
    for record in reversed(history):  # Most recent first
        table_data.append({
            "Time": record.timestamp.strftime("%H:%M:%S"),
            "Method": record.method,
            "Endpoint": record.endpoint,
            "Status": record.response_status,
            "Duration": f"{record.duration_ms:.0f}ms",
            "Success": "✅" if record.error is None else "❌",
        })
    
    st.dataframe(table_data, use_container_width=True)
    
    # Export button
    if st.button("Export History as JSON"):
        export_data = [
            {
                "timestamp": r.timestamp.isoformat(),
                "method": r.method,
                "endpoint": r.endpoint,
                "request_data": r.request_data,
                "response_status": r.response_status,
                "response_data": r.response_data,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in history
        ]
        st.download_button(
            "Download JSON",
            data=json.dumps(export_data, indent=2),
            file_name=f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
        )

# Made with Bob
