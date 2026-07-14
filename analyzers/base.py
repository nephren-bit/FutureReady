"""
analyzers/base.py

Base interface for Layer 2 (AI Vision & Speech Intelligence, and
deterministic text/structure analysis). Every analyzer takes already
extracted Layer 1 data (never a raw file) and produces a single,
strongly-typed feature model. None of these analyzers call an LLM.

New analyzers are added by subclassing `BaseAnalyzer` and registering an
instance with the AI Orchestrator (`services/ai_orchestrator.py`); no
existing code needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

InputT = TypeVar("InputT")
FeatureT = TypeVar("FeatureT", bound=BaseModel)


class BaseAnalyzer(ABC, Generic[InputT, FeatureT]):
    """Abstract base class for all Layer 2 analyzers."""

    @abstractmethod
    def analyze(self, data: InputT) -> FeatureT:
        """
        Run analysis on already-extracted data and return a feature model.

        Args:
            data: Analyzer-specific input (e.g. a transcript string, a list
                of video frames, or a Layer 1 feature model). Never a raw
                file path and never a raw file's bytes.

        Returns:
            A Pydantic feature model describing the analysis result.
        """
        raise NotImplementedError
