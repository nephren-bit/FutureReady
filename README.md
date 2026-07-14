# FutureReady (EmpathAI)

FutureReady is an AI-powered communication-coaching platform. It runs two
evaluation workflows — **Presentation** (slides + video) and **Interview**
(resume + video) — combining traditional AI, computer vision, and an LLM
into a single deterministic, production-quality pipeline, orchestrated
through persistent, resumable **sessions**. On top of that, two smaller
features round out the platform: a **Recommendation Engine** that suggests
curated learning resources targeted at a session's weakest areas, and
**Live Practice**, a WebSocket-streamed speaking-practice mode (optionally
with a slide deck/resume attached) for quick practice outside the full
session flow. A React/Vite **frontend** (`frontend/`) drives all three —
Dashboard, session upload/report views, and Live Practice — against the
FastAPI backend below.

This is the session-centric platform (v3): every evaluation is a persisted
`AnalysisSession` moving through an explicit state machine, with Layer 1/2
AI analysis running in the background so uploads return immediately and a
client polls for progress. As soon as each material (slide deck, resume,
or video) finishes analysis, it gets its own **preliminary score +
reasoning checkpoint** — the candidate sees feedback on their slides
immediately, without waiting for the video — and once every material has
been evaluated, a **final synthesis pass** reconciles the preliminary
checkpoints into one coherent report rather than reasoning over the raw
data from scratch. Once that report exists, the **Recommendation Engine**
automatically picks learning resources targeted at the session's weakest
areas. The original stateless Clean Architecture pipeline (v2) —
extractors, analyzers, feature fusion, scoring, prompt building, Gemini
reasoning — is unchanged and fully reused underneath; v3 adds persistence,
orchestration, per-material checkpoints, a swappable reasoning-provider
layer, recommendations, and live practice on top of it.

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
later touches no business logic. The Recommendation Engine follows the
same discipline in spirit: the reasoning engine never invents a resource,
it only picks from a closed, server-validated candidate list (see
"Recommendation Engine" below).

### What this project deliberately does NOT implement

A persona engine, authentication, model fine-tuning, RAG, and multi-agent
orchestration remain out of scope by design. (Live audio streaming and a
recommendation engine, previously listed here as future work, are now
implemented — see "Live Practice" and "Recommendation Engine" below.) The
codebase is structured so anything still out of scope can be added later
without touching `EvaluationWorkflowManager`, `FeatureFusionEngine`,
`ScoringEngine`, the API contracts, or the DB models — see "Extending the
platform" below.

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
       │ GET .../recommendations    │    preliminary score+reason │
┌──────┴───────┐                    │  - runs final Fusion/Scoring│
│AnalysisSession│◀──────persisted──│    /Prompt/Reasoning tail    │
│ + Preliminary │                  │  - runs RecommendationEngine │
│  Evaluation +  │                  └───────────────┬─────────────┘
│  Recommendation│                                  │
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

┌──────────────┐   WS /practice/stream (audio chunks in, live tips + final evaluation out)
│   Routers    │──────────────────────────────┐
│ practice.py  │                               ▼
└──────────────┘                    ┌────────────────────────────┐
       ▲                            │  PracticeSessionManager     │  ◀── its own small orchestrator,
       │ GET /practice/{id}         │  - assembles streamed audio │      NOT part of AnalysisSession's
       │ GET .../evaluation         │  - periodic Whisper re-pass │      state machine (see below)
