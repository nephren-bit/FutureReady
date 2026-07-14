# FutureReady (EmpathAI)

FutureReady is an AI-powered communication-coaching platform. It runs two
evaluation workflows — **Presentation** (slides + video) and **Interview**
(resume + video) — combining traditional AI, computer vision, and an LLM
into a single deterministic, production-quality pipeline, orchestrated
through persistent, resumable **sessions**.

This is the session-centric platform (v3): every evaluation is a persisted
`AnalysisSession` moving through an explicit state machine, with Layer 1/2
AI analysis running in the background so uploads return immediately and a
client polls for progress. As soon as each material (slide deck, resume,
or video) finishes analysis, it gets its own **preliminary score +
reasoning checkpoint** — the candidate sees feedback on their slides
immediately, without waiting for the video — and once every material has
been evaluated, a **final synthesis pass** reconciles the preliminary
checkpoints into one coherent report rather than reasoning over the raw
data from scratch. The original stateless Clean Architecture pipeline
(v2) — extractors, analyzers, feature fusion, scoring, prompt building,
Gemini reasoning — is unchanged and fully reused underneath; v3 adds
persistence, orchestration, per-material checkpoints, and a swappable
reasoning-provider layer on top of it.

## Design Principle

Gemini (or whichever reasoning engine is configured) is a reasoning engine
only. It never touches a raw file and never computes a score:

```
Traditional AI (Librosa / OpenCV / PyMuPDF / python-pptx)
        │
        ▼
Feature Extraction (Layer 1)
        │
        ▼
AI Vision & Speech Intelligence + deterministic analysis (Layer 2)
   (Whisper, HSEmotion, MediaPipe Face Mesh, transcript/CV/slide analyzers)
        │
        ▼
Feature Fusion (Layer 3)                    ─┐
        │                                     │  orchestrated by
        ▼                                     │  EvaluationWorkflowManager,
Deterministic Scoring Engine (Layer 4)        │  persisted as an
        │                                     │  AnalysisSession
        ▼                                     │
Prompt Builder (Layer 5)                      │
        │                                     │
        ▼                                     │
Reasoning Engine (Layer 6) — strengths,       │
weaknesses, coaching, no scores. Resolved     │
via providers/registry.py (Gemini today)     ─┘
```

