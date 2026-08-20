"""
models/resource_models.py

Request/response schemas for the learning-resource catalog — row 12 of the
Project 1 report's permission matrix, "Quản lý danh mục tài nguyên học tập
(thêm, sửa, ẩn tài nguyên, gắn nhãn kỹ năng)".

Note the verbs the report chose: add, edit, **hide**, tag. Not delete. That
is reflected here — there is no delete schema, because `RecommendationORM`
rows point at resources, and removing a resource would rewrite the history of
every session that was once recommended it. Hiding via `is_active` keeps that
history intact and truthful.

Skill tags are a controlled vocabulary rather than free text. The
Recommendation Engine matches these tags against a session's weakest
sub-scores (`services/recommendation_engine.py`), so a tag nobody matches on
is a resource that can never be recommended — it would look catalogued but be
invisible in practice, which is worse than being rejected at entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillTag(str, Enum):
    """
    The skill slugs the Recommendation Engine can match a weak area against.

    Taken from what the seeded catalog actually uses. Adding a member here is
    what it takes to introduce a new tag — deliberately a code change, since
    a tag the engine does not know about matches nothing.
    """

    SPEAKING = "speaking"
    CONFIDENCE = "confidence"
    PRESENTATION = "presentation"
    CRITICAL_THINKING = "critical_thinking"
    INTERVIEW = "interview"
    GENERAL = "general"


class ResourceType(str, Enum):
    """What kind of thing the resource is."""

    VIDEO = "video"
    ARTICLE = "article"
    COURSE = "course"
    EXERCISE = "exercise"


def _clean(value: str | None) -> str | None:
    """Trim, and treat an all-whitespace field as absent rather than as an empty string."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ResourceCreateRequest(BaseModel):
    """A new catalog entry."""

    title: str = Field(..., min_length=1, max_length=512)
    url: str = Field(..., min_length=1, max_length=1024)
    resource_type: ResourceType = ResourceType.VIDEO
    platform: str | None = Field(None, max_length=64)
    language: str | None = Field(None, pattern="^(vi|en)$")
    speaker: str | None = Field(None, max_length=256)
    source: str | None = Field(None, max_length=128)
    description: str | None = None
    skill_tags: list[SkillTag] = Field(
        default_factory=list,
        description="Which weak areas this resource addresses. Empty means it can never be recommended.",
    )
    category_label: str | None = Field(None, max_length=128)
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        """
        Require an http(s) URL.

        The catalog is rendered as clickable links in the learner's report; a
        bare domain or a stray file path would render as a dead link that
        nobody notices until a learner clicks it.
        """
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("Đường dẫn phải bắt đầu bằng http:// hoặc https://")
        return cleaned

    @field_validator("title", "platform", "speaker", "source", "category_label", "description")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


class ResourceUpdateRequest(BaseModel):
    """
    Changes to an existing entry. Every field optional; only what is sent is
    applied, so a form that edits one field cannot blank out the rest.
    """

    title: str | None = Field(None, min_length=1, max_length=512)
    url: str | None = Field(None, min_length=1, max_length=1024)
    resource_type: ResourceType | None = None
    platform: str | None = Field(None, max_length=64)
    language: str | None = Field(None, pattern="^(vi|en)$")
    speaker: str | None = Field(None, max_length=256)
    source: str | None = Field(None, max_length=128)
    description: str | None = None
    skill_tags: list[SkillTag] | None = None
    category_label: str | None = Field(None, max_length=128)
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("Đường dẫn phải bắt đầu bằng http:// hoặc https://")
        return cleaned

    @field_validator("title", "platform", "speaker", "source", "category_label", "description")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


class ResourcePublic(BaseModel):
    """One catalog entry as the admin screen sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    url: str
    resource_type: str
    platform: str | None = None
    language: str | None = None
    speaker: str | None = None
    source: str | None = None
    description: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    category_label: str | None = None
    is_active: bool
    created_at: datetime | None = None
    recommendation_count: int = Field(
        0,
        description=(
            "How many times this resource has been recommended. The reason hiding "
            "exists instead of deleting: a non-zero count means session history "
            "points here."
        ),
    )


class ResourceListResponse(BaseModel):
    """One page of the catalog."""

    total: int = Field(..., description="Total matching resources, before paging.")
    items: list[ResourcePublic]


class ResourceStatsResponse(BaseModel):
    """Headline counts for the catalog screen."""

    total: int
    active: int
    hidden: int
    by_type: dict[str, int]
    by_skill_tag: dict[str, int]
    untagged: int = Field(
        0, description="Resources with no skill tag — catalogued but unreachable by the engine."
    )
