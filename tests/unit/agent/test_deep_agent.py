"""Tests for DeepAgent."""

import pytest
from pydantic import SecretStr
from unittest.mock import Mock, AsyncMock, patch
from simulation_harness.agent.deep_agent import DeepAgent, _READONLY_FS_RULES
from simulation_harness.openapi.parser import OpenAPISpec, OpenAPIOperation
from deepagents.middleware.permissions import _check_fs_permission


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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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
        api_key=SecretStr("test-key"),
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


def test_readonly_fs_rules_deny_writes_including_dotpaths():
    """_READONLY_FS_RULES must deny writes to both normal and dot-prefixed paths.

    Approach: call deepagents' internal `_check_fs_permission` helper directly
    against the module-level `_READONLY_FS_RULES` constant.  This tests the
    *actual* glob-match behavior (not just the string content of the paths list)
    and uses the same code path that `_PermissionMiddleware` uses at runtime.
    """
    # Writes to dot-prefixed paths (the gap in the old `/**`-only rule)
    assert (
        _check_fs_permission(_READONLY_FS_RULES, "write", "/.skills/foo.txt") == "deny"
    )
    assert _check_fs_permission(_READONLY_FS_RULES, "write", "/.hidden") == "deny"
    # dot dir nested deeper: /a/b/.hidden is the dot entry; /a/b/.hidden/c is inside it
    assert _check_fs_permission(_READONLY_FS_RULES, "write", "/a/b/.hidden") == "deny"
    assert _check_fs_permission(_READONLY_FS_RULES, "write", "/a/b/.hidden/c") == "deny"
    # Writes to ordinary paths must also be denied
    assert _check_fs_permission(_READONLY_FS_RULES, "write", "/foo.txt") == "deny"
    assert _check_fs_permission(_READONLY_FS_RULES, "write", "/a/b/c.json") == "deny"
    # Reads must always be allowed (rule only covers 'write')
    assert (
        _check_fs_permission(_READONLY_FS_RULES, "read", "/.skills/foo.txt") == "allow"
    )
    assert _check_fs_permission(_READONLY_FS_RULES, "read", "/foo.txt") == "allow"


def test_stateful_branch_wires_lean_create_agent_with_skills(
    tmp_path, mock_spec, mock_operation
):
    """skill_dir present -> create_agent with skills/filesystem/permission middleware."""
    skill_dir = tmp_path / "petstore"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: petstore\ndescription: Simulate the Pet Store API.\n---\n# Pet Store\n"
    )

    with (
        patch("simulation_harness.agent.deep_agent.ChatOpenAI") as mock_chat_openai,
        patch("simulation_harness.agent.deep_agent.StoreRegistry"),
        patch(
            "simulation_harness.agent.deep_agent.create_state_tools", return_value=[]
        ),
        patch(
            "simulation_harness.agent.deep_agent.create_agent",
            return_value=Mock(),
        ) as mock_create_agent,
    ):
        mock_chat_openai.return_value = Mock()
        agent = DeepAgent(
            api_key=SecretStr("test-key"),
            model="gpt-4",
            temperature=0.0,
            max_tokens=1000,
            base_url=None,
            spec=mock_spec,
            operations=[mock_operation],
            skill_dir=skill_dir,
        )

    # The per-simulation skills root was assembled.
    assert (skill_dir / ".skills" / "petstore").is_symlink()

    # create_agent was called with the expected wiring.
    kwargs = mock_create_agent.call_args.kwargs
    assert kwargs["checkpointer"] is agent.checkpointer
    assert kwargs["system_prompt"] == agent.system_prompt
    middleware_types = [type(m).__name__ for m in kwargs["middleware"]]
    assert middleware_types == [
        "SkillsMiddleware",
        "FilesystemMiddleware",
        "_PermissionMiddleware",
    ]

    # The model must be passed UNBOUND — bind_tools must NOT have been called
    # before handing the llm to create_agent.
    mock_chat_openai.return_value.bind_tools.assert_not_called()
    # First positional arg to create_agent is the (unbound) llm instance.
    assert mock_create_agent.call_args.args[0] is mock_chat_openai.return_value


def test_empty_string_base_url_is_forwarded_not_silently_dropped(
    mock_spec, mock_operation
):
    """base_url='' must reach ChatOpenAI, not be silently omitted by a falsy check."""
    with patch("simulation_harness.agent.deep_agent.ChatOpenAI") as mock_chat:
        mock_chat.return_value = Mock()
        DeepAgent(
            api_key=SecretStr("test-key"),
            model="gpt-4",
            temperature=0.7,
            max_tokens=1000,
            base_url="",
            spec=mock_spec,
            operations=[mock_operation],
        )
        call_kwargs = mock_chat.call_args[1]
        assert "base_url" in call_kwargs, (
            "base_url='' was silently dropped — use 'if base_url is not None:'"
        )
        assert call_kwargs["base_url"] == ""


# Made with Bob
