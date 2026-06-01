"""Tests for DeepAgent."""

from pathlib import Path
import pytest
from unittest.mock import Mock, AsyncMock, patch
from langchain_core.messages import SystemMessage
from simulation_harness.agent.deep_agent import DeepAgent
from simulation_harness.openapi.parser import OpenAPISpec, OpenAPIOperation


@pytest.fixture
def mock_spec():
    """Create a mock OpenAPI spec."""
    spec = Mock(spec=OpenAPISpec)
    spec.info = {"title": "Test API", "version": "1.0.0", "description": "Test"}
    spec.servers = [{"url": "https://api.example.com"}]
    return spec


@pytest.fixture
def mock_operation():
    """Create a mock OpenAPI operation."""
    op = Mock(spec=OpenAPIOperation)
    op.method = "get"
    op.path = "/users/{id}"
    op.operation_id = "getUser"
    op.summary = "Get user"
    op.description = "Get user by ID"
    op.parameters = []
    op.request_body = None
    op.get_request_schema = Mock(return_value=None)
    op.get_response_schema = Mock(
        return_value={"type": "object", "properties": {"id": {"type": "string"}}}
    )
    return op


def test_deep_agent_initialization(mock_spec, mock_operation):
    """Test DeepAgent initializes correctly."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
        session_timeout_seconds=3600,
    )

    assert agent.spec is mock_spec
    assert agent.operations == [mock_operation]
    assert agent.session_timeout_seconds == 3600
    assert agent.llm is not None
    assert agent.checkpointer is not None
    assert agent.session_manager is not None


def test_deep_agent_initialization_with_base_url(mock_spec, mock_operation):
    """Test DeepAgent initializes with custom base URL."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url="https://custom.openai.com",
        spec=mock_spec,
        operations=[mock_operation],
    )

    assert agent.llm is not None


@pytest.mark.asyncio
async def test_generate_response_basic(mock_spec, mock_operation):
    """Test generating a basic response."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    # Mock the agent's ainvoke method
    mock_message = Mock()
    mock_message.content = '{"id": "123", "name": "Test User"}'

    with patch.object(agent.agent, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
        mock_ainvoke.return_value = {"messages": [mock_message]}

        result = await agent.generate_response(
            tool_name="getUser", arguments={"id": "123"}, thread_id="test-thread"
        )

        assert result == {"id": "123", "name": "Test User"}
        mock_ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_response_with_default_thread(mock_spec, mock_operation):
    """Test generating response with default thread ID."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    mock_message = Mock()
    mock_message.content = '{"result": "ok"}'

    with patch.object(agent.agent, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
        mock_ainvoke.return_value = {"messages": [mock_message]}

        result = await agent.generate_response(
            tool_name="getUser", arguments={"id": "123"}
        )

        assert result == {"result": "ok"}


@pytest.mark.asyncio
async def test_generate_response_invalid_json(mock_spec, mock_operation):
    """Test handling invalid JSON response."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    mock_message = Mock()
    mock_message.content = "This is not JSON"

    with patch.object(agent.agent, "ainvoke", new_callable=AsyncMock) as mock_ainvoke:
        mock_ainvoke.return_value = {"messages": [mock_message]}

        result = await agent.generate_response(
            tool_name="getUser", arguments={"id": "123"}
        )

        assert "error" in result
        assert "Failed to generate valid JSON response" in result["error"]


@pytest.mark.asyncio
async def test_generate_response_tool_not_found(mock_spec, mock_operation):
    """Test handling tool not found error."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    with pytest.raises(ValueError, match="Operation not found"):
        await agent.generate_response(tool_name="nonexistentTool", arguments={})


@pytest.mark.asyncio
async def test_reset_specific_thread(mock_spec, mock_operation):
    """Test resetting a specific thread."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    # Record some activity
    agent.session_manager.record_activity("test-thread")
    assert agent.session_manager.get_active_session_count() == 1

    # Reset the thread
    await agent.reset(thread_id="test-thread")

    assert agent.session_manager.get_active_session_count() == 0


@pytest.mark.asyncio
async def test_reset_all_threads(mock_spec, mock_operation):
    """Test resetting all threads."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    # Record some activity
    agent.session_manager.record_activity("thread1")
    agent.session_manager.record_activity("thread2")
    assert agent.session_manager.get_active_session_count() == 2

    # Reset all
    await agent.reset()

    assert agent.session_manager.get_active_session_count() == 0


@pytest.mark.asyncio
async def test_shutdown(mock_spec, mock_operation):
    """Test shutting down the agent."""
    agent = DeepAgent(
        api_key="test-key",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        base_url=None,
        spec=mock_spec,
        operations=[mock_operation],
    )

    # Start session manager
    agent.start_session_cleanup()
    assert agent.session_manager._running is True

    # Shutdown
    await agent.shutdown()

    assert agent.session_manager._running is False


def test_deep_agent_uses_prompt_for_stateful_react_agent(mock_spec, mock_operation):
    """Test stateful agent creation passes system prompt via supported prompt kwarg."""
    mock_react_agent = Mock()

    with (
        patch("simulation_harness.agent.deep_agent.ChatOpenAI") as mock_chat_openai,
        patch("simulation_harness.agent.deep_agent.StoreRegistry"),
        patch(
            "simulation_harness.agent.deep_agent.create_state_tools", return_value=[]
        ),
        patch(
            "simulation_harness.agent.deep_agent.create_react_agent",
            return_value=mock_react_agent,
        ) as mock_create_react_agent,
    ):
        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_chat_openai.return_value = mock_llm

        agent = DeepAgent(
            api_key="test-key",
            model="gpt-4",
            temperature=0.7,
            max_tokens=1000,
            base_url=None,
            spec=mock_spec,
            operations=[mock_operation],
            skill_dir=Path("/tmp/test-skill"),
        )

    assert agent.agent is mock_react_agent
    mock_create_react_agent.assert_called_once()
    kwargs = mock_create_react_agent.call_args.kwargs
    assert kwargs["checkpointer"] is agent.checkpointer
    assert "prompt" in kwargs
    assert "state_modifier" not in kwargs
    assert isinstance(kwargs["prompt"], SystemMessage)
    assert kwargs["prompt"].content == agent.system_prompt


# Made with Bob