Everything through Layer 5 is fully deterministic and reproducible: given
the same input files, the same scores come out every time, whether or not
the reasoning provider is even reachable. The reasoning engine's only job
is turning already-computed numbers (and, for the final report, real
per-slide/per-resume content — see "Preliminary evaluation & final
synthesis" below) into human, actionable feedback — and it is never
imported directly by the workflow manager, only resolved through
`providers/registry.py`, so swapping Gemini for Claude/GPT/a local model
later touches no business logic.

### What this project deliberately does NOT implement

Live recording/webcam, WebSocket streaming, a persona engine, a
recommendation engine, authentication, model fine-tuning, RAG, and
multi-agent orchestration are all out of scope by design. The codebase is
structured so every one of these can be added later without touching
`EvaluationWorkflowManager`, `FeatureFusionEngine`, `ScoringEngine`, the API
contracts, or the DB models — see "Extending the platform" below.

## Architecture

```
┌──────────────┐   POST /sessions/{id}/{slide,resume,video}
│   Routers    │──────────────────────────────┐
│ sessions.py  │                               ▼
└──────────────┘                    ┌───────────────────────────┐
       ▲                            │  EvaluationWorkflowManager │  ◀── sole orchestrator;
       │ GET /sessions/{id}         │  - validates state machine │      routers never call
       │ GET .../report             │  - runs Layer 1/2 analysis │      AI services directly
       │ GET .../preliminary/{stage}│  - runs per-material        │
       │                            │    preliminary score+reason │
┌──────┴───────┐                    │  - runs final Fusion/Scoring│
│AnalysisSession│◀──────persisted──│    /Prompt/Reasoning tail    │
│ + Preliminary │                  └───────────────┬─────────────┘
│  Evaluation    │                                  │
│  (PostgreSQL)  │                                  ▼
└──────────────┘                ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐  ┌───────────────────┐
                                 │  Extractors  │─▶│  Analyzers   │─▶│  Feature Fusion     │─▶│  Scoring Engine    │
                                 │  (Layer 1)   │  │  (Layer 2)   │  │  (Layer 3)          │  │  (Layer 4)         │
                                 └──────────────┘  └──────────────┘  └────────────────────┘  └─────────┬─────────┘
                                                                                                          ▼
                                                                                               ┌───────────────────┐
                                                                                               │  Prompt Builder    │
                                                                                               │  (Layer 5)         │
                                                                                               └─────────┬─────────┘
                                                                                                          ▼
                                                                                          ┌────────────────────────────┐
                                                                                          │ providers/registry.py       │
                                                                                          │  -> BaseReasoningEngine      │
                                                                                          │     (GeminiReasoningEngine)  │
                                                                                          └────────────────────────────┘
```

Every extractor implements `BaseExtractor.extract()`; every analyzer
implements `BaseAnalyzer.analyze()` — both are swappable strategy classes
injected into `AIOrchestrator`, unchanged since v2. `FeatureFusionEngine`
and `ScoringEngine` remain concrete, non-swappable services: they are the
only source of derived features and numeric scores respectively, and are
never treated as plugins. `BaseReasoningEngine` is the one deliberately
swappable AI boundary, resolved via `providers/registry.py` and
`config/providers.yaml`.

## Preliminary evaluation & final synthesis

Instead of "upload everything, then wait for one big evaluation at the
end," each material gets scored and reasoned about **as soon as it
finishes analysis**:

```
slide/resume analysis done
        │
        ▼
Scoring (this material only) ──▶ *_SCORING
        │
        ▼
Prompt Builder (preliminary) + Reasoning Engine ──▶ *_REASONING
        │
        ▼
Persisted as PreliminaryEvaluationORM, visible via
GET /sessions/{id}/preliminary/{stage} ──▶ *_EVALUATED
        │
        ▼
await_video (Presentation/Interview) or, once the video's own
preliminary pass is done, straight into the final synthesis tail
```

The video goes through the identical per-material pipeline once uploaded
(`VIDEO_SCORING` → `VIDEO_REASONING` → `VIDEO_EVALUATED`). Once every
material required by the session's mode has its own preliminary
evaluation, the shared tail runs: Feature Fusion → Scoring → Prompt
Building → Reasoning, producing the **final** report. Two decisions make
this a synthesis rather than a fresh evaluation:

* The final `overall_score` is an equal-weighted combination of the
  preliminary `overall_score`s already shown to the user (see
  `EvaluationWorkflowManager._combine_preliminary_overall_score`,
  `utils/scoring_math.weighted_average` + `clamp_score`) — not a fresh
  `ScoringEngine.score()` recomputation from the merged feature set.
* The final prompt (`prompts/evaluation_prompt.build_evaluation_prompt`)
  is given both preliminary `ReasoningPayload`s as context and explicitly
  instructed to reconcile them with the full cross-modal picture, rather
  than reason over the raw data as if seeing it for the first time.

Each material's prompt section (`prompts/slide_prompt.py`,
`prompts/cv_prompt.py`) also sends Gemini the actual **content** —
per-slide titles/bullets/speaker notes, full resume text — not just
deterministic structure metrics, so both the preliminary and final
feedback can speak to what the candidate actually wrote, not only how it's
formatted.

Retrying a `FAILED` session resumes from exactly the sub-stage that
failed: a crash during a material's preliminary reasoning pass re-runs
only that pass (cheap — Layer 1/2 analysis is never repeated), and a
crash during final synthesis resumes from whichever of
Fusion/Scoring/Prompt/Reasoning didn't finish.

## Folder structure

