"""Simplified Deep Agent implementation for Simulation Harness.

This module provides the main agent that generates mock responses using
LangChain and LangGraph directly (without the deepagents library).
"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from simulation_harness.openapi.parser import OpenAPIOperation, OpenAPISpec
from simulation_harness.utils.logging import get_logger
from simulation_harness.agent.prompts import render_system_prompt
from simulation_harness.agent.session_manager import SessionManager

logger = get_logger(__name__)


class DeepAgent:
    """Simplified agent for generating mock API responses using LangChain/LangGraph."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        base_url: str | None,
        spec: OpenAPISpec,
        operations: list[OpenAPIOperation],
        session_timeout_seconds: int = 3600,
    ):
        """Initialize Deep Agent.

        Args:
            api_key: OpenAI API key
            model: Model name (e.g., "gpt-4")
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            base_url: Optional custom base URL for OpenAI API
            spec: OpenAPI specification
            operations: List of API operations
            session_timeout_seconds: Session timeout in seconds
        """
        self.spec = spec
        self.operations = operations
        self.session_timeout_seconds = session_timeout_seconds

        # Initialize LLM
        llm_kwargs = {
            "model": model,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "api_key": SecretStr(api_key),
        }
        if base_url:
            llm_kwargs["base_url"] = base_url

        self.llm = ChatOpenAI(**llm_kwargs)

        # Render system prompt
        self.system_prompt = render_system_prompt(spec, operations)

        logger.debug(
            f"Rendered system prompt: length={len(self.system_prompt)}, "
            f"preview={self.system_prompt[:200]}..."
        )

        # Initialize checkpointer for session management
        self.checkpointer = MemorySaver()

        # Initialize session cleanup manager
        self.session_manager = SessionManager(
            checkpointer=self.checkpointer,
            timeout_seconds=session_timeout_seconds,
            max_sessions=100,  # Default max sessions
        )

        # Create LangGraph agent
        self.agent = self._create_agent()

        # Note: Session cleanup task is NOT started automatically
        # Call start_session_cleanup() explicitly when ready

        logger.info(
            f"Deep Agent initialized: model={model}, "
            f"operation_count={len(operations)}, "
            f"session_timeout={session_timeout_seconds}s"
        )

    def start_session_cleanup(self) -> None:
        """Start the session cleanup background task.
        
        This should be called after the agent is initialized and
        an event loop is running.
        """
        self.session_manager.start()

    def _create_agent(self) -> CompiledStateGraph:
        """Create LangGraph agent with state management.

        Returns:
            Compiled state graph
        """
        # Define the agent function
        def agent_node(state: MessagesState) -> MessagesState:
            """Process messages and generate response."""
            messages = state["messages"]
            
            # Add system message if not present
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=self.system_prompt)] + list(messages)
            
            # Invoke LLM
            response = self.llm.invoke(messages)
            
            return {"messages": messages + [response]}

        # Build graph
        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", agent_node)
        workflow.add_edge(START, "agent")
        workflow.add_edge("agent", END)

        # Compile with checkpointer
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
            # Create prompt for this specific request
            request_prompt = self._create_request_prompt(operation, arguments)

            logger.debug(
                f"Request prompt: tool={tool_name}, prompt={request_prompt}, "
                f"thread_id={thread_id or 'default'}"
            )

            # Determine effective thread_id
            effective_thread_id = thread_id or "default"

            # Record session activity for cleanup tracking
            self.session_manager.record_activity(effective_thread_id)

            # Build config with thread_id for session management
            config: RunnableConfig = {
                "configurable": {"thread_id": effective_thread_id},
            }

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
                last_message.content if hasattr(last_message, "content") else str(last_message)
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

    def _create_request_prompt(
        self,
        operation: OpenAPIOperation,
        arguments: dict[str, Any],
    ) -> str:
        """Create prompt for specific request.

        Args:
            operation: API operation
            arguments: Request arguments

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
        else:
            # Reset all sessions
            count = self.session_manager.clear_all_sessions()
            logger.info(f"Reset all agent sessions: count={count}")

    async def shutdown(self) -> None:
        """Shutdown the agent and cleanup resources."""
        # Stop session cleanup task
        await self.session_manager.stop()
        logger.info("Agent shutdown complete")

# Made with Bob
