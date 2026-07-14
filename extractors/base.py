"""
extractors/base.py

Base interface for Layer 1 (Feature Extraction). Every extractor turns one
raw input file into a single, strongly-typed, JSON-serializable feature
model — and does nothing else. No AI reasoning, no scoring, no LLM calls.

New extractors (e.g. for a new file format) are added by subclassing
`BaseExtractor` and registering an instance with the AI Orchestrator
(`services/ai_orchestrator.py`); no existing code needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

FeatureT = TypeVar("FeatureT", bound=BaseModel)


class BaseExtractor(ABC, Generic[FeatureT]):
    """Abstract base class for all Layer 1 feature extractors."""

    @abstractmethod
    def extract(self, file_path: Path) -> FeatureT:
        """
        Run extraction on a file and return a structured feature model.

        Args:
            file_path: Path to the input file on disk.

        Returns:
            A Pydantic feature model describing the file's content.

        Raises:
            RuntimeError: If the file cannot be opened, parsed, or is
                otherwise invalid for this extractor.
        """
        raise NotImplementedError