```
FutureReady/
├── app.py                       # FastAPI entry point (sessions router + deprecated legacy routers)
├── config.py                    # Centralized configuration (env vars)
├── requirements.txt
├── pytest.ini
├── alembic.ini
├── .env.example
├── uploads/                     # Uploaded files (kept for session recovery/retry, not auto-deleted)
├── db/                          # Persistence layer (PostgreSQL via SQLAlchemy 2.0)
│   ├── base.py                  #   Shared DeclarativeBase
│   ├── models.py                #   AnalysisSession, PreliminaryEvaluationORM, every feature/score/report table
│   └── session.py               #   Engine, SessionLocal, get_db() FastAPI dependency
├── migrations/                  # Alembic migrations (hand-written, not autogenerated)
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py           # AnalysisSession + Layer 1-6 feature/score/report tables
│       └── 0002_preliminary_evaluations.py  # *_SCORING/*_REASONING/*_EVALUATED states + preliminary_evaluations table
├── providers/
│   └── registry.py              #   ProviderRegistry -> BaseReasoningEngine, driven by config/providers.yaml
├── config/
│   └── providers.yaml           #   reasoning_engine: gemini
├── extractors/                  # Layer 1 — raw, deterministic feature extraction
│   ├── base.py
│   ├── pdf_extractor.py         #   Resume PDF -> ResumeFeature (PyMuPDF)
│   ├── ppt_extractor.py         #   Slides PPTX -> SlideFeature (python-pptx)
│   ├── audio_extractor.py       #   Audio -> AudioFeature (Librosa)
│   └── video_extractor.py       #   Video -> VideoFeature + sampled frames (OpenCV)
├── analyzers/                   # Layer 2 — AI vision/speech + deterministic analysis
│   ├── base.py
│   ├── cv_analyzer.py           #   ResumeFeature -> ResumeAnalysisFeature
│   ├── slide_analyzer.py        #   SlideFeature -> SlideAnalysisFeature
│   ├── transcript_analyzer.py   #   transcript text -> TranscriptFeature
│   ├── speech_analyzer.py       #   audio -> SpeechIntelligenceFeature (Whisper)
│   ├── emotion_analyzer.py      #   frames -> EmotionFeature (HSEmotion)
│   └── facemesh_analyzer.py     #   frames -> FaceMeshFeature (MediaPipe)
├── services/
│   ├── ai_orchestrator.py       #   Facade driving Layers 1-6 (used by legacy routers directly, by WorkflowManager for Layer 1/2 calls)
│   ├── feature_fusion.py        #   Layer 3 — DerivedFeatures (concrete, not a plugin)
│   ├── scoring_engine.py        #   Layer 4 — ScoreBreakdown (concrete, not a plugin; documented formulas)
│   ├── prompt_builder.py        #   Layer 5 — prompt composition service (EVALUATE + PRELIMINARY tasks)
│   ├── gemini_service.py        #   google-genai SDK wrapper (used by GeminiReasoningEngine)
│   ├── reasoning/
│   │   ├── base.py              #   BaseReasoningEngine contract
│   │   └── gemini_engine.py     #   GeminiReasoningEngine (current implementation)
│   ├── session_state_machine.py #   Pure transition table for AnalysisSession.state
│   ├── session_mappers.py       #   ORM row <-> Pydantic feature model conversions
│   └── workflow_manager.py      #   EvaluationWorkflowManager — the sole orchestrator
├── routers/
│   ├── sessions.py              #   POST /sessions, /sessions/{id}/{slide,resume,video,retry}, GET .../{id}, .../report, .../preliminary/{stage}, DELETE
│   ├── extract.py               #   DEPRECATED — POST /extract/{resume,slide,audio,video}
│   ├── analyze.py               #   DEPRECATED — POST /analyze/{resume,slide,transcript,speech,video}
│   └── evaluate.py              #   DEPRECATED — POST /evaluate, POST /evaluate/from-features
├── prompts/                     # Layer 5 — prompt text, never hard-coded in routers
│   ├── base_prompt.py           #   Shared persona/guardrail framing + JSON-only instruction helper
│   ├── cv_prompt.py             #   Resume section (full text + deterministic analysis)
│   ├── slide_prompt.py          #   Slide section (per-slide title/bullets/notes + deterministic analysis)
│   ├── transcript_prompt.py     #   Transcript section
│   ├── speech_prompt.py         #   Vocal delivery section (acoustic + Whisper + emotion + face mesh)
│   ├── evaluation_prompt.py     #   FINAL synthesis prompt — accepts prior preliminary ReasoningPayloads
│   └── preliminary_prompt.py    #   Single-material preliminary review prompt (reuses the section builders above)
├── models/
│   ├── features.py              #   UnifiedFeatureModel + every feature/score model
│   ├── session_models.py        #   SessionCreateRequest / SessionResponse / SessionReportResponse / PreliminaryEvaluationResponse
│   ├── requests.py              #   Legacy request bodies
│   └── responses.py             #   EvaluationReport, ReasoningPayload, ErrorResponse
├── utils/
│   ├── file_utils.py            #   Upload validation, save, cleanup
│   ├── scoring_math.py          #   band_score / weighted_average / clamp_score
│   └── logger.py                #   Centralized logging
└── tests/                       #   Unit + integration tests (see "Testing" below)
```

