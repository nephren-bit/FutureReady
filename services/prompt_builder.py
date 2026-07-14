"""
services/prompt_builder.py

Layer 5 — Prompt Builder service.

Thin service facade over `prompts/evaluation_prompt.py` and
`prompts/preliminary_prompt.py`. Routers never import from `prompts/`
directly and never construct prompt text themselves; they call
`PromptBuilder` (indirectly, via `EvaluationWorkflowManager`), which
receives a `UnifiedFeatureModel` plus the already-computed `ScoreBreakdown`
(and, for the final task, `DerivedFeatures`) and returns the finished
prompt string for the reasoning engine.

Kept as its own service (rather than inlining prompt construction) so
future task types can be added here as new methods without touching the
orchestrator, workflow manager, or routers.
"""

from __future__ import annotations

from enum import Enum

from models.features import DerivedFeatures, ScoreBreakdown, UnifiedFeatureModel
from models.responses import ReasoningPayload
from prompts.evaluation_prompt import build_evaluation_prompt
from prompts.preliminary_prompt import build_preliminary_prompt


class PromptTask(str, Enum):
    """Supported prompt-building tasks. Extend here as new reasoning tasks are added."""

    EVALUATE = "evaluate"
    """Final, synthesized report — the shared tail of both evaluation modes."""

    PRELIMINARY = "preliminary"
    """Single-material preliminary review (slide, resume, or video) — see `build_preliminary`."""


class PromptBuilder:
    """Builds reasoning-engine prompts from unified features, scores, and derived features (Layer 5)."""

    def build(
        self,
        task: PromptTask,
        features: UnifiedFeatureModel,
        scores: ScoreBreakdown,
        derived: DerivedFeatures,
        language: str = "vi",
        prior_evaluations: dict[str, ReasoningPayload] | None = None,
    ) -> str:
        """
        Build a prompt for the final synthesis task.

        Args:
            task: Must be `PromptTask.EVALUATE` (use `build_preliminary` for
                single-material preliminary reviews).
            features: The full unified feature set.
            scores: The deterministic score breakdown.
            derived: The cross-modal derived features.
            language: Output language code ("vi" or "en").
            prior_evaluations: Optional stage-name -> `ReasoningPayload`
                mapping of preliminary assessments already shown to the
                user, so the final report reconciles them (see
                `prompts/evaluation_prompt.py`).

        Returns:
            The finished prompt string.

        Raises:
            ValueError: If `task` is not a recognized `PromptTask`.
        """
        if task is PromptTask.EVALUATE:
            return build_evaluation_prompt(
                features, scores, derived, language=language, prior_evaluations=prior_evaluations
            )
        raise ValueError(f"Unsupported prompt task for build(): {task}")

    def build_preliminary(
        self,
        stage: str,
        features: UnifiedFeatureModel,
        scores: ScoreBreakdown,
        language: str = "vi",
    ) -> str:
        """
        Build a single-material preliminary review prompt.

        Args:
            stage: One of "slide", "resume", "video".
            features: A `UnifiedFeatureModel` narrowed to just this
                material's fields (see `services/workflow_manager.py`).
            scores: The `ScoreBreakdown` computed from just this material.
            language: Output language code ("vi" or "en").

        Returns:
            The finished prompt string.
        """
        return build_preliminary_prompt(stage, features, scores, language=language)


prompt_builder = PromptBuilder()
