"""
tests/conftest.py

Shared pytest fixtures for the FutureReady test suite.

Sets a default `UPLOAD_DIR` before any application module is imported.

(This file used to also stub a reasoning-engine provider and build sample
resume/slide/transcript/audio/emotion/facemesh feature fixtures for a larger
evaluation pipeline's tests -- removed along with that pipeline.)
"""

from __future__ import annotations

import os

os.environ.setdefault("UPLOAD_DIR", "uploads_test")