## Installation

### 1. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `openai-whisper`, `torch`, `mediapipe`, and `hsemotion-onnx` are
> large downloads and may take a while to install. `librosa` additionally
> needs `ffmpeg` or `libsndfile` on some systems to decode audio tracks.
> Whisper and HSEmotion also download their model weights on first use —
> the first video upload will be slower than subsequent ones. On Windows,
> if `pip install` fails on `openai-whisper` with
> `ModuleNotFoundError: No module named 'pkg_resources'`, run
> `pip install "setuptools<81" wheel` first.

### 3. Start PostgreSQL

Sessions are persisted to PostgreSQL. Easiest local option, Docker:

```bash
docker run --name futureready-db \
  -e POSTGRES_USER=futureready \
  -e POSTGRES_PASSWORD=futureready \
  -e POSTGRES_DB=futureready \
  -p 5432:5432 -d postgres:16
```

(Already have a container running under a different name/credentials, or
something else already listening on 5432? Just point `DATABASE_URL` at the
right host/port in step 4 — nothing else needs to match.)

### 4. Configure environment variables

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | API key from https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model used for Layer 6 reasoning |
| `WHISPER_MODEL_SIZE` | `base` | Whisper model size: tiny/base/small/medium/large |
| `HSEMOTION_MODEL_NAME` | `enet_b0_8_best_afew` | HSEmotion (ONNX) model name |
| `VIDEO_SAMPLE_FRAME_COUNT` | `60` | Frames sampled per video for vision analyzers |
| `UPLOAD_DIR` | `uploads` | Upload storage directory (kept for session recovery) |
| `MAX_FILE_SIZE_MB` | `25` | Max size for PDF/PPTX uploads |
| `MAX_VIDEO_SIZE_MB` | `300` | Max size for video uploads |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_URL` | `postgresql+psycopg://futureready:futureready@localhost:5432/futureready` | SQLAlchemy connection string for session persistence |
| `SCORING_ENGINE_VERSION` | `1.0.0` | Stamped onto every `ScoreResult`/`PreliminaryEvaluation` row for reproducibility |
| `FEATURE_FUSION_VERSION` | `1.0.0` | Stamped onto every `UnifiedFeature` row for reproducibility |

Reasoning-provider selection lives in `config/providers.yaml` (not `.env`),
since it's an architectural choice rather than a per-environment secret:

```yaml
reasoning_engine: gemini
```

### 5. Apply database migrations

```bash
alembic upgrade head
```

This applies both `0001_initial_schema.py` (the core session/feature/score
tables) and `0002_preliminary_evaluations.py` (the preliminary-evaluation
sub-states and `preliminary_evaluations` table). If you're upgrading an
existing database that was only ever migrated to `0001`, running
`alembic upgrade head` again picks up `0002`.

### 6. Run the server

```bash
uvicorn app:app --reload
```

### 7. Open Swagger UI

http://127.0.0.1:8000/docs

## Session API (primary interface)

