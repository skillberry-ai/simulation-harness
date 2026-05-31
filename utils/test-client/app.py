"""Streamlit test client for simulation harness."""

import asyncio
import os
from datetime import datetime

import streamlit as st
import yaml

from lib.api_client import HarnessAPIClient
from lib.mcp_client import HarnessMCPClient
from lib.state import get_state
from lib.ui_components import (
    render_connection_status,
    render_history_table,
    render_json_viewer,
    render_openapi_editor,
    render_response_metrics,
    render_tool_form,
)

# Page config
st.set_page_config(
    page_title="Harness Test Client",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Title
st.title("🧪 Simulation Harness Test Client")
st.markdown("Interactive client for testing API and MCP interfaces")

# Get state
state = get_state()

# Sidebar - Connection Settings
with st.sidebar:
    st.header("⚙️ Connection Settings")
    
    # URL input
    harness_url = st.text_input(
        "Harness URL",
        value=os.getenv("HARNESS_URL", state.harness_url),
        help="Base URL of the running harness",
    )
    
    if harness_url != state.harness_url:
        state.harness_url = harness_url
        state.connected = False
    
    # Test connection button
    if st.button("🔌 Test Connection", use_container_width=True):
        async def test_connection():
            client = HarnessAPIClient(state.harness_url)
            response = await client.health_check()
            await client.close()
            return response
        
        response = asyncio.run(test_connection())
        
        if response.success:
            state.connected = True
            state.connection_error = None
            st.success(f"✅ Connected ({response.duration_ms:.0f}ms)")
        else:
            state.connected = False
            state.connection_error = response.error
            st.error(f"❌ Connection failed: {response.error}")
    
    # Connection status
    st.divider()
    render_connection_status(state.connected, state.connection_error)
    
    # Current simulation info
    if state.simulation_name:
        st.divider()
        st.subheader("📊 Current Simulation")
        st.write(f"**Name:** {state.simulation_name}")
        st.write(f"**Status:** {state.simulation_status}")
        if state.simulation_created_at:
            st.write(f"**Created:** {state.simulation_created_at.strftime('%H:%M:%S')}")

# Main content - Tabs
tab1, tab2, tab3, tab4 = st.tabs(["🔌 Connection", "🌐 API", "🛠️ MCP", "📜 History"])

# Tab 1: Connection
with tab1:
    st.header("Connection Test")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Configuration")
        st.code(f"""
Harness URL: {state.harness_url}
Connected: {state.connected}
        """)
    
    with col2:
        st.subheader("Quick Test")
        if st.button("Run Health Check"):
            async def health_check():
                client = HarnessAPIClient(state.harness_url)
                response = await client.health_check()
                await client.close()
                return response
            
            response = asyncio.run(health_check())
            
            render_response_metrics(
                response.status_code,
                response.duration_ms,
                response.success,
            )
            
            if response.data:
                render_json_viewer(response.data, "Health Check Response")

# Tab 2: API Testing
with tab2:
    st.header("REST API Testing")
    
    # Create Simulation
    st.subheader("1️⃣ Create Simulation")
    
    spec = render_openapi_editor()
    
    col1, col2 = st.columns([3, 1])
    with col1:
        regenerate = st.checkbox("Regenerate skill if exists", value=False)
    with col2:
        create_button = st.button("Create Simulation", type="primary", disabled=spec is None)
    
    if create_button and spec:
        async def create_sim():
            client = HarnessAPIClient(state.harness_url)
            response = await client.create_simulation(spec, regenerate)
            await client.close()
            return response
        
        response = asyncio.run(create_sim())
        
        # Add to history
        state.add_request(
            "POST",
            "/api/v1/simulation",
            {"openapi_spec": spec, "regenerate_skill": regenerate},
            response.status_code,
            response.data,
            response.duration_ms,
            response.error,
        )
        
        render_response_metrics(
            response.status_code,
            response.duration_ms,
            response.success,
        )
        
        if response.success and response.data:
            # Update state
            state.update_simulation(
                name=response.data.get("name"),
                status=response.data.get("status"),
                created_at=datetime.fromisoformat(response.data.get("created_at")),
                mcp_endpoint=response.data.get("mcp_endpoint"),
            )
            render_json_viewer(response.data, "Simulation Created")
        elif response.error:
            st.error(f"Error: {response.error}")
    
    st.divider()
    
    # Get Simulation
    st.subheader("2️⃣ Get Simulation Status")
    
    if st.button("Get Simulation"):
        async def get_sim():
            client = HarnessAPIClient(state.harness_url)
            response = await client.get_simulation()
            await client.close()
            return response
        
        response = asyncio.run(get_sim())
        
        state.add_request(
            "GET",
            "/api/v1/simulation",
            None,
            response.status_code,
            response.data,
            response.duration_ms,
            response.error,
        )
        
        render_response_metrics(
            response.status_code,
            response.duration_ms,
            response.success,
        )
        
        if response.success and response.data:
            state.update_simulation(
                name=response.data.get("name"),
                status=response.data.get("status"),
                created_at=datetime.fromisoformat(response.data.get("created_at")),
                mcp_endpoint=response.data.get("mcp_endpoint"),
            )
            render_json_viewer(response.data, "Simulation Status")
        elif response.error:
            st.error(f"Error: {response.error}")
    
    st.divider()
    
    # Reset Session
    st.subheader("3️⃣ Reset Session")
    
    if st.button("Reset Session"):
        async def reset_sess():
            client = HarnessAPIClient(state.harness_url)
            response = await client.reset_session()
            await client.close()
            return response
        
        response = asyncio.run(reset_sess())
        
        state.add_request(
            "POST",
            "/api/v1/simulation/reset",
            None,
            response.status_code,
            response.data,
            response.duration_ms,
            response.error,
        )
        
        render_response_metrics(
            response.status_code,
            response.duration_ms,
            response.success,
        )
        
        if response.success:
            st.success("Session reset successfully")
            if response.data:
                render_json_viewer(response.data, "Reset Response")
        elif response.error:
            st.error(f"Error: {response.error}")
    
    st.divider()
    
    # Delete Simulation
    st.subheader("4️⃣ Delete Simulation")
    
    if st.button("Delete Simulation", type="secondary"):
        async def delete_sim():
            client = HarnessAPIClient(state.harness_url)
            response = await client.delete_simulation()
            await client.close()
            return response
        
        response = asyncio.run(delete_sim())
        
        state.add_request(
            "DELETE",
            "/api/v1/simulation",
            None,
            response.status_code,
            None,
            response.duration_ms,
            response.error,
        )
        
        render_response_metrics(
            response.status_code,
            response.duration_ms,
            response.success,
        )
        
        if response.success:
            state.clear_simulation()
            st.success("Simulation deleted successfully")
        elif response.error:
            st.error(f"Error: {response.error}")

# Tab 3: MCP Testing
with tab3:
    st.header("MCP Interface Testing")
    
    if not state.simulation_name:
        st.warning("⚠️ Create a simulation first to test MCP tools")
    else:
        # List Tools
        st.subheader("1️⃣ List Available Tools")
        
        if st.button("List Tools", key="list_tools_btn"):
            with st.spinner("Fetching tools..."):
                try:
                    async def list_tools_with_timeout():
                        client = HarnessMCPClient(state.harness_url)
                        try:
                            # Add 10 second timeout
                            response = await asyncio.wait_for(
                                client.list_tools(),
                                timeout=10.0
                            )
                            await client.close()
                            return response
                        except asyncio.TimeoutError:
                            await client.close()
                            from lib.mcp_client import MCPResponse
                            return MCPResponse(
                                success=False,
                                data=None,
                                error="Timeout: MCP connection took longer than 10 seconds",
                                duration_ms=10000
                            )
                    
                    st.write("DEBUG: About to run asyncio.run()")
                    response = asyncio.run(list_tools_with_timeout())
                    st.write(f"DEBUG: asyncio.run() completed, response={response}")
                    
                    # Store in session state for persistence
                    st.session_state.last_list_tools_response = response
                    st.write("DEBUG: Stored in session state")
                except Exception as e:
                    st.error(f"Exception during list_tools: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    # Store error in session state too
                    from lib.mcp_client import MCPResponse
                    st.session_state.last_list_tools_response = MCPResponse(
                        success=False,
                        data=None,
                        error=str(e),
                        duration_ms=0
                    )
        
        # Display response if it exists in session state
        if hasattr(st.session_state, 'last_list_tools_response'):
            response = st.session_state.last_list_tools_response
            
            # Debug output
            st.write(f"DEBUG: Response success={response.success}")
            st.write(f"DEBUG: Response data={response.data}")
            st.write(f"DEBUG: Response error={response.error}")
            st.write(f"DEBUG: Response duration={response.duration_ms}ms")
            
            render_response_metrics(
                200 if response.success else 500,
                response.duration_ms,
                response.success,
            )
            
            if response.success and response.data:
                state.mcp_tools = response.data
                state.mcp_tools_loaded = True
                st.success(f"Found {len(response.data)} tools")
                render_json_viewer({"tools": response.data}, "Available Tools")
            elif response.error:
                st.error(f"Error: {response.error}")
            else:
                st.warning("No data and no error - unexpected state")
        
        st.divider()
        
        # Call Tool
        st.subheader("2️⃣ Call Tool")
        
        if not state.mcp_tools_loaded:
            st.info("List tools first to see available options")
        else:
            # Tool selector
            tool_names = [t["name"] for t in state.mcp_tools]
            selected_tool_name = st.selectbox("Select Tool", tool_names)
            
            if selected_tool_name:
                # Find tool schema
                selected_tool = next(
                    (t for t in state.mcp_tools if t["name"] == selected_tool_name),
                    None,
                )
                
                if selected_tool:
                    # Render form
                    arguments = render_tool_form(selected_tool)
                    
                    if arguments is not None:
                        async def call_tool():
                            client = HarnessMCPClient(state.harness_url)
                            response = await client.call_tool(
                                selected_tool_name,
                                arguments,
                            )
                            await client.close()
                            return response
                        
                        response = asyncio.run(call_tool())
                        
                        render_response_metrics(
                            200 if response.success else 500,
                            response.duration_ms,
                            response.success,
                        )
                        
                        if response.data:
                            render_json_viewer(response.data, "Tool Result")
                        elif response.error:
                            st.error(f"Error: {response.error}")

# Tab 4: History
with tab4:
    st.header("Request History")
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"Total requests: {len(state.request_history)}")
    with col2:
        if st.button("Clear History"):
            state.clear_history()
            st.rerun()
    
    render_history_table(state.request_history)

# Made with Bob
