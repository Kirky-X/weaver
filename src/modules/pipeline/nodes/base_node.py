"""Base class for pipeline nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.llm.client import LLMClient
from core.llm.token_budget import TokenBudgetManager
from core.prompt.loader import PromptLoader
from core.observability.logging import get_logger
from modules.pipeline.state import PipelineState

log = get_logger("pipeline.base_node")


class BasePipelineNode(ABC):
    """Abstract base class for pipeline nodes.

    Provides common functionality:
    - Terminal state handling
    - Prompt version tracking
    - Logging
    - Error handling
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        name: str,
    ) -> None:
        """Initialize the node.

        Args:
            llm: LLM client for AI calls.
            budget: Token budget manager.
            prompt_loader: Prompt template loader.
            name: Node name for logging.
        """
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._name = name

    async def execute(self, state: PipelineState) -> PipelineState:
        """Execute the node.

        Args:
            state: Current pipeline state.

        Returns:
            Updated pipeline state.
        """
        if self._should_skip(state):
            return state

        try:
            result = await self._process(state)
            self._update_state(state, result)
        except Exception as e:
            await self._handle_error(state, e)

        self._record_prompt_version(state)
        self._log_success(state)
        return state

    def _should_skip(self, state: PipelineState) -> bool:
        """Check if this node should be skipped.

        Args:
            state: Current pipeline state.

        Returns:
            True if node should be skipped.
        """
        return state.get("terminal", False)

    def _record_prompt_version(self, state: PipelineState) -> None:
        """Record prompt version in state.

        Args:
            state: Pipeline state to update.
        """
        try:
            version = self._prompt_loader.get_version(self._name)
            state.setdefault("prompt_versions", {})[self._name] = version
        except Exception:
            pass

    @abstractmethod
    async def _process(self, state: PipelineState) -> Any:
        """Process the state and return result.

        Args:
            state: Current pipeline state.

        Returns:
            Processing result.
        """
        ...

    @abstractmethod
    def _update_state(self, state: PipelineState, result: Any) -> None:
        """Update state with processing result.

        Args:
            state: Pipeline state to update.
            result: Processing result.
        """
        ...

    async def _handle_error(self, state: PipelineState, error: Exception) -> None:
        """Handle processing error.

        Args:
            state: Current pipeline state.
            error: Exception that occurred.
        """
        raw = state.get("raw")
        url = raw.url if raw else "unknown"
        log.warning(
            f"{self._name}_failed",
            url=url,
            error=str(error),
        )

    def _log_success(self, state: PipelineState) -> None:
        """Log successful processing.

        Args:
            state: Updated pipeline state.
        """
        raw = state.get("raw")
        url = raw.url if raw else "unknown"
        log.info(f"{self._name}_processed", url=url)