An evaluation is a **session**: create one in `presentation` or `interview`
mode, upload its materials, and poll until it completes. Uploads return as
soon as the file is saved and validated — the actual AI analysis, that
material's preliminary score + reasoning pass, and (for video) the final
Fusion → Scoring → Reasoning tail all run in the background via FastAPI
`BackgroundTasks`, so the client is never blocked on a multi-second
Whisper/MediaPipe/Gemini call.

| Endpoint | Description |
|---|---|
| `POST /sessions` | Create a session. Body: `{"mode": "presentation" \| "interview", "language": "vi"}` |
| `POST /sessions/{id}/slide` | Upload slides (`.pptx`, Presentation mode only) |
| `POST /sessions/{id}/resume` | Upload a resume (`.pdf`, Interview mode only) |
| `POST /sessions/{id}/video` | Upload the video (`.mp4/.mov/.m4v`, either mode, once `state == waiting_for_video`) |
| `GET /sessions/{id}` | Current state, progress, and `legal_next_events` |
| `GET /sessions/{id}/preliminary/{stage}` | Preliminary (single-material) score + reasoning for `stage` (`slide`/`resume`/`video`) — available as soon as that material finishes its own review, well before the rest of the session's materials are uploaded |
| `GET /sessions/{id}/report` | Final, synthesized report — only available once `state == completed` |
| `POST /sessions/{id}/retry` | Retry a `failed` session from the exact sub-stage it failed at |
| `DELETE /sessions/{id}` | Delete the session and every row derived from it |

### State machine

```
Presentation:  empty ─upload_slide→ slide_uploaded ─start_slide_analysis→ slide_analyzing
               ─slide_analysis_done→ slide_analyzed ─start_slide_scoring→ slide_scoring
               ─slide_scoring_done→ slide_reasoning ─slide_reasoning_done→ slide_evaluated
               ─await_video→ waiting_for_video

Interview:     empty ─upload_resume→ resume_uploaded ─...(mirrors Presentation)...
               ─resume_reasoning_done→ resume_evaluated ─await_video→ waiting_for_video

Shared tail:   waiting_for_video ─upload_video→ video_uploaded ─start_video_analysis→ video_analyzing
               ─video_analysis_done→ video_analyzed ─start_video_scoring→ video_scoring
               ─video_scoring_done→ video_reasoning ─video_reasoning_done→ video_evaluated
               ─start_fusion→ feature_fusion ─fusion_done→ scoring ─scoring_done→ prompt_building
               ─prompt_built→ reasoning ─reasoning_done→ report_generated ─finalize→ completed
```

Any state may transition to `failed` on an exception; `POST /retry` resumes
from exactly the stage that failed (already-uploaded files and
already-persisted feature/score/preliminary-evaluation/report rows are
never re-processed). See `services/session_state_machine.py` for the full
transition table and `services/workflow_manager.py` for how each
sub-stage's failure maps back to its retry entry point.

### Example flow (Presentation mode)

```bash
# 1. Create a session
SESSION_ID=$(curl -s -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"mode": "presentation", "language": "vi"}' | jq -r .id)

# 2. Upload slides — returns immediately; analysis + preliminary review run in the background
curl -X POST "http://127.0.0.1:8000/sessions/$SESSION_ID/slide" -F "file=@slides.pptx"

# 3. Poll until the slide's own preliminary review finishes (state becomes "waiting_for_video")
curl "http://127.0.0.1:8000/sessions/$SESSION_ID"

# 3b. See feedback on the slides right away, before uploading a video
curl "http://127.0.0.1:8000/sessions/$SESSION_ID/preliminary/slide"

# 4. Upload the video — triggers vision + speech analysis, its own preliminary
#    review, then the final Fusion -> Scoring -> Reasoning synthesis
curl -X POST "http://127.0.0.1:8000/sessions/$SESSION_ID/video" -F "file=@presentation.mp4"

# 5. Poll until state == "completed", then fetch the final report
curl "http://127.0.0.1:8000/sessions/$SESSION_ID"
curl "http://127.0.0.1:8000/sessions/$SESSION_ID/report"
```

`GET /sessions/{id}/preliminary/{stage}` returns:

