"""
extractors/pdf_extractor.py

Extracts structured information from a CV/resume PDF using PyMuPDF (fitz).

The extractor pulls out raw text, page count, detected headings (based on
font-size heuristics), best-effort sections (skills / education /
experience / projects, detected via keyword matching in both English and
Vietnamese), and basic layout statistics. The result is a typed
`ResumeFeature` model — no AI reasoning happens here (Layer 1 only).
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from extractors.base import BaseExtractor
from models.features import ResumeFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# Section keywords (English + Vietnamese) used to detect CV sections.
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "skills": ["skill", "kỹ năng", "ky nang"],
    "education": ["education", "học vấn", "hoc van", "academic"],
    "experience": ["experience", "kinh nghiệm", "kinh nghiem", "work history"],
    "projects": ["project", "dự án", "du an"],
}

# A line is considered a heading if its font size is at least this many
# points larger than the document's median (body) font size.
_HEADING_SIZE_DELTA = 1.5


class PDFExtractor(BaseExtractor[ResumeFeature]):
    """Extracts structured data from a CV PDF file (Layer 1)."""

    def extract(self, file_path: Path) -> ResumeFeature:
        """
        Run full extraction on a PDF file.

        Args:
            file_path: Path to the PDF file on disk.

        Returns:
            A `ResumeFeature` model with text, headings, sections, and
            layout statistics.

        Raises:
            RuntimeError: If the PDF cannot be opened or parsed.
        """
        try:
            document = fitz.open(file_path)
        except Exception as exc:  # noqa: BLE001 - surfaced as a clear runtime error
            logger.exception("Failed to open PDF %s", file_path)
            raise RuntimeError(f"Could not open PDF file: {exc}") from exc

        try:
            spans = self._collect_spans(document)
            full_text = "\n".join(span["text"] for span in spans if span["text"].strip())
            headings = self._detect_headings(spans)
            sections = self._detect_sections(spans)
            layout_stats = self._compute_layout_statistics(document, spans)

            return ResumeFeature(
                text=full_text,
                page_count=document.page_count,
                headings=headings,
                skills=sections["skills"],
                education=sections["education"],
                experience=sections["experience"],
                projects=sections["projects"],
                word_count=layout_stats["word_count"],
                avg_words_per_page=layout_stats["avg_words_per_page"],
                font_size_min=layout_stats["font_size_min"],
                font_size_max=layout_stats["font_size_max"],
                font_size_avg=layout_stats["font_size_avg"],
                distinct_fonts=layout_stats["distinct_fonts"],
            )
        finally:
            document.close()

    def _collect_spans(self, document: "fitz.Document") -> list[dict[str, Any]]:
        """Flatten every text span in the document into a simple list of dicts."""
        spans: list[dict[str, Any]] = []
        for page_index, page in enumerate(document):
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        spans.append(
                            {
                                "text": text,
                                "size": round(span.get("size", 0.0), 2),
                                "font": span.get("font", ""),
                                "page": page_index + 1,
                            }
                        )
        return spans

    def _detect_headings(self, spans: list[dict[str, Any]]) -> list[str]:
        """Detect probable headings using a font-size-above-median heuristic."""
        if not spans:
            return []

        sizes = [span["size"] for span in spans]
        median_size = statistics.median(sizes)

        headings: list[str] = []
        seen: set[str] = set()
        for span in spans:
            is_large = span["size"] >= median_size + _HEADING_SIZE_DELTA
            is_short = len(span["text"]) <= 60
            if is_large and is_short and span["text"] not in seen:
                headings.append(span["text"])
                seen.add(span["text"])
        return headings

    def _detect_sections(self, spans: list[dict[str, Any]]) -> dict[str, list[str]]:
        """
        Best-effort section extraction based on keyword-matched headings.

        For each known section (skills/education/experience/projects), find
        the first span whose text matches one of the section's keywords and
        collect subsequent spans until the next heading-like span is found.
        """
        sizes = [span["size"] for span in spans] or [0.0]
        median_size = statistics.median(sizes)

        sections: dict[str, list[str]] = {key: [] for key in _SECTION_KEYWORDS}

        current_section: str | None = None
        for span in spans:
            text_lower = span["text"].lower()
            is_heading = span["size"] >= median_size + _HEADING_SIZE_DELTA and len(span["text"]) <= 60

            matched_section = None
            if is_heading:
                for section_name, keywords in _SECTION_KEYWORDS.items():
                    if any(keyword in text_lower for keyword in keywords):
                        matched_section = section_name
                        break

            if matched_section:
                current_section = matched_section
                continue

            if is_heading:
                # Reached a different heading (not one of our target sections).
                current_section = None
                continue

            if current_section:
                sections[current_section].append(span["text"])

        # Clean up: strip empty/very short noise lines.
        for key, lines in sections.items():
            sections[key] = [line for line in lines if len(line.strip()) > 1]

        return sections

    def _compute_layout_statistics(
        self, document: "fitz.Document", spans: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Compute basic layout statistics: word count, density, font sizes."""
        all_text = " ".join(span["text"] for span in spans)
        word_count = len(re.findall(r"\S+", all_text))
        page_count = max(document.page_count, 1)
        sizes = [span["size"] for span in spans] or [0.0]

        return {
            "word_count": word_count,
            "avg_words_per_page": round(word_count / page_count, 2),
            "font_size_min": round(min(sizes), 2),
            "font_size_max": round(max(sizes), 2),
            "font_size_avg": round(sum(sizes) / len(sizes), 2),
            "distinct_fonts": sorted({span["font"] for span in spans}),
        }
