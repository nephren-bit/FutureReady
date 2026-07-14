"""
services/session_state_machine.py

Pure state-machine logic for `AnalysisSession.state`. Contains no I/O, no
DB access, and no AI calls — it only answers "is this transition legal from
this state, in this mode?" `EvaluationWorkflowManager` is the only caller;
routers never touch this module directly.

Both evaluation modes share one `SessionState` enum (db/models.py) and one
transition table here, rather than two near-duplicate state machines, so
there is exactly one place that defines "what can happen next." The two
modes only diverge at the very first hop (SLIDE_* vs RESUME_*) and
converge again at `WAITING_FOR_VIDEO`.
"""

from __future__ import annotations

from db.models import EvaluationMode, SessionState


class InvalidTransitionError(Exception):
    """Raised when a transition is attempted that the state machine forbids."""

    def __init__(self, current: SessionState, event: str, mode: EvaluationMode) -> None:
        self.current = current
        self.event = event
        self.mode = mode
        super().__init__(
            f"Cannot apply event '{event}' while session is in state "
            f"'{current.value}' (mode={mode.value})."
        )


# Each entry: (mode-or-None-for-both, from_state) -> {event: to_state}
# `mode=None` means the transition is legal in either mode (the shared tail).
_TRANSITIONS: dict[tuple[EvaluationMode | None, SessionState], dict[str, SessionState]] = {
    # --- Presentation branch ---
    # Slide upload -> analysis -> its own preliminary score + reasoning
    # (SLIDE_SCORING/SLIDE_REASONING/SLIDE_EVALUATED) before ever waiting on
    # a video, so the user gets feedback on their slides immediately.
    (EvaluationMode.PRESENTATION, SessionState.EMPTY): {
        "upload_slide": SessionState.SLIDE_UPLOADED,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_UPLOADED): {
        "start_slide_analysis": SessionState.SLIDE_ANALYZING,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_ANALYZING): {
        "slide_analysis_done": SessionState.SLIDE_ANALYZED,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_ANALYZED): {
        "start_slide_scoring": SessionState.SLIDE_SCORING,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_SCORING): {
        "slide_scoring_done": SessionState.SLIDE_REASONING,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_REASONING): {
        "slide_reasoning_done": SessionState.SLIDE_EVALUATED,
    },
    (EvaluationMode.PRESENTATION, SessionState.SLIDE_EVALUATED): {
        "await_video": SessionState.WAITING_FOR_VIDEO,
    },
    # --- Interview branch (mirrors the Presentation branch, resume instead of slide) ---
    (EvaluationMode.INTERVIEW, SessionState.EMPTY): {
        "upload_resume": SessionState.RESUME_UPLOADED,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_UPLOADED): {
        "start_resume_analysis": SessionState.RESUME_ANALYZING,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_ANALYZING): {
        "resume_analysis_done": SessionState.RESUME_ANALYZED,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_ANALYZED): {
        "start_resume_scoring": SessionState.RESUME_SCORING,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_SCORING): {
        "resume_scoring_done": SessionState.RESUME_REASONING,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_REASONING): {
        "resume_reasoning_done": SessionState.RESUME_EVALUATED,
    },
    (EvaluationMode.INTERVIEW, SessionState.RESUME_EVALUATED): {
        "await_video": SessionState.WAITING_FOR_VIDEO,
    },
    # --- Shared tail (both modes) ---
    # Video upload -> analysis -> its own preliminary score + reasoning,
    # exactly mirroring the slide/resume branches, then a FINAL synthesis
    # pass (Feature Fusion -> Scoring -> Prompt -> Reasoning) that
    # reconciles the two preliminary evaluations into one report, and
    # finally a Recommendation Engine pass that picks learning resources
    # targeted at the session's weakest areas before the session completes.
    (None, SessionState.WAITING_FOR_VIDEO): {
        "upload_video": SessionState.VIDEO_UPLOADED,
    },
    (None, SessionState.VIDEO_UPLOADED): {
        "start_video_analysis": SessionState.VIDEO_ANALYZING,
    },
    (None, SessionState.VIDEO_ANALYZING): {
        "video_analysis_done": SessionState.VIDEO_ANALYZED,
    },
    (None, SessionState.VIDEO_ANALYZED): {
        "start_video_scoring": SessionState.VIDEO_SCORING,
    },
    (None, SessionState.VIDEO_SCORING): {
        "video_scoring_done": SessionState.VIDEO_REASONING,
    },
    (None, SessionState.VIDEO_REASONING): {
        "video_reasoning_done": SessionState.VIDEO_EVALUATED,
    },
    (None, SessionState.VIDEO_EVALUATED): {
        "start_fusion": SessionState.FEATURE_FUSION,
    },
    (None, SessionState.FEATURE_FUSION): {
        "fusion_done": SessionState.SCORING,
    },
    (None, SessionState.SCORING): {
        "scoring_done": SessionState.PROMPT_BUILDING,
    },
    (None, SessionState.PROMPT_BUILDING): {
        "prompt_built": SessionState.REASONING,
    },
    (None, SessionState.REASONING): {
        "reasoning_done": SessionState.REPORT_GENERATED,
    },
    (None, SessionState.REPORT_GENERATED): {
        "start_recommending": SessionState.RECOMMENDING,
    },
    (None, SessionState.RECOMMENDING): {
        "finalize": SessionState.COMPLETED,
    },
}

# Terminal states — no outgoing transitions except the implicit "fail"/"retry"
# handling, which `apply` and `resume_from_failure` special-case below.
_TERMINAL_STATES = {SessionState.COMPLETED, SessionState.FAILED}


def next_state(mode: EvaluationMode, current: SessionState, event: str) -> SessionState:
    """
    Look up the state reached by applying `event` to `current` in `mode`.

    Raises:
        InvalidTransitionError: if `event` is not legal from `current` in `mode`.
    """
    if current in _TERMINAL_STATES:
        raise InvalidTransitionError(current, event, mode)

    for key in ((mode, current), (None, current)):
        table = _TRANSITIONS.get(key)
        if table and event in table:
            return table[event]

    raise InvalidTransitionError(current, event, mode)


def can_apply(mode: EvaluationMode, current: SessionState, event: str) -> bool:
    """Non-raising check, useful for building UI affordances (e.g. "can I upload a video yet?")."""
    try:
        next_state(mode, current, event)
        return True
    except InvalidTransitionError:
        return False


def legal_events(mode: EvaluationMode, current: SessionState) -> list[str]:
    """All events that may legally be applied from `current` in `mode`. Empty for terminal states."""
    if current in _TERMINAL_STATES:
        return []
    events: list[str] = []
    for key in ((mode, current), (None, current)):
        table = _TRANSITIONS.get(key)
        if table:
            events.extend(table.keys())
    return events