```json
{
  "session_id": "...",
  "stage": "slide",
  "scores": { "slide_score": 82, "overall_score": 82, "...": "null for every other sub-score" },
  "reasoning": { "strengths": ["..."], "weaknesses": ["..."], "presentation_feedback": "...", "...": "..." },
  "scoring_engine_version": "1.0.0",
  "reasoning_engine_name": "gemini",
  "reasoning_engine_version": "gemini-2.5-flash",
  "generated_at": "..."
}
```

`GET /sessions/{id}/report` returns:

```json
{
  "session_id": "...",
  "mode": "presentation",
  "scores": { "resume_score": null, "slide_score": 82, "overall_score": 76, "...": "..." },
  "derived_features": { "professionalism": 80.5, "...": "..." },
  "reasoning": { "strengths": ["..."], "weaknesses": ["..."], "presentation_feedback": "...", "...": "..." },
  "scoring_engine_version": "1.0.0",
  "fusion_engine_version": "1.0.0",
  "reasoning_engine_name": "gemini",
  "reasoning_engine_version": "gemini-2.5-flash",
  "generated_at": "..."
}
```

`overall_score` in the final report is a combination of the `slide` and
`video` preliminary `overall_score`s above (equal-weighted), not a fresh
recomputation — see "Preliminary evaluation & final synthesis" above.

## Legacy stateless API (deprecated, kept for backward compatibility)