┌──────┴────────┐                   │    + deterministic live tip │
│PracticeSession │◀─────persisted──│  - final Layer1/2/3/4/5/6    │
│ + Evaluation   │                  │    pass on end_session       │
│  (PostgreSQL)  │                  └────────────────────────────┘
└──────────────┘
```

Every extractor implements `BaseExtractor.extract()`; every analyzer
implements `BaseAnalyzer.analyze()` — both are swappable strategy classes
injected into `AIOrchestrator`, unchanged since v2. `FeatureFusionEngine`
and `ScoringEngine` remain concrete, non-swappable services: they are the
only source of derived features and numeric scores respectively, and are
never treated as plugins. `BaseReasoningEngine` is the one deliberately
swappable AI boundary, resolved via `providers/registry.py` and
`config/providers.yaml`. `PracticeSessionManager` reuses `AIOrchestrator`,
`FeatureFusionEngine`, `ScoringEngine`, and `PromptBuilder` directly rather
than duplicating any pipeline logic — Live Practice is a different entry
point into the same six layers, not a parallel implementation of them.

**Frontend.** `frontend/` is a Vite + React + TypeScript SPA that talks to
the routers above over `/api/*`, proxied by `vite.config.ts` to the FastAPI
backend on `:8000` (`ws: true` so the Live Practice WebSocket proxies too).
It never talks to Postgres or the AI services directly — every piece of
state it holds is exactly what the corresponding `GET` endpoint returns,
including `legal_next_events` on a session, which the Dashboard/session
pages use to decide what upload action is currently legal instead of
re-deriving the state machine client-side. See "Frontend" below for the
page-by-page breakdown and dev setup.

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
(`VIDEO_SCORING` → `VIDEO_REASONING` → `VIDEO_EVALUATED`). A video with no
usable audio track (silent recording, video-only export, an
unsupported/corrupt audio codec) does **not** fail the session:
`EvaluationWorkflowManager.run_video_analysis` runs speech transcription
(Whisper) in its own try/except and, if it raises, logs a warning and
skips speech/transcript scoring for that material only — video, emotion,
and eye-contact/face-mesh scoring still complete normally, since
`speech_score`/`transcript_score` are already-optional sub-scores
throughout `ScoreBreakdown` (`null` whenever their source material is
absent, exactly like a session missing a material entirely).

Once every material required by the session's mode has its own
preliminary evaluation, the shared tail runs: Feature Fusion → Scoring →
Prompt Building → Reasoning, producing the **final** report, followed
immediately by the Recommendation Engine pass (see below). Two decisions
make the final report a synthesis rather than a fresh evaluation:

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
Fusion/Scoring/Prompt/Reasoning/Recommending didn't finish.

## Recommendation Engine

Once a session's final report exists (`REPORT_GENERATED`), the session
moves into a `RECOMMENDING` state and the Recommendation Engine picks 3-5
learning resources targeted at the session's weakest areas, before the
session reaches `COMPLETED`. This is an MVP, LLM-driven strategy —
`docs/ERD_Design.md` §4 documents a `rule_engine`/`tfrs` (TensorFlow
Recommenders) upgrade path the schema already accommodates via
`RecommendationORM.generated_by`, without any migration.

**Candidate-list-constrained selection.** The reasoning engine is never
allowed to invent a resource. `RecommendationEngine.candidate_resources`
queries every active row in `learning_resources` and hands the reasoning
engine a closed list of `{id, title, skill_tags, category, language,
resource_type}` (see `prompts/recommendation_prompt.py`), instructed to
pick only from that list and copy `resource_id` exactly.
`RecommendationEngine.validate_picks` then defensively filters the
response against the real candidate IDs server-side, dedupes, and caps at
5 — a hallucinated or malformed ID is silently dropped rather than trusted.

**Catalog.** `learning_resources` is seeded from two curated Excel
catalogs (kept under `data/learning_resources/` for a stable,
version-controlled source):

```bash
python -m scripts.seed_learning_resources
# or explicitly:
python -m scripts.seed_learning_resources --vietfuture data/learning_resources/VietFuture.xlsx --ted data/learning_resources/Danh_Sach_TED_Talk_Ky_Nang.xlsx
```

The script is idempotent — it matches existing rows by `url` (the table's
unique constraint) and skips ones already present, so re-running it after
adding new rows to the source spreadsheets only inserts the new ones. If
the catalog has never been seeded, `RECOMMENDING` still completes
successfully with zero picks (see `_run_recommendations` in
`services/workflow_manager.py`) — a missing catalog is not a session
failure, just nothing to suggest yet.

`GET /sessions/{id}/recommendations` (only available once
`state == completed`) returns:

```json
{
  "session_id": "...",
  "recommendations": [
    {
      "resource_title": "...",
      "resource_url": "https://...",
      "resource_type": "video",
      "platform": "Youtube",
      "language": "vi",
      "speaker": "...",
      "rank": 1,
      "rationale": "Targets the low eye-contact and confidence sub-scores flagged in the final report.",
      "target_skill_tags": ["confidence", "speaking"]
    }
  ],
  "generated_by": "llm"
}
```

## Live Practice

A WebSocket-streamed speaking-practice mode that never touches
`AnalysisSession` at all — no 20-state session machine, just a
short-lived `PracticeSessionORM` with its own five-state lifecycle
(`connecting` → `streaming` → `finalizing` → `completed`/`failed`, see
`db.models.PracticeSessionState`). The audio pipeline is otherwise
identical to a session's speech material (Librosa + Whisper + the
deterministic transcript analyzer). The frontend's Practice page
(`frontend/src/pages/Practice.tsx`, `/app/practice`) drives it: pick
**Presentation** or **Interview** mode, optionally attach a slide
deck/resume, then record.

**Optional slide/resume attachment.** A practice session can optionally
carry the same `mode` (`presentation`/`interview`) and a `slide_file_path`/
`resume_file_path` an `AnalysisSession` does (see migration
`0005_practice_materials.py`), so the recording is scored alongside real
slide/CV content instead of audio alone:

| Endpoint | Description |
|---|---|
| `POST /practice` | Create a session ahead of streaming. Body: `{"mode": "presentation" \| "interview" \| null, "language": "vi"}` |
| `POST /practice/{id}/slide` | Attach slides (`.pptx`, Presentation mode only) — only legal while `state == connecting` |
| `POST /practice/{id}/resume` | Attach a resume (`.pdf`, Interview mode only) — only legal while `state == connecting` |

Wrong mode for the attached file, or attaching after streaming has
started, returns `409` (`PracticeMaterialError`). Skip `POST /practice`
entirely for a plain audio-only practice — `WS /practice/stream` creates
its own session exactly as before.

**Wire protocol** — `WS /practice/stream?language=vi&audio_format=wav&practice_session_id=...`
(`audio_format` ∈ `wav`/`webm`/`ogg`/`mp3`/`m4a`; `practice_session_id` is
optional — pass the id from `POST /practice` to stream into a session with
material already attached, omit it for a fresh audio-only session):

```
client → server: binary frames — raw, already-encoded audio chunks
client → server: {"type": "end_session"}                (text frame, when done)

server → client: {"type": "session_started", "session_id": "..."}
server → client: {"type": "partial_transcript", "transcript": "..."}     (periodic)
server → client: {"type": "live_tip", "message": "..."}                  (periodic, when there's something to flag)
server → client: {"type": "final_evaluation", "session_id": "...", "scores": {...}, "reasoning": {...}, ...}
server → client: {"type": "final_evaluation_failed", "session_id": "...", "error_message": "..."}
```

**Live tips are free — no LLM call per chunk.** Every
`_PARTIAL_TRANSCRIBE_EVERY_N_CHUNKS` (5) chunks, the server re-runs
Whisper on the buffered recording so far (best-effort — a not-yet-decodable
mid-stream buffer just skips that cycle rather than erroring) and runs the
same deterministic `TranscriptAnalyzer` a session already uses, flagging
high filler-word ratio or low vocabulary diversity in plain-language tips
(`PracticeSessionManager.partial_transcript_tip`). The one and only LLM
call in the entire flow happens once, at `end_session`.

**Finalize** (`PracticeSessionManager.finalize`) runs the same six-layer
pipeline a session's materials go through — `AIOrchestrator.
build_unified_features(audio_path=..., slide_path=..., resume_path=...)`
(the last two only if attached) → `FeatureFusionEngine.fuse` →
`ScoringEngine.score` → `PromptBuilder.build_preliminary("practice", ...)`
→ the configured reasoning engine — and persists a
`PracticeEvaluationORM` (same field shape as a session's
`PreliminaryEvaluationORM`; `slide_score`/`resume_score` are populated too
when that material was attached). If the client disconnects without
sending `end_session`, the server still finalizes whatever was recorded on
a best-effort basis; the result is retrievable afterward regardless.

Retrieval, after the socket closes:

| Endpoint | Description |
|---|---|
| `GET /practice/{id}` | Current status (`state`, `mode`, `has_slide`/`has_resume`, `transcript_so_far`, timestamps) |
| `GET /practice/{id}/evaluation` | The final evaluation — `409` until `state == completed` |

## Folder structure

```
FutureReady/
├── app.py                       # FastAPI entry point (sessions + practice routers + deprecated legacy routers)
├── config.py                    # Centralized configuration (env vars)
├── requirements.txt
├── pytest.ini
├── alembic.ini
├── .env.example
├── uploads/                     # Uploaded files + assembled practice recordings (kept for retry/recovery, not auto-deleted)
├── data/
│   └── learning_resources/      #   VietFuture.xlsx, Danh_Sach_TED_Talk_Ky_Nang.xlsx (Recommendation Engine seed source)
├── scripts/
│   └── seed_learning_resources.py  # Idempotent seed script for the learning_resources catalog
├── db/                          # Persistence layer (PostgreSQL via SQLAlchemy 2.0)
│   ├── base.py                  #   Shared DeclarativeBase
│   ├── models.py                #   AnalysisSession, PreliminaryEvaluationORM, LearningResourceORM,
│   │                             #   RecommendationORM, PracticeSessionORM (mode/slide/resume paths), PracticeEvaluationORM, every feature/score/report table
│   └── session.py               #   Engine, SessionLocal, get_db() FastAPI dependency
├── migrations/                  # Alembic migrations (hand-written, not autogenerated)
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py           # AnalysisSession + Layer 1-6 feature/score/report tables
│       ├── 0002_preliminary_evaluations.py  # *_SCORING/*_REASONING/*_EVALUATED states + preliminary_evaluations table
│       ├── 0003_recommendation_engine.py    # RECOMMENDING state + learning_resources/recommendations tables
│       ├── 0004_practice_sessions.py        # practice_sessions/practice_evaluations tables (own enum, not part of session_state)
│       └── 0005_practice_materials.py       # mode/slide_file_path/resume_file_path on practice_sessions (optional slide/resume attachment)
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
│   ├── ai_orchestrator.py       #   Facade driving Layers 1-6 (used by legacy routers, WorkflowManager, and PracticeSessionManager)
│   ├── feature_fusion.py        #   Layer 3 — DerivedFeatures (concrete, not a plugin)
│   ├── scoring_engine.py        #   Layer 4 — ScoreBreakdown (concrete, not a plugin; documented formulas)
│   ├── prompt_builder.py        #   Layer 5 — prompt composition service (EVALUATE + PRELIMINARY + RECOMMEND tasks)
│   ├── gemini_service.py        #   google-genai SDK wrapper (used by GeminiReasoningEngine)
│   ├── reasoning/
│   │   ├── base.py              #   BaseReasoningEngine contract
│   │   └── gemini_engine.py     #   GeminiReasoningEngine (current implementation)
│   ├── recommendation_engine.py #   Candidate-list-constrained LLM resource picking + server-side validation
│   ├── practice_session_manager.py  # Live Practice orchestrator (own lifecycle, reuses Layers 1-6)
│   ├── session_state_machine.py #   Pure transition table for AnalysisSession.state
│   ├── session_mappers.py       #   ORM row <-> Pydantic feature model conversions
│   └── workflow_manager.py      #   EvaluationWorkflowManager — the sole AnalysisSession orchestrator
├── routers/
│   ├── sessions.py              #   POST /sessions, GET /sessions (list), /sessions/{id}/{slide,resume,video,retry}, GET .../{id}, .../report, .../preliminary/{stage}, .../recommendations, DELETE
│   ├── practice.py              #   POST /practice, /practice/{id}/{slide,resume}, WS /practice/stream, GET /practice/{id}, GET /practice/{id}/evaluation
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
│   ├── preliminary_prompt.py    #   Single-material preliminary review prompt (stages: slide/resume/video/practice)
│   └── recommendation_prompt.py #   Candidate-list-constrained learning-resource picking prompt
├── models/
│   ├── features.py              #   UnifiedFeatureModel + every feature/score model
│   ├── session_models.py        #   SessionCreateRequest / SessionResponse / SessionReportResponse / PreliminaryEvaluationResponse / RecommendationListResponse
│   ├── practice_models.py       #   PracticeSessionCreateRequest / PracticeSessionResponse / PracticeEvaluationResponse
│   ├── requests.py              #   Legacy request bodies
│   └── responses.py             #   EvaluationReport, ReasoningPayload, RecommendationPayload, ErrorResponse
├── utils/
│   ├── file_utils.py            #   Upload validation, save, cleanup
│   ├── scoring_math.py          #   band_score / weighted_average / clamp_score
│   └── logger.py                #   Centralized logging
├── tests/                       #   Unit + integration tests (see "Testing" below)
└── frontend/                    #   Vite + React + TypeScript SPA (see "Frontend" below)
    ├── vite.config.ts           #   Dev-server proxy: /api -> http://localhost:8000 (ws: true for /practice/stream)
    └── src/
        ├── App.tsx              #   Routes: /, /app, /app/new, /app/practice, /app/sessions/:id, /app/sessions/:id/report
        ├── lib/api.ts           #   axios client (Session/Practice REST) + practiceStreamUrl() for the WS
        ├── types/index.ts       #   TS mirrors of every Pydantic response model (SessionState/ScoreBreakdown/PracticeSession/...)
        ├── components/
        │   ├── layout/          #   Navbar, Footer
        │   └── charts/          #   ScoreRadar, ScoreBar (Recharts)
        └── pages/
            ├── Landing.tsx      #   Marketing page at "/"
            ├── Dashboard.tsx    #   List/retry/delete sessions ("/app")
            ├── NewSession.tsx   #   Create a session, pick Presentation/Interview ("/app/new")
            ├── SessionDetail.tsx#   Upload materials, poll progress, view preliminary results ("/app/sessions/:id")
            ├── Report.tsx       #   Final report: scores, derived features, reasoning ("/app/sessions/:id/report")
            └── Practice.tsx     #   Live Practice: mode + optional slide/CV, mic recording, live tips, results ("/app/practice")
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
> large downloads and may take a while to install. Whisper and HSEmotion
> also download their model weights on first use — the first video/practice
> upload will be slower than subsequent ones. On Windows, if `pip install`
> fails on `openai-whisper` with `ModuleNotFoundError: No module named
> 'pkg_resources'`, run `pip install "setuptools<81" wheel` first.
>
> `truststore` (in `requirements.txt`) makes every outgoing HTTPS call
> (Gemini included, via `services/gemini_service.py`) trust the OS
> certificate store instead of just the `certifi` bundle — needed because
> some antivirus products (AVG, Avast, Kaspersky, ESET, ...) intercept
> HTTPS with their own locally-generated root CA, which Windows trusts but
> `certifi` doesn't. No action needed; it's wired in automatically. If you
> still see `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
> unable to get local issuer certificate` from Gemini, see Troubleshooting.

**`ffmpeg` is required, not optional** — both `librosa` (audio extraction)
and `openai-whisper` (speech transcription) shell out to it to decode
audio/video. Without it on `PATH`, transcription fails with `[WinError 2]
The system cannot find the file specified` (Windows) or `FileNotFoundError:
[Errno 2] No such file or directory: 'ffmpeg'` (macOS/Linux):

```bash
# Windows (winget, built into Windows 10/11)
winget install --id Gyan.FFmpeg -e

# macOS
brew install ffmpeg

# Debian/Ubuntu
sudo apt install ffmpeg
```

`winget`/most installers update `PATH` for new shells automatically; if a
shell was already open when you installed it, open a new one (or restart
`uvicorn`) so it picks up the change.

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
| `UPLOAD_DIR` | `uploads` | Upload storage directory (kept for session recovery; also where Live Practice recordings are assembled) |
| `MAX_FILE_SIZE_MB` | `25` | Max size for PDF/PPTX uploads |
| `MAX_VIDEO_SIZE_MB` | `300` | Max size for video uploads |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_URL` | `postgresql+psycopg://futureready:futureready@localhost:5432/futureready` | SQLAlchemy connection string for session persistence |
| `SCORING_ENGINE_VERSION` | `1.0.0` | Stamped onto every `ScoreResult`/`PreliminaryEvaluation`/`PracticeEvaluation` row for reproducibility |
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

This applies, in order: `0001_initial_schema.py` (core session/feature/
score tables), `0002_preliminary_evaluations.py` (preliminary-evaluation
sub-states + table), `0003_recommendation_engine.py` (`RECOMMENDING` state
+ `learning_resources`/`recommendations` tables), `0004_practice_sessions.py`
(`practice_sessions`/`practice_evaluations` tables), and
`0005_practice_materials.py` (`mode`/`slide_file_path`/`resume_file_path` on
`practice_sessions`, for optional slide/resume attachment — see "Live
Practice"). If you're upgrading an existing database that's behind,
running `alembic upgrade head` picks up everything newer in order.

### 6. Seed the Recommendation Engine catalog (optional but recommended)

```bash
python -m scripts.seed_learning_resources
```

Without this, `GET /sessions/{id}/recommendations` still works, it just
returns an empty list — see "Recommendation Engine" above.

### 7. Run the server

```bash
uvicorn app:app --reload
```

### 8. Open Swagger UI

http://127.0.0.1:8000/docs

(Swagger's built-in "Try it out" doesn't speak WebSocket — test
`/practice/stream` with `websocat`, a small script, or a real client; see
"Live Practice" above for the wire protocol.)

### 9. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at http://localhost:5173 — `vite.config.ts` proxies `/api/*` (HTTP
and WebSocket) to the backend on `:8000`, so both must be running. See
"Frontend" below for the page-by-page breakdown, or `npm run build` for a
production bundle.

## Session API (primary interface)

An evaluation is a **session**: create one in `presentation` or `interview`
mode, upload its materials, and poll until it completes. Uploads return as
soon as the file is saved and validated — the actual AI analysis, that
material's preliminary score + reasoning pass, and (for video) the final
Fusion → Scoring → Reasoning → Recommending tail all run in the background
via FastAPI `BackgroundTasks`, so the client is never blocked on a
multi-second Whisper/MediaPipe/Gemini call.

| Endpoint | Description |
|---|---|
| `POST /sessions` | Create a session. Body: `{"mode": "presentation" \| "interview", "language": "vi"}` |
| `GET /sessions` | List every session, most recently created first (used by the frontend Dashboard) |
| `POST /sessions/{id}/slide` | Upload slides (`.pptx`, Presentation mode only) |
| `POST /sessions/{id}/resume` | Upload a resume (`.pdf`, Interview mode only) |
| `POST /sessions/{id}/video` | Upload the video (`.mp4/.mov/.m4v`, either mode, once `state == waiting_for_video`) |
| `GET /sessions/{id}` | Current state, progress, and `legal_next_events` |
| `GET /sessions/{id}/preliminary/{stage}` | Preliminary (single-material) score + reasoning for `stage` (`slide`/`resume`/`video`) — available as soon as that material finishes its own review, well before the rest of the session's materials are uploaded |
| `GET /sessions/{id}/report` | Final, synthesized report — only available once `state == completed` |
| `GET /sessions/{id}/recommendations` | Ranked learning-resource picks — only available once `state == completed` |
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
               ─prompt_built→ reasoning ─reasoning_done→ report_generated
               ─start_recommending→ recommending ─finalize→ completed
```

Any state may transition to `failed` on an exception; `POST /retry` resumes
from exactly the stage that failed (already-uploaded files and
already-persisted feature/score/preliminary-evaluation/report/
recommendation rows are never re-processed). See
`services/session_state_machine.py` for the full transition table and
`services/workflow_manager.py` for how each sub-stage's failure maps back
to its retry entry point.

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
#    review, then the final Fusion -> Scoring -> Reasoning -> Recommending synthesis
curl -X POST "http://127.0.0.1:8000/sessions/$SESSION_ID/video" -F "file=@presentation.mp4"

# 5. Poll until state == "completed", then fetch the final report + recommendations
curl "http://127.0.0.1:8000/sessions/$SESSION_ID"
curl "http://127.0.0.1:8000/sessions/$SESSION_ID/report"
curl "http://127.0.0.1:8000/sessions/$SESSION_ID/recommendations"
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
`GET /sessions/{id}/recommendations` returns the shape documented in
"Recommendation Engine" above.

## Frontend

`frontend/` is a Vite + React 19 + TypeScript SPA (Tailwind, Recharts,
`@phosphor-icons/react`, `motion`), routed under `/` (marketing landing
page) and `/app/*` (the product). Every page's state is exactly what its
corresponding backend endpoint returns — no client-side re-derivation of
the session state machine:

| Route | Page | Backend endpoints used |
|---|---|---|
| `/app` | `Dashboard.tsx` — list, retry, delete sessions | `GET /sessions`, `POST /sessions/{id}/retry`, `DELETE /sessions/{id}` |
| `/app/new` | `NewSession.tsx` — pick Presentation/Interview + language | `POST /sessions` |
| `/app/sessions/:id` | `SessionDetail.tsx` — upload materials, poll progress, view preliminary results | `GET /sessions/{id}`, `POST .../{slide,resume,video}`, `GET .../preliminary/{stage}` |
| `/app/sessions/:id/report` | `Report.tsx` — final scores, derived features, reasoning | `GET /sessions/{id}/report` |
| `/app/practice` | `Practice.tsx` — Live Practice: mode + optional slide/CV, mic recording, live tips, results | `POST /practice`, `POST /practice/{id}/{slide,resume}`, `WS /practice/stream`, `GET /practice/{id}/evaluation` |

**Upload gating via `legal_next_events`.** Rather than hard-coding which
upload button is enabled for a given `SessionState`, `SessionDetail.tsx`
reads `legal_next_events` off `GET /sessions/{id}` (e.g. `["upload_slide"]`,
`["upload_video"]`, `[]` once terminal) and enables exactly the upload(s)
named there — see `services/session_state_machine.legal_events`, which is
the single source of truth for what the state machine allows next.

**Live Practice's recording flow**: request microphone access
(`getUserMedia`) → `MediaRecorder` (auto-detects a supported
`audio/webm`/`audio/ogg`/`audio/mp4` MIME type and maps it to the
matching `audio_format`) → stream chunks over the WebSocket as they're
produced → on stop, send `{"type": "end_session"}` and render the
`final_evaluation` payload. If a slide/CV was selected, the page first
calls `POST /practice` + `POST /practice/{id}/slide`\|`/resume`, then opens
the WebSocket with that session's id so the recording lands in the same
session as the attached material (see "Live Practice" above). The
"finalizing" step shows a simulated, named-stage progress bar (extraction
→ speech analysis → fusion → scoring → reasoning) rather than a bare
spinner — the backend runs this as one pass with no intermediate
checkpoints to poll, so the bar is time-based and always resolves for real
once `final_evaluation`/`final_evaluation_failed` actually arrives.

## Legacy stateless API (deprecated, kept for backward compatibility)

`/extract/*`, `/analyze/*`, and `/evaluate*` still work exactly as in v2
(stateless, single request/response, no persistence, no preliminary
checkpoints) but are marked deprecated in Swagger. They're useful for
debugging a single extractor or analyzer in isolation. The standalone
Audio Upload API (`/extract/audio` as a first-class workflow, and a
dedicated audio-only evaluation path) has been **removed entirely** from
the Session API — audio is only ever analyzed as part of a session's video
upload (`services/workflow_manager.run_video_analysis` transcribes the
video's own audio track via Whisper). Standalone audio-only evaluation
outside a session now lives in **Live Practice** instead (see above),
which is a purpose-built replacement for that use case rather than a
revival of the old endpoint.

## Deterministic scoring

Every score in `ScoreBreakdown` is computed by `services/scoring_engine.py`
from fixed, documented formulas over `UnifiedFeatureModel` +
`DerivedFeatures` (see `services/feature_fusion.py`) — never by the
reasoning engine. A sub-score is `null` only when its underlying material
was not supplied; a material's own `overall_score` (preliminary, or a Live
Practice evaluation) is a renormalized weighted average over whichever
sub-scores that single material has, and a session's final `overall_score`
is a combination of the per-material preliminary `overall_score`s.

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
  `_run_preliminary_evaluation` itself is already stage-generic. (`"practice"`
  in `prompts/preliminary_prompt.py` is an example of a stage that is
  reasoning-prompt-generic but deliberately NOT wired into `SessionState`
  at all — see "Live Practice".)
* **Recommendation Engine upgrade** (rule-based or TFRS instead of LLM):
  implement the new strategy behind the same `candidate_resources` /
  `build_prompt` / `validate_picks` shape in
  `services/recommendation_engine.py` and set `generated_by` accordingly
  on the rows it writes — `docs/ERD_Design.md` §4 documents this path; no
  schema change is required.
* **Persona/Memory/RAG engines**: intentionally out of scope today, but
  the schema (`db/models.py`) and the provider-registry pattern were
  designed so these can be added as new tables + a new registry method
  later without touching `EvaluationWorkflowManager`, `FeatureFusionEngine`,
  `ScoringEngine`, or any existing API contract.

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
  sub-stages and the `report_generated → recommending → completed` tail.
* `test_workflow_manager.py` — `EvaluationWorkflowManager` against an
  in-memory SQLite DB: full happy paths (both modes), preliminary
  evaluations persisted and retrievable before the video is uploaded,
  final `overall_score` combination, recommendation generation/validation
  against a seeded catalog, failure + retry (Layer 1/2 analysis stage,
  preliminary-evaluation stage, and recommending stage), wrong-mode
  rejection, report-not-ready.
* `test_sessions_api.py` — the full HTTP surface end-to-end via
  `TestClient` (create → upload → poll → preliminary → report →
  recommendations → delete).
* `test_provider_registry.py` — reasoning-engine resolution, caching, and
  unknown-provider error handling.
* `test_practice_session_manager.py` — `PracticeSessionManager` against an
  in-memory SQLite DB: lifecycle transitions, finalize with no/empty audio,
  finalize success persisting a `PracticeEvaluationORM`, finalize recording
  a reasoning-engine failure, and the deterministic live-tip heuristic.
* `test_practice_api.py` — the full `/practice/stream` WebSocket flow via
  `TestClient.websocket_connect` (session_started → audio chunks →
  end_session → final_evaluation), plus the `GET /practice/{id}` /
  `GET /practice/{id}/evaluation` REST endpoints. One test documents a
  known `TestClient` quirk: it cancels the server-side task very
  aggressively right after a client disconnect, more aggressively than a
  real ASGI server (uvicorn) does — so that specific test asserts the
  handler never crashes and the session stays queryable, rather than
  asserting `finalize()` always wins that race; the actual
  finalize-on-disconnect behavior is covered directly at the unit level in
  `test_practice_session_manager.py`.

All AI calls (Whisper, MediaPipe, HSEmotion, Gemini) are mocked in tests
that don't specifically target them — no test in this suite makes a real
network call or requires a live PostgreSQL instance (workflow/API tests
use an in-memory SQLite database instead).

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `GEMINI_API_KEY is not set` | Missing `.env` or missing key | Create `.env` from `.env.example` and set your key |
| `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate` (calling Gemini) | Antivirus HTTPS scanning (AVG, Avast, Kaspersky, ESET, ...) intercepts the connection with its own root CA, which Windows trusts but Python's `certifi` bundle doesn't | Already handled — `truststore.inject_into_ssl()` in `services/gemini_service.py` makes Python trust the OS certificate store instead. If it still happens (e.g. a different outgoing call not yet routed through this), the antivirus's HTTPS-scanning feature is the cause; the same `truststore` fix or disabling that feature resolves it |
| `Default value is not supported in the response schema for the Gemini API` | Gemini's structured-output schema rejects Pydantic's `default`/`default_factory` fields | Already handled — `GeminiService._to_gemini_schema` strips `default` before calling Gemini. If you see this on a custom reasoning model, apply the same stripping to its schema. |
| `Speech transcription failed: [WinError 2] The system cannot find the file specified` (or `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`) | `ffmpeg` isn't installed / isn't on `PATH` — both `librosa` and Whisper shell out to it | Install it (see Installation step 2) and restart `uvicorn` from a shell that has the updated `PATH` |
| `Speech transcription failed: Failed to load audio: ... Output file does not contain any stream` | The uploaded video has no audio track (silent/video-only export) | Already handled — `run_video_analysis` catches this and skips speech/transcript scoring for that material only; video/emotion/eye-contact scoring and the rest of the session still complete normally |
| `sqlalchemy.exc.OperationalError` on startup | PostgreSQL not running, or `DATABASE_URL` wrong (including a port conflict with another local Postgres instance) | Start the `futureready-db` container; check host/port/user/password; try a different host port (e.g. `5433:5432`) if 5432 is already taken |
| `alembic upgrade head` fails / no such table | Migrations not applied yet, or you're behind on newer ones (0003/0004/0005) | Run `alembic upgrade head` after PostgreSQL is reachable; re-run it after pulling new migrations |
| `psycopg.errors.DuplicateObject: type "..." already exists` | A previous partial/failed migration left a Postgres enum type behind | `DROP TYPE IF EXISTS <type_name>;` for the affected enum(s), then re-run `alembic upgrade head` |
| `409 Conflict` on a session endpoint | Illegal state transition (e.g. uploading video before the slide's preliminary evaluation finishes) | Check `GET /sessions/{id}` → `legal_next_events` before the next upload |
| `409 Conflict` on `GET /sessions/{id}/preliminary/{stage}` | That material's preliminary evaluation hasn't completed yet | Poll `GET /sessions/{id}` until state moves past `{stage}_evaluated`/`waiting_for_video` |
| `GET /sessions/{id}/recommendations` returns an empty list | `learning_resources` catalog hasn't been seeded | Run `python -m scripts.seed_learning_resources` |
| `409 Conflict` on `GET /practice/{id}/evaluation` | The practice session hasn't finished (`state` isn't `completed` yet) | Send `{"type": "end_session"}` over the socket and wait for `final_evaluation`, or poll `GET /practice/{id}` |
| `409 Conflict` on `POST /practice/{id}/slide`\|`/resume` | Wrong material for the session's mode, or streaming has already started | Attach slides only to a `presentation`-mode session (resume only to `interview`), and only while `state == connecting` |
| `413 Request Entity Too Large` | File exceeds `MAX_FILE_SIZE_MB` / `MAX_VIDEO_SIZE_MB` | Raise the limit in `.env` or compress the file |
| Session stuck in `failed` | An AI/analysis call raised (Layer 1/2 extraction, a preliminary reasoning call, the final synthesis tail, or the recommending stage) | Check `error_message` and `failed_state` via `GET /sessions/{id}`, fix the underlying issue, then `POST /sessions/{id}/retry` |
| `503 Required dependency not installed` | Optional heavy dependency (torch/whisper/mediapipe/hsemotion-onnx/opencv) missing | `pip install -r requirements.txt` |
| First video/practice-session upload is very slow | Whisper/HSEmotion downloading model weights on first use | Expected — subsequent calls are fast (models are cached in-process) |
