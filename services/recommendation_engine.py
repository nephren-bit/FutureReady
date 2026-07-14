"""
services/recommendation_engine.py

MVP Recommendation Engine — LLM-driven (see docs/ERD_Design.md §4 for the
"rule_engine -> tfrs" upgrade path this schema was designed to absorb
without a rewrite; `RecommendationORM.generated_by` already accommodates
"llm" as a third strategy alongside those two).

Given a session's final `ScoreBreakdown` + `ReasoningPayload`, this selects
a small ranked set of `LearningResourceORM` rows (seeded via
`scripts/seed_learning_resources.py` from curated catalogs) via the
configured reasoning engine (`providers/registry.py`), with prompt
construction delegated to `services/prompt_builder.py` (Layer 5's sole
facade — this service never imports from `prompts/` directly). The
candidate list handed to the LLM is a closed set — it is instructed to
select only from what it is given, and `validate_picks` defensively drops
any pick that doesn't reference a real candidate id, so a malformed or
hallucinated response can never produce a broken foreign key.

`EvaluationWorkflowManager` is the only caller (see the `RECOMMENDING`
stage in `_run_final_synthesis`); routers never call this directly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from db.models import LearningResourceORM
from models.features import ScoreBreakdown
from models.responses import ReasoningPayload, RecommendationPayload
from services.prompt_builder import PromptBuilder, prompt_builder

# Keeps the prompt a manageable, predictable size. The seeded catalog today
# is ~50 rows (see data/learning_resources/), so this rarely trims anything;
# raise it if the catalog grows substantially and prompt-length becomes a
# real constraint, at which point pre-filtering by skill_tags overlap
# (rather than sending the full catalog) would be the next step.
_MAX_CANDIDATES = 80
_TOP_N = 5


class RecommendationEngine:
    """Selects and validates learning-resource recommendations for a completed session."""

    def __init__(self, builder: PromptBuilder | None = None) -> None:
        self._prompt_builder = builder or prompt_builder

    def candidate_resources(self, db: DBSession, limit: int = _MAX_CANDIDATES) -> list[LearningResourceORM]:
        """Fetch the pool of active catalog resources the reasoning engine may choose from."""
        stmt = select(LearningResourceORM).where(LearningResourceORM.is_active.is_(True)).limit(limit)
        return list(db.execute(stmt).scalars().all())

    def build_prompt(
        self,
        scores: ScoreBreakdown,
        reasoning: ReasoningPayload,
        candidates: list[LearningResourceORM],
        language: str = "vi",
    ) -> str:
        """Build the recommendation prompt from a session's final scores/reasoning and the candidate pool."""
        candidate_payload = [
            {
                "id": str(resource.id),
                "title": resource.title,
                "skill_tags": resource.skill_tags,
                "category": resource.category_label,
                "language": resource.language,
                "resource_type": resource.resource_type,
            }
            for resource in candidates
        ]
        return self._prompt_builder.build_recommendation(scores, reasoning, candidate_payload, language=language)

    def validate_picks(
        self, payload: RecommendationPayload, candidates: list[LearningResourceORM]
    ) -> list[tuple[LearningResourceORM, str, list[str]]]:
        """
        Filter the LLM's picks down to ones that reference a real candidate
        id, drop duplicates, and cap at `_TOP_N`.

        Returns:
            A list of `(resource, rationale, target_skill_tags)` tuples, in
            the order the reasoning engine ranked them.
        """
        by_id = {str(resource.id): resource for resource in candidates}
        seen: set[str] = set()
        results: list[tuple[LearningResourceORM, str, list[str]]] = []
        for pick in payload.picks:
            resource = by_id.get(pick.resource_id)
            if resource is None or pick.resource_id in seen:
                continue
            seen.add(pick.resource_id)
            results.append((resource, pick.rationale, pick.target_skill_tags))
            if len(results) >= _TOP_N:
                break
        return results


recommendation_engine = RecommendationEngine()
