"""
FastAPI endpoint tests. Gemini is always monkeypatched — no test in this
module makes a real network call or requires a real API key. Heavy/optional
dependencies required just to import the app (google-genai, PyMuPDF,
python-pptx, librosa) are skipped-if-missing at collection time so the rest
of the suite still runs on a partial install.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("google.genai")
pytest.importorskip("librosa")
fitz = pytest.importorskip("fitz")

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from models.responses import ReasoningPayload  # noqa: E402
from services import ai_orchestrator as orchestrator_module  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def mock_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real Gemini call with a deterministic stub for every test."""

    async def fake_generate_structured(prompt: str, response_model):  # noqa: ANN001
        assert response_model is ReasoningPayload
        return ReasoningPayload(
            strengths=["Clear structure"],
            weaknesses=["Needs more quantified achievements"],
            improvement_plan=["Add measurable results to each bullet point"],
            presentation_feedback="Solid overall presentation readiness.",
            interview_feedback="Good pacing; work on filler words.",
            interview_questions=["Tell me about a challenging project."],
            suggestions=["Practice a stronger opening."],
        )

    monkeypatch.setattr(
        orchestrator_module.ai_orchestrator._gemini,
        "generate_structured",
        fake_generate_structured,
    )


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_extract_resume_returns_feature(client: TestClient, tmp_path: Path) -> None:
    pdf_path = tmp_path / "resume.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Jane Smith", fontsize=18)
    page.insert_text((72, 110), "Skills", fontsize=13)
    page.insert_text((72, 130), "Python, Leadership", fontsize=10)
    document.save(str(pdf_path))
    document.close()

    with pdf_path.open("rb") as fh:
        response = client.post(
            "/extract/resume", files={"file": ("resume.pdf", fh, "application/pdf")}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["page_count"] == 1
    assert "Jane Smith" in body["text"]


def test_extract_resume_rejects_wrong_extension(client: TestClient) -> None:
    response = client.post(
        "/extract/resume", files={"file": ("resume.txt", b"not a pdf", "text/plain")}
    )
    assert response.status_code == 400


def test_evaluate_from_features_returns_report(
    client: TestClient, sample_unified_features
) -> None:
    payload = {
        "features": sample_unified_features.model_dump(mode="json"),
        "language": "en",
    }
    response = client.post("/evaluate/from-features", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["overall_score"] <= 100
    assert body["strengths"] == ["Clear structure"]
    assert "derived_features" in body
    assert "features" in body


def test_evaluate_requires_at_least_one_file(client: TestClient) -> None:
    response = client.post("/evaluate", data={"language": "en"})
    assert response.status_code == 400
