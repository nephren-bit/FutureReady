"""
services/profile_loader.py

Loads and caches the context profiles in `config/profiles/*.yaml`.

Why this lives in `services/` and not in `config/`: the project root already
has a `config.py` module, so `config/` must stay a plain data directory
without an `__init__.py` — adding one would shadow `from config import
settings` everywhere.

Discovery is by directory scan, not by a hard-coded list, so dropping a new
YAML file into `config/profiles/` registers a new profile with no code
change. A profile whose file is empty loads as an all-defaults
`ContextProfile`: it measures nothing and emits no events, rather than
crashing the process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from models.profiles import ContextProfile
from utils.logger import get_logger

logger = get_logger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent / "config" / "profiles"

# The profile used when a caller does not name one. In-class teacher recording
# is the only calibrated profile in this milestone.
DEFAULT_PROFILE = "presentation_class"


class ProfileNotFoundError(LookupError):
    """Raised when a named profile has no YAML file in `config/profiles/`."""


def available_profiles() -> list[str]:
    """Every profile name discoverable on disk, sorted."""
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(path.stem for path in PROFILES_DIR.glob("*.yaml"))


@lru_cache(maxsize=None)
def load_profile(name: str = DEFAULT_PROFILE) -> ContextProfile:
    """
    Load one context profile by name (the YAML file's stem).

    Results are cached for the process lifetime — profiles are configuration,
    read on every analysis run, and never change while the app is running.
    Call `reload_profiles()` after editing a file in a long-lived process.

    Args:
        name: Profile name, e.g. `presentation_class`.

    Returns:
        The parsed `ContextProfile`. `profile` is filled in from the file name
        when the YAML omits it.

    Raises:
        ProfileNotFoundError: If no such YAML file exists.
        ValueError: If the file exists but is not a valid profile.
    """
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.is_file():
        raise ProfileNotFoundError(
            f"No context profile named '{name}'. Available: {', '.join(available_profiles()) or 'none'}"
        )

    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Context profile '{name}' must be a YAML mapping, got {type(raw).__name__}.")

    raw.setdefault("profile", name)
    profile = ContextProfile.model_validate(raw)

    if not profile.events:
        logger.info(
            "Context profile '%s' (v%s) declares %d event code(s) but carries no calibrated "
            "thresholds; event detection will return an empty list for it.",
            profile.profile,
            profile.version,
            len(profile.event_catalog),
        )
    return profile


def reload_profiles() -> None:
    """Drop the cache so the next `load_profile` call re-reads from disk."""
    load_profile.cache_clear()
