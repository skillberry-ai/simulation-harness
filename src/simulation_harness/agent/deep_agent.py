"""Simplified Deep Agent implementation for Simulation Harness.

This module provides the main agent that generates mock responses using
LangChain and LangGraph directly (without the deepagents library).
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware, FsToolName
from deepagents.middleware.skills import SkillsMiddleware

from simulation_harness.agent.grounding import (
    Ungrounded,
    check_grounding,
    static_evidence,
)
from simulation_harness.config.env_source import llm_no_cache_requested
from simulation_harness.models.domain import Fidelity, StrictGrounding
from simulation_harness.openapi.parser import OpenAPIOperation, OpenAPISpec
from simulation_harness.utils.errors import UngroundedResponseError
from simulation_harness.state.registry import StoreRegistry
from simulation_harness.state.tools import create_state_tools
from simulation_harness.utils.logging import get_logger
from simulation_harness.agent.prompts import render_system_prompt
from simulation_harness.agent.session_manager import SessionManager
from simulation_harness.agent.skill_backend import build_skill_sources

logger = get_logger(__name__)

# The agent only ever *reads* the generated skill from the virtual filesystem;
# all mutation goes through the `state_*` tools instead.  So we allowlist the
# read-only filesystem tools and never hand the model a write-capable one.
#
# Omitted from the deepagents default set on purpose:
#   write_file, edit_file, delete — the agent must not mutate the skill
#   execute                       — needs a SandboxBackendProtocol backend,
#                                   which FilesystemBackend is not, so it could
#                                   only ever return an error
#
# This is a stronger guarantee than the deny-rules it replaces: a tool that is
# never exposed cannot be called at all, so there is no glob pattern to get
# wrong (the previous rules needed five patterns to cover dot-prefixed paths,
# because wcmatch's GLOBSTAR does not imply DOTGLOB).
_READONLY_FS_TOOLS: list[FsToolName] = ["ls", "read_file", "glob", "grep"]

# Appended to every strict-mode request. The thread accumulates up to
# max_messages turns; a per-call line keeps the closed-world rule in view.
_STRICT_REMINDER = "Fidelity: strict (closed world). Answer only from stored rows."

# Cap on ungrounded values carried in an MCP error and in the next reprompt.
_MAX_REPORTED_UNGROUNDED = 10


def _load_static_text(skill_dir: Path) -> str:
    """Spec strings plus SKILL.md: the static evidence for the grounding check."""
    api_path = skill_dir / "api.json"
    skill_path = skill_dir / "SKILL.md"
    api = json.loads(api_path.read_text()) if api_path.exists() else {}
    skill_md = skill_path.read_text() if skill_path.exists() else ""
    return static_evidence(api, skill_md)


class DeepAgent:
    """Simplified agent for generating mock API responses using LangChain/LangGraph."""

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        temperature: float,
        max_tokens: int,
        base_url: str | None,
        spec: OpenAPISpec,
        operations: list[OpenAPIOperation],
        session_timeout_seconds: int = 3600,
        skill_dir: Path | None = None,
        agent_recursion_limit: int = 50,
        fidelity: Fidelity = "generative",
        operation_kinds: dict[str, str] | None = None,
        strict_grounding: StrictGrounding = "report",
        on_ungrounded: Callable[[list[Ungrounded]], None] | None = None,
    ):
        """Initialize Deep Agent.

        Args:
            api_key: LLM API key (wrapped in SecretStr)
            model: Model name (e.g., "gpt-4")
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            base_url: Optional custom base URL for OpenAI API
            spec: OpenAPI specification
            operations: List of API operations
            session_timeout_seconds: Session timeout in seconds
            skill_dir: Optional path to skill directory for state store
            agent_recursion_limit: Maximum recursion depth for agent (default: 10)
            fidelity: Data fidelity mode ("generative" or "strict")
            operation_kinds: operationId -> OperationKind value, from the skill
                manifest; drives the strict-mode state write gate
            strict_grounding: Strict mode only: "report" logs and counts
                ungrounded responses, "enforce" raises UngroundedResponseError
            on_ungrounded: Called with the findings whenever a strict-mode
                response is ungrounded, in either grounding mode
        """
        self.spec = spec
        self.operations = operations
        self.session_timeout_seconds = session_timeout_seconds
        self.skill_dir = skill_dir
        self.agent_recursion_limit = agent_recursion_limit
        self.fidelity = fidelity
        self.operation_kinds = dict(operation_kinds or {})
        self.strict_grounding = strict_grounding
        self._on_ungrounded = on_ungrounded
        # thread_id -> values rejected on that thread's last call (enforce mode),
        # carried into the next request so the agent does not reuse them.
        self._pending_rejections: dict[str, list[Ungrounded]] = {}
        # Assembled once: the spec and skill do not change during a simulation.
        self._static_text = (
            _load_static_text(skill_dir) if fidelity == "strict" and skill_dir else ""
        )

        # Per-simulation staging dir for the skills backend, created lazily in
        # _create_agent and removed in shutdown().
        self._skill_staging_dir: Path | None = None

        # Initialize LLM
        # `max_tokens` is ChatOpenAI's declared field name; langchain_openai
        # serializes it to the API's `max_completion_tokens` for us (it is the
        # field's alias). Spell it this way rather than as the alias, to match
        # the rest of the codebase and to avoid depending on the alias surviving
        # a langchain_openai upgrade.
        llm_kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": api_key,
        }
        if base_url is not None:
            llm_kwargs["base_url"] = base_url
        # Read once per simulation: a harness started with HARNESS_LLM_NO_CACHE
        # must not let repeated runtime calls replay the gateway's cache.
        if llm_no_cache_requested():
            llm_kwargs["extra_body"] = {"cache": {"no-cache": True}}

        self.llm = ChatOpenAI(**llm_kwargs)

        # Render system prompt
        self.system_prompt = render_system_prompt(spec, fidelity=fidelity)

        logger.debug(
            f"Rendered system prompt: length={len(self.system_prompt)}, "
            f"preview={self.system_prompt[:200]}..."
        )

        # Initialize checkpointer for session management
        self.checkpointer = MemorySaver()

        # Initialize state store registry if skill_dir provided
        self.store_registry: StoreRegistry | None = None
        if skill_dir:
            self.store_registry = StoreRegistry(skill_dir)
            logger.info(f"State store registry initialized for skill: {skill_dir}")
        elif fidelity == "strict":
            logger.warning(
                "strict fidelity without a skill directory: grounding check disabled"
            )

        # Initialize session cleanup manager
        self.session_manager = SessionManager(
            checkpointer=self.checkpointer,
            timeout_seconds=session_timeout_seconds,
            max_sessions=100,  # Default max sessions
            store_registry=self.store_registry,
        )

        # Create LangGraph agent
        self.agent = self._create_agent()

        # Note: Session cleanup task is NOT started automatically
        # Call start_session_cleanup() explicitly when ready

        logger.info(
            f"Deep Agent initialized: model={model}, "
            f"operation_count={len(operations)}, "
            f"session_timeout={session_timeout_seconds}s, "
            f"state_store={'enabled' if skill_dir else 'disabled'}"
        )

    def start_session_cleanup(self) -> None:
        """Start the session cleanup background task.

        This should be called after the agent is initialized and
        an event loop is running.
        """
        self.session_manager.start()

    def _create_agent(self) -> CompiledStateGraph:
        """Create the runtime agent.

        With a skill directory, build a lean ``create_agent`` graph that loads
        the per-API skill dynamically (progressive disclosure) and exposes the
        state tools. Without one, fall back to the legacy stateless agent.
        """
        if self.store_registry and self.skill_dir:
            tools = create_state_tools()

            root_dir, sources = build_skill_sources(self.skill_dir)
            self._skill_staging_dir = Path(root_dir)
            backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

            # Read-only filesystem enforcement: expose only the non-mutating
            # filesystem tools (public `tools=` allowlist, deepagents 0.7.0+).
            middleware = [
                SkillsMiddleware(backend=backend, sources=sources),
                FilesystemMiddleware(
                    backend=backend,
                    tools=_READONLY_FS_TOOLS,
                ),
            ]

            agent = create_agent(
                self.llm,
                system_prompt=self.system_prompt,
                tools=tools,
                middleware=middleware,
                checkpointer=self.checkpointer,
            )

            logger.info(
                f"Created lean skill-loading agent: {len(tools)} state tools, "
                f"skill sources={sources}"
            )
            return agent

        # Legacy stateless agent (no skill_dir): unchanged.
        def agent_node(state: MessagesState) -> MessagesState:
            messages = state["messages"]
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=self.system_prompt)] + list(messages)
            response = self.llm.invoke(messages)
            return {"messages": messages + [response]}

        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", agent_node)
        workflow.add_edge(START, "agent")
        workflow.add_edge("agent", END)
        return workflow.compile(checkpointer=self.checkpointer)

    async def generate_response(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        thread_id: str | None = None,
    ) -> Any:
        """Generate mock response for a tool invocation.

        Args:
            tool_name: Name of the tool being invoked
            arguments: Tool arguments
            thread_id: Optional session/thread identifier for context persistence.
                      If provided, conversation history will be maintained across calls.
                      If None, uses "default" thread.

        Returns:
            Generated mock response

        Raises:
            ValueError: If tool is not found or response generation fails
        """
        # Find the operation
        operation = self._find_operation(tool_name)
        if not operation:
            raise ValueError(f"Operation not found for tool: {tool_name}")

        logger.debug(
            f"Processing request: tool={tool_name}, operation={operation.operation_id}, "
            f"arguments={arguments}"
        )

        try:
            # Determine effective thread_id
            effective_thread_id = thread_id or "default"

            # Create prompt for this specific request, carrying any values the
            # previous call on this thread was rejected for (strict, enforce).
            rejected = self._pending_rejections.pop(effective_thread_id, None)
            request_prompt = self._create_request_prompt(operation, arguments, rejected)

            logger.debug(
                f"Request prompt: tool={tool_name}, prompt={request_prompt}, "
                f"thread_id={effective_thread_id}"
            )

            # Record session activity for cleanup tracking
            self.session_manager.record_activity(effective_thread_id)

            # Build config with thread_id for session management
            config: RunnableConfig = {
                "configurable": {"thread_id": effective_thread_id},
                "recursion_limit": self.agent_recursion_limit,
            }

            # Add store_registry to config if available
            if self.store_registry:
                config["configurable"]["store_registry"] = self.store_registry

            # Read by the state tools' strict-mode write gate. The list is fresh
            # per call, so refusals never leak between calls.
            refused_writes: list[dict[str, str]] = []
            config["configurable"]["fidelity"] = self.fidelity
            config["configurable"]["operation_kind"] = self.operation_kinds.get(
                operation.operation_id
            )
            config["configurable"]["refused_writes"] = refused_writes

            # Generate response using agent with session context
            result = await self.agent.ainvoke(
                {"messages": [HumanMessage(content=request_prompt)]},
                config=config,
            )

            # Extract the output from the last message
            messages = result.get("messages", [])
            if not messages:
                raise ValueError("No response from agent")

            last_message = messages[-1]
            response_text = (
                last_message.content
                if hasattr(last_message, "content")
                else str(last_message)
            )

            logger.debug(
                f"Raw response: tool={tool_name}, response={response_text[:200]}..., "
                f"length={len(response_text)}"
            )

            # Try to parse as JSON
            try:
                parsed_response = json.loads(response_text)

                logger.debug(
                    f"Parsed response: tool={tool_name}, type={type(parsed_response).__name__}"
                )

                self._check_grounding(
                    operation.operation_id,
                    arguments,
                    parsed_response,
                    effective_thread_id,
                    refused_writes,
                )

                return parsed_response

            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON parse error: tool={tool_name}, response={response_text[:500]}, "
                    f"error={str(e)}"
                )

                # Return error response
                return {
                    "error": "Failed to generate valid JSON response",
                    "details": str(e),
                }

        except UngroundedResponseError:
            # A verdict, not an agent failure: let SimulationInstance map it.
            raise

        except Exception as e:
            logger.error(
                f"Agent error: tool={tool_name}, error={str(e)}",
                exc_info=True,
            )

            return {
                "error": "Internal error generating mock response",
                "details": str(e),
            }

    def _find_operation(self, tool_name: str) -> OpenAPIOperation | None:
        """Find operation by tool name.

        Args:
            tool_name: Tool name (operation ID)

        Returns:
            Operation if found, None otherwise
        """
        for operation in self.operations:
            if operation.operation_id == tool_name:
                return operation
        return None

    def _check_grounding(
        self,
        operation_id: str,
        arguments: dict[str, Any],
        response: Any,
        thread_id: str,
        refused_writes: list[dict[str, str]],
    ) -> None:
        """Strict mode: report or reject a response the store cannot account for."""
        if self.fidelity != "strict" or self.store_registry is None:
            return
        snapshot = self.store_registry.for_thread(thread_id).snapshot()
        ungrounded = check_grounding(response, arguments, snapshot, self._static_text)
        if not ungrounded:
            return
        shown = ungrounded[:_MAX_REPORTED_UNGROUNDED]
        logger.warning(
            f"Ungrounded strict-mode response: operation={operation_id}, "
            f"count={len(ungrounded)}, mode={self.strict_grounding}, "
            f"ungrounded={json.dumps([u.as_dict() for u in shown])}, "
            f"refused_writes={json.dumps(refused_writes)}"
        )
        if self._on_ungrounded is not None:
            self._on_ungrounded(ungrounded)
        if self.strict_grounding == "enforce":
            self._pending_rejections[thread_id] = shown
            raise UngroundedResponseError(
                operation_id=operation_id,
                ungrounded=[u.as_dict() for u in shown],
                refused_writes=list(refused_writes),
            )

    def _create_request_prompt(
        self,
        operation: OpenAPIOperation,
        arguments: dict[str, Any],
        rejected: list[Ungrounded] | None = None,
    ) -> str:
        """Create prompt for specific request.

        Args:
            operation: API operation
            arguments: Request arguments
            rejected: Values the previous call on this thread was rejected for
                (strict mode, enforce); named in the prompt so they are not reused

        Returns:
            Formatted request prompt
        """
        prompt_parts = [
            f"API Request: {operation.method.upper()} {operation.path}",
            f"Operation: {operation.operation_id}",
            "",
            "Request Parameters:",
            json.dumps(arguments, indent=2),
            "",
        ]
        if self.fidelity == "strict":
            prompt_parts += [
                "Return a response that:",
                "1. Matches the response schema exactly",
                "2. Uses only values from the request parameters, rows returned "
                "by the state tools, and the skill's Derivation Rules",
                "3. Maintains consistency with previous responses in this session",
                "4. Returns ONLY valid JSON (no explanations, no markdown)",
                "",
                _STRICT_REMINDER,
            ]
            if rejected:
                values = ", ".join(repr(u.value) for u in rejected)
                prompt_parts.append(
                    "Your previous response was rejected; these values are not "
                    f"in the store: {values}"
                )
        else:
            prompt_parts += [
                "Generate a realistic mock response that:",
                "1. Matches the response schema exactly",
                "2. Uses the provided request parameters appropriately",
                "3. Maintains consistency with previous responses in this session",
                "4. Returns ONLY valid JSON (no explanations, no markdown)",
            ]

        return "\n".join(prompt_parts)

    async def reset(self, thread_id: str | None = None) -> None:
        """Reset the agent's state and memory.

        Args:
            thread_id: Optional specific thread to reset. If None, resets all sessions.
        """
        if thread_id:
            # Reset specific session
            cleared = self.session_manager.clear_session(thread_id)
            if cleared:
                logger.info(f"Reset agent session: thread_id={thread_id}")
            else:
                logger.warning(f"Session not found: thread_id={thread_id}")

            # Reset store for this thread if registry exists
            if self.store_registry:
                self.store_registry.reset(thread_id)
            self._pending_rejections.pop(thread_id, None)
        else:
            # Reset all sessions
            count = self.session_manager.clear_all_sessions()
            logger.info(f"Reset all agent sessions: count={count}")

            # Drop all stores if registry exists
            if self.store_registry:
                self.store_registry.drop_all()
            self._pending_rejections.clear()

    async def shutdown(self) -> None:
        """Shutdown the agent and cleanup resources."""
        # Stop session cleanup task
        await self.session_manager.stop()

        # Drop all stores if registry exists
        if self.store_registry:
            self.store_registry.drop_all()

        # Remove the per-simulation skills staging dir, if one was created.
        if self._skill_staging_dir is not None:
            shutil.rmtree(self._skill_staging_dir, ignore_errors=True)
            self._skill_staging_dir = None

        logger.info("Agent shutdown complete")


# Made with Bob
