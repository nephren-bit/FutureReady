"""
routers/cv.py - REMOVED in the Clean Architecture refactor.

This module was part of FutureReady v1: a single `/analyze/cv` endpoint
that extracted CV features with PyMuPDF and then sent them straight to
Gemini, asking Gemini itself to assign a numeric score. That violated the
new design principle that Gemini must never calculate a score.

Superseded by:
* POST /extract/resume  (routers/extract.py)  - Layer 1 extraction only.
* POST /analyze/resume  (routers/analyze.py)  - Layer 2 deterministic analysis.
* POST /evaluate        (routers/evaluate.py) - full six-layer pipeline.

`app.py` no longer imports this module; it registers no routes. Safe to
delete manually.
"""