`/extract/*`, `/analyze/*`, and `/evaluate*` still work exactly as in v2
(stateless, single request/response, no persistence, no preliminary
checkpoints) but are marked deprecated in Swagger. They're useful for
debugging a single extractor or analyzer in isolation. The standalone
Audio Upload API (`/extract/audio` as a first-class workflow, and a
dedicated audio-only evaluation path) has been **removed entirely** —
audio is now only ever analyzed as part of a session's video upload
(`services/workflow_manager.run_video_analysis` transcribes the video's
own audio track via Whisper; there is no standalone "upload just an audio
file to a session" endpoint).

## Deterministic scoring

Every score in `ScoreBreakdown` is computed by `services/scoring_engine.py`
from fixed, documented formulas over `UnifiedFeatureModel` +
`DerivedFeatures` (see `services/feature_fusion.py`) — never by the
reasoning engine. A sub-score is `null` only when its underlying material
was not supplied; a material's own `overall_score` (preliminary) is a
renormalized weighted average over whichever sub-scores that single
material has, and the session's final `overall_score` is a combination of
the per-material preliminary `overall_score`s.

`utils/scoring_math.py` provides the three primitives every formula is
built from: `band_score`, `weighted_average`, and `clamp_score`.

## Extending the platform

* **New reasoning provider** (Claude, GPT, a local model, a fine-tuned
  model): implement `BaseReasoningEngine` (`services/reasoning/base.py`),
  register it in `_REASONING_ENGINE_FACTORIES` in `providers/registry.py`,
  and point `reasoning_engine:` in `config/providers.yaml` at its name.
  `EvaluationWorkflowManager` never changes. Note that the Gemini API's
  structured-output schema rejects the `default` JSON Schema keyword —
  `services/gemini_service.py::_to_gemini_schema` strips it from
  `model_json_schema()` before sending; a new provider may need an
  equivalent step depending on its own schema constraints.
* **New extractor/analyzer** (e.g. a gesture analyzer): implement
  `BaseExtractor`/`BaseAnalyzer` and inject it into `AIOrchestrator`'s
  constructor. No router or workflow-manager change required.
* **New preliminary-evaluation stage**: add a value to `EvaluationStage`
  and the corresponding `*_SCORING`/`*_REASONING`/`*_EVALUATED` states to
  `SessionState`, extend `session_state_machine._TRANSITIONS`, and add a
  narrowing branch to `EvaluationWorkflowManager._hydrate_stage_only_features`.
  `_run_preliminary_evaluation` itself is already stage-generic.
* **Persona/Recommendation/Memory/RAG engines**: intentionally out of
  scope today, but the session/feature schema (`db/models.py`) and the
  provider-registry pattern were designed so these can be added as new
  tables + a new registry method later without touching
  `EvaluationWorkflowManager`, `FeatureFusionEngine`, `ScoringEngine`, or
  any existing API contract.

## Testing

```bash
pip install -r requirements.txt   # includes pytest, pytest-asyncio, httpx
pytest
```

The suite covers:

* `test_scoring_math.py` — `band_score` / `weighted_average` / `clamp_score`.
* `test_analyzers.py` / `test_extractors.py` — Layer 1/2 unit tests.
* `test_feature_fusion.py` / `test_scoring_engine.py` — full-feature and
  missing-feature scenarios, determinism checks.
* `test_endpoints.py` — legacy stateless-router `TestClient` tests.
* `test_session_state_machine.py` — every legal/illegal state transition
  in both modes, including the `*_SCORING`/`*_REASONING`/`*_EVALUATED`
  sub-stages.
* `test_workflow_manager.py` — `EvaluationWorkflowManager` against an
  in-memory SQLite DB: full happy paths (both modes), preliminary
  evaluations persisted and retrievable before the video is uploaded,
  final `overall_score` combination, failure + retry (both at the
  Layer 1/2 analysis stage and at the preliminary-evaluation stage),
  wrong-mode rejection, report-not-ready.
* `test_sessions_api.py` — the full HTTP surface end-to-end via
  `TestClient` (create → upload → poll → preliminary → report → delete).
* `test_provider_registry.py` — reasoning-engine resolution, caching, and
  unknown-provider error handling.

All AI calls (Whisper, MediaPipe, HSEmotion, Gemini) are mocked in tests
that don't specifically target them — no test in this suite makes a real
network call or requires a live PostgreSQL instance (workflow/API tests
use an in-memory SQLite database instead).

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `GEMINI_API_KEY is not set` | Missing `.env` or missing key | Create `.env` from `.env.example` and set your key |
| `Default value is not supported in the response schema for the Gemini API` | Gemini's structured-output schema rejects Pydantic's `default`/`default_factory` fields | Already handled — `GeminiService._to_gemini_schema` strips `default` before calling Gemini. If you see this on a custom reasoning model, apply the same stripping to its schema. |
| `sqlalchemy.exc.OperationalError` on startup | PostgreSQL not running, or `DATABASE_URL` wrong (including a port conflict with another local Postgres instance) | Start the `futureready-db` container; check host/port/user/password; try a different host port (e.g. `5433:5432`) if 5432 is already taken |
| `alembic upgrade head` fails / no such table | Migrations not applied yet, or only `0001` was applied before `0002` was added | Run `alembic upgrade head` after PostgreSQL is reachable; re-run it after pulling new migrations |
| `psycopg.errors.DuplicateObject: type "..." already exists` | A previous partial/failed migration left a Postgres enum type behind | `DROP TYPE IF EXISTS <type_name>;` for the affected enum(s), then re-run `alembic upgrade head` |
| `409 Conflict` on a session endpoint | Illegal state transition (e.g. uploading video before the slide's preliminary evaluation finishes) | Check `GET /sessions/{id}` → `legal_next_events` before the next upload |
| `409 Conflict` on `GET /sessions/{id}/preliminary/{stage}` | That material's preliminary evaluation hasn't completed yet | Poll `GET /sessions/{id}` until state moves past `{stage}_evaluated`/`waiting_for_video` |
| `413 Request Entity Too Large` | File exceeds `MAX_FILE_SIZE_MB` / `MAX_VIDEO_SIZE_MB` | Raise the limit in `.env` or compress the file |
| Session stuck in `failed` | An AI/analysis call raised (Layer 1/2 extraction, a preliminary reasoning call, or the final synthesis tail) | Check `error_message` and `failed_state` via `GET /sessions/{id}`, fix the underlying issue, then `POST /sessions/{id}/retry` |
| `503 Required dependency not installed` | Optional heavy dependency (torch/whisper/mediapipe/hsemotion-onnx/opencv) missing | `pip install -r requirements.txt` |
| First video upload is very slow | Whisper/HSEmotion downloading model weights on first use | Expected — subsequent calls are fast (models are cached in-process) |
