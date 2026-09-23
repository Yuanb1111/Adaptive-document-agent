# Adaptive Document Intelligence Agent

Adaptive Document Intelligence Agent is a production-minded Streamlit prototype for analysing an unfamiliar, data-rich PDF without asking the user to choose a document type first. It preserves page-level evidence, discovers what information is actually present, selects analyses supported by that evidence, performs calculations in deterministic Python, and produces a traceable report and presentation.

The project currently processes one PDF synchronously. Its generic analysis pipeline works end to end, and the repository now also contains a stronger financial-document layer for normalized facts, period semantics, sign-aware claims, and presentation QA. OCR execution and pixel-backed chart interpretation remain extension points rather than bundled capabilities.

## Project Overview

The application can:

- validate and hash an uploaded PDF;
- build a page map and require confirmation of the page ranges selected for deep analysis;
- extract digital text, bordered tables, aligned borderless tables, images, and page-level provenance;
- reconstruct table structure and likely cross-page continuations;
- discover the document purpose, sections, metrics, dimensions, entities, periods, units, and limitations;
- preserve raw values while building normalized observations and, where applicable, typed financial facts;
- propose, score, and execute only analyses supported by the available data;
- run arithmetic and statistics through deterministic tools and a restricted formula evaluator;
- validate extraction, semantics, units, periods, calculations, evidence, narrative claims, and presentation consistency;
- generate a dynamic Markdown report, interactive Plotly charts, a formatted PDF, and an editable PowerPoint presentation;
- block PowerPoint export when critical factual or financial contradictions remain unresolved.

The responsibility split is:

- **LLMs:** semantic discovery, conservative metric resolution, analysis prioritisation, insight wording, report organisation, and presentation story planning.
- **Python:** extraction, normalization, arithmetic, statistics, ranking, safe formula evaluation, chart construction, and deterministic validation.
- **Validators:** decide what is sufficiently supported to retain, repair, warn about, or block from export.

PDF contents are untrusted source material. Instructions embedded in a document are treated as data, never as commands.

## Architecture

```text
PDF
  -> validation, hashing, page-level parsing, and cache
  -> model-selected page ranges (optional user review)
  -> text, table, image, and OCR/vision requirement detection
  -> document discovery and semantic resolution
  -> observations -> normalized financial facts where applicable
  -> global document index
  -> candidate generation -> value scoring -> validated analysis plan
  -> targeted extraction -> deterministic tool execution
  -> extraction, semantic, consistency, calculation, evidence, and coverage validation
  -> grounded insights -> dynamic report and chart plans
  -> evidence-bound presentation plan -> repair/recovery and comprehensive QA
  -> Streamlit results and exports
```

All model access crosses one provider-independent boundary:

```text
Agent modules -> LLMGateway -> LLMClient -> LiteLLMProvider -> configured provider
```

Agent modules do not import provider SDKs or LiteLLM directly. Stage-specific model routing is supported without changing business logic.

The main programmatic entry point is:

```python
from adaptive_document_agent.agent.orchestrator import analyse_pdf

result = analyse_pdf(pdf_bytes, gateway=gateway)
```

The Streamlit UI starts analysis automatically after upload. It uses document discovery to select evidence-bearing page ranges, then prepares and verifies the PowerPoint export. Users who need to override the automatic scope can enable the optional review mode, call `DocumentOrchestrator.preview_scope(...)`, and confirm the proposed ranges before rerunning deep analysis.

## Repository Layout

```text
app.py                              Streamlit entry point
adaptive_document_agent/
  agent/                            discovery, planning, execution, reporting, presentation
  document_model/                   global index, comparable series, period/topic semantics
  extraction/                       PDF, text, table, image, numeric, OCR, and vision adapters
  models/                           evidence, observations, canonical facts, reports, presentations
  prompts/                          prompts that treat document text as untrusted
  services/                         LLM boundary, normalization, exports, QA, formatting
  templates/                        bundled FOURIER PowerPoint template
  tools/                            deterministic calculations and safe formula evaluator
  ui/                               Streamlit views and deployment/session handling
  validation/                       analysis, claim, layout, coverage, and cross-slide validators
docs/MASTER_PROMPT.md               authoritative engineering specification
tests/                              unit, regression, export, and pipeline tests
```

## Installation

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For development and tests:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

A Python 3.11 development-container configuration is included in `.devcontainer/` and starts Streamlit on port 8501 after attachment.

## Configuration

Copy `.env.example` to `.env` and set only the values required by the selected provider. Never commit `.env` or real API keys.

```dotenv
EXECUTION_MODE=auto
LOCAL_ONLY=false
PUBLIC_DEPLOYMENT=false

LLM_PROVIDER=ollama
LLM_MODEL=
LLM_API_KEY=
LLM_BASE_URL=http://localhost:11434
LLM_TIMEOUT_SECONDS=120
LLM_TEMPERATURE=0

LOG_LEVEL=INFO
CACHE_DIR=.adaptive_document_cache
```

`EXECUTION_MODE` accepts `auto`, `cloud`, or `local_only`. Setting `LOCAL_ONLY=true` takes precedence and forces Local Only mode.

Optional stage routes are:

```dotenv
LLM_DISCOVERY_MODEL=
LLM_SEMANTIC_MODEL=
LLM_EXTRACTION_MODEL=
LLM_PLANNER_MODEL=
LLM_VISION_MODEL=
LLM_INSIGHT_MODEL=
LLM_REPORT_MODEL=
LLM_PRESENTATION_MODEL=
```

The sidebar can override the provider, model, base URL, execution mode, and API key for the current process. UI-entered keys are masked and are not written to disk, logs, reports, or exports.

## Cloud Providers

Cloud mode sends relevant, selected document content to the configured provider. Provider switching is configuration-only.

### OpenAI

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=<OpenAI model name>
OPENAI_API_KEY=...
```

### DeepSeek

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=<DeepSeek model name>
DEEPSEEK_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com
```

### Gemini

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=<Gemini model name>
GEMINI_API_KEY=...
```

### OpenRouter

```dotenv
LLM_PROVIDER=openrouter
LLM_MODEL=<provider/model name>
OPENROUTER_API_KEY=...
LLM_BASE_URL=https://openrouter.ai/api/v1
```

`LLM_API_KEY` can be used as the common key setting; otherwise the application looks for the provider-specific variable.

## Local Ollama

Start Ollama separately and make sure the selected model is already installed locally:

```dotenv
EXECUTION_MODE=local_only
LOCAL_ONLY=true
LLM_PROVIDER=ollama
LLM_MODEL=<local model name>
LLM_BASE_URL=http://localhost:11434
```

Local Only mode rejects cloud providers and never falls back to one if the local service fails.

## Local OpenAI-Compatible Server

For vLLM or another OpenAI-compatible server running on the same machine:

```dotenv
EXECUTION_MODE=local_only
LOCAL_ONLY=true
LLM_PROVIDER=openai_compatible
LLM_MODEL=<served model name>
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=
```

In Local Only mode, compatible endpoints must resolve to a loopback hostname: `localhost`, `127.0.0.1`, or `::1`. A remote compatible endpoint is classified as cloud.

## Launch and Use

```powershell
python -m streamlit run app.py
```

Then:

1. Configure an execution mode, provider, and model in the sidebar.
2. Optionally describe an analysis focus in plain language.
3. Upload one PDF.
4. Analysis and verified PowerPoint generation start automatically. Wait for the export check to finish.
5. Review the Overview, Analysis, Charts, Extracted Data, Sources, Data Quality, and Technical Details tabs if needed.
6. Download the available deliverables. To inspect or override the page ranges, enable **Review page scope before analysis (optional)** before uploading and confirm the proposed scope.

Interactive charts expose the exact retained observations used, their source pages, selectable compatible chart types, and optional direct data labels.

## How Analysis Works

1. The parser verifies the PDF signature, readability, encryption state, size, and page count, then computes a SHA-256 content hash.
2. PyMuPDF extracts page text and layout. Table strategies use pdfplumber-derived structure, including aligned borderless layouts. Image-heavy or low-text pages are flagged for OCR.
3. A compact page map is routed to complete, evidence-bearing page ranges. Optional scope review lets the user confirm those ranges before deeper processing.
4. Discovery identifies the document's purpose and the information actually present; no document-type workflow is selected.
5. Extraction preserves original metric names, raw values, table coordinates, sections, and page evidence. Semantic mappings are applied only above a confidence threshold.
6. Financial observations, when present, receive typed units, cleaned numeric representations, period basis, audit/IFRS status, display forms, and validation status without discarding the raw source form.
7. The global document index groups comparable observations while guarding against mixed periods, incompatible units, different dimensions, and over-normalized metrics.
8. Candidate analyses are generated from available structures, scored for value, deduplicated, and converted into executable tasks only when their inputs exist.
9. Python tools compute changes, growth, ratios, shares, rankings, descriptive statistics, trends, correlations, and outliers. Arbitrary Python and unrestricted formulas are never executed.
10. Validators check extraction quality, semantic safety, consistency, coverage, calculation validity, evidence, and report language.
11. Evidence-grounded insights, report sections, and charts are generated from retained results. A recovery pass rechecks extraction when the narrative appears materially richer than the structured evidence.
12. The presentation planner references retained observation, insight, chart, and page IDs. Invalid model output is repaired or replaced with an evidence-only fallback plan.
13. Before PowerPoint export, deterministic QA checks claim direction, period comparability, sign semantics, currency and scale, company identity, chart-topic alignment, source coverage, cross-slide consistency, and layout risks. Safe issues are auto-repaired; unresolved critical issues block the export.

## Data Model

`Observation` is the central generic fact model. It preserves:

- original and optional canonical metric names;
- numeric, raw, normalized, and display values;
- raw and normalized units, scale, and currency;
- period label, period type/basis, dates, entity, and arbitrary dimensions;
- table/row/column structure, section context, and additive/subtractive row behavior;
- extraction, semantic, chartability, and validation status;
- one or more `SourceEvidence` records with one-based pages and optional text, table labels, and bounding boxes.

For financial evidence, `CanonicalFact` provides a strict raw/normalized/display separation together with audit status, IFRS or adjusted status, fact type, period semantics, confidence, and source excerpt. It supplements the generic observation model; it does not turn the pipeline into a fixed financial-report workflow.

Analysis results retain all input observation IDs and carry their evidence forward. Presentation slides and visual blocks likewise reference retained IDs instead of accepting free-floating numeric claims.

## Validation and Presentation QA

The current validation stack includes:

- missing, duplicate, low-confidence, conflicting, or suspiciously aligned extraction checks;
- conservative semantic normalization and compatible-series partitioning;
- unit, currency, scale, period, dimension, and minimum-sample gates;
- calculation checks for missing inputs, divide-by-zero, non-finite values, unsafe formulas, and invalid denominators;
- total/component consistency and evidence coverage checks;
- signed gain/loss, deficit/net-liability, profitability, balance-sheet, and mixed-period direction semantics;
- clause-level claim validation and targeted wording repair;
- company identity reconciliation and source-only company overview construction;
- chart/slide topic alignment based on positive semantic evidence;
- source-based amount/percentage column roles (never inferred from column position), with re-evaluation of stale roles and critical checks for unsupported monetary percentages or percentage magnitudes above 1,000;
- enriched single-metric analysis pages with a large editable chart, start/end KPIs, absolute change, eligible CAGR/percentage change, period changes, extrema, and source pages; rates require comparable periods and compatible units, while percentage metrics use percentage-point changes;
- final checks for sparse analysis content, chart-title/data mismatch, and repeated slide narratives/evidence;
- cross-slide checks for contradictory summaries, placeholders, float artifacts, working-capital wording, and inconsistent detail;
- layout QA for cramped multi-chart slides, unreadable scatter charts, long titles, zero-crossing labels, KPI spacing, and legend/unit collisions;
- a final PowerPoint preflight and a hard export blocker for unresolved critical contradictions.

Warnings and repairs are retained in the pipeline result and exposed in the Data Quality or Technical Details views. The system does not fabricate replacement facts when validation fails.

## Exports and Developer Artifacts

The Streamlit UI provides:

- `analysis_presentation.pptx` — editable widescreen presentation based on the bundled FOURIER template, subject to critical QA;
- `analysis_report.pdf` — formatted report;
- `analysis_report.md` — dynamic Markdown report;
- `extracted_observations.csv` — complete retained observation table with raw values and source pages.

The export service also supports a complete structured JSON serialization through `export_json(result)`. For QA and integration work, `generate_artifacts(result, output_dir)` writes:

- `extracted_facts.json`;
- `normalized_facts.json`;
- `slide_plan.json`;
- `qa_report.json`.

These JSON artifacts are programmatic outputs; only the QA report is conditionally offered in the UI when PowerPoint export is blocked.

## Privacy and Security

- Local Only is enforced by `LLMGateway` before document or derived content can be sent.
- There is no local-to-cloud fallback path.
- Routine logs avoid complete confidential document content and all secrets.
- Uploaded filenames are not trusted; internal identities derive from content hashes.
- PDF text is delimited as untrusted data in model prompts.
- Embedded scripts, macros, commands, and document instructions are never executed.
- Generated formulas use an allowlisted AST evaluator, not `eval()`.
- The local content-addressed cache lives in `.adaptive_document_cache/`; delete that directory to remove cached extraction data.

### Public Streamlit Deployment

For Streamlit Community Cloud, deploy `app.py` from the repository root and set this non-secret value in Advanced settings -> Secrets:

```toml
PUBLIC_DEPLOYMENT = "true"
```

Do not store a provider key in the hosted app's secrets. Public mode:

- exposes cloud providers only;
- ignores environment-backed API keys;
- requires each visitor to enter a key for the current session;
- disables Local Only and local providers;
- allocates a separate temporary extraction cache per Streamlit session and removes it on a best-effort basis when the session object is released.

The committed `.streamlit/config.toml` disables source-file watching and save-triggered
reruns. Streamlit's development watcher can evict process-wide Python modules while
another session is importing them, producing changing `KeyError` module names during
deployment. Production code updates therefore require a **process restart**, not just
a browser refresh or script rerun. Reboot the app after a deployment and confirm
**Source reload: disabled (restart required for code updates)** on the homepage.
The caption checks the effective runtime setting; an environment/CLI override that
re-enables watching produces a warning. Existing sessions and in-memory exports are
lost on reboot, so download completed work first. Widget reruns still work normally.
For local development only, opt in with
`python -m streamlit run app.py --server.fileWatcherType=auto`.
Only this non-secret config file is tracked; `.streamlit/secrets.toml` stays ignored.

Startup regressions cover the actual loaded config, disabled watcher registration,
concurrent cold imports in fresh processes, and Streamlit session/rerun rendering.
These tests do not simulate Community Cloud's deployment controller; verify the
runtime caption and renderer readiness online after restarting.

## Testing

The suite uses generated PDFs and `MockLLMClient`; normal test runs require no provider credentials.

```powershell
python -m pytest
```

Coverage includes PDF validation and routing, OCR detection, bordered and borderless tables, table reconstruction, numeric parsing, semantic conservatism, observation indexing, planners and tools, structured-output recovery, privacy and public deployment, financial fact normalization, period and sign semantics, claim repair, cross-slide consistency, chart selection, PowerPoint layout/preflight, PDF/PPTX exports, and end-to-end pipeline and presentation regressions.

### Evidence-driven presentation composition (P0)

- Planned chart pages now render hero/supporting chart roles, exact-value KPI cards, tables, commentary and a source footer. Hero and peer layouts use distinct proportions. Long commentary and table rows continue onto additional pages without repeating charts or discarding evidence.
- Stacked amount charts, 100% stacked charts and doughnut charts share the same validated matrix in the UI and editable PowerPoint renderer. Eligibility requires compatible periods, units, currencies and reporting scope, a complete category matrix, nonnegative values, and two to eight categories. Missing categories are never treated as zero.
- Percentage shares must reconcile to 100% within rounding tolerance. Amount-based share charts require explicitly linked, evidenced totals that reconcile to their components; amounts and raw source values remain unchanged. Automatic discovery exposes eligible reported percentage compositions and multi-period additive amount compositions; it does not guess denominators.
- Deck-wide semantic colors, typography and spacing are shared. Pre-export checks reject invalid compositions, contradictory chart/block titles, and actual overlapping or out-of-bounds compositor objects. Existing financial Critical QA remains in force.
- These are generic evidence/geometry rules, with no issuer, industry or prospectus-specific branches and no additional model calls. The local rendered QA gate below adds runtime checks.

### Theme-first analytical planning (P1)

- The existing presentation model call now receives a bounded evidence catalogue instead of a flat top-180 observation list. Whole series retain their periods, categories, units, entities, reporting basis, raw values and source pages. Retrieval uses the document purpose, prior report sections and insight labels, then balances metric coverage. Structural cross-page links suggest evidence to inspect; only the model decides whether it is analytically relevant.
- The model can return explicit themes (question, rationale, evidence boundary and caveats). Analysis pages link to a theme and state their analytical question and evidence-selection reason. Validators reject unknown/out-of-theme references, duplicate analysis evidence sets and incompatible like-for-like comparisons. Older cached plans without themes remain supported; the theme schema is requested for new model plans, not retroactively invented by Python.
- Eligible absolute change, percentage change, CAGR and YoY facts come from the existing Python calculation engine, with stable calculation IDs, exact input IDs, periods, units and source pages. Slide claims must link those IDs and all their inputs. Percentage-point movements stay distinct from percentage growth. Reported observations are never overwritten.
- Source snippets are retrieved near metric labels instead of only from page openings. Insight drivers require a verbatim quote and page from linked source evidence; otherwise the insight falls back to a factual result. Empty driver/implication/watch fields are acceptable. There is no fixed financial-theme checklist or automatic statement that management failed to disclose a driver.
- The normal presentation path still uses one gateway call, with the existing bounded repair attempt. Retrieval is local and capped (60 series, 240 observations, 12 source snippets, plus exact existing-chart data); omitted coverage is disclosed to the model. It is not exhaustive semantic search or proof of absence. Local Only policy and provider routing remain unchanged.
- New themed plans are not silently downgraded by the legacy deterministic repairer. If a model repair also fails, orchestration retains its explicitly labelled evidence-only fallback. Synthetic/mock tests validate contracts; live-model narrative quality across real documents still needs evaluation.

### Local rendered export gate (P2)

- Public PowerPoint export now runs financial/claim QA, builds the editable deck, renders every page locally, checks the results, and permits at most two position-only repair rounds. `export_pptx_with_report()` returns the final bytes plus a validation receipt; `export_pptx()` retains its bytes API. Existing `force=True` does not bypass rendered validation. The low-level builder is not a verified export API.
- Checks cover complete page count, valid PNGs, actual canvas/aspect ratio, blank pages and blank chart/table regions, missing native objects, out-of-bounds content, chart/table collisions, and source-footer collisions with inherited template text. Text-fit estimates and text-box intersections are warnings, not falsely precise glyph measurements. Existing financial, title/data, narrative and composition checks remain upstream.
- Repairs only move a small overflow into available space or reposition a source footer within the bottom quarter. They never shrink text, truncate evidence, remove slides, rewrite conclusions, or change values. A package-wide preservation digest allows only slide-position changes; chart XML, embedded workbooks, notes, text, units, relationships and other parts must stay unchanged. Unsafe/unresolved critical issues block export with a downloadable report.
- Rendering runs on the **same host as the app**, with no external rendering service. `PPTX_QA_BACKEND=auto` uses explicit Artifact configuration when present, otherwise an installed Linux LibreOffice backend. Streamlit Cloud installs LibreOffice Impress/Calc, fonts and `libseccomp2` from the root `packages.txt`. No desktop paths or private Codex package are needed there. Existing desktop installations can still use `PPTX_QA_NODE` and `PPTX_QA_ARTIFACT_MODULE` as absolute local paths. An explicit invalid configuration fails rather than silently switching engines. Never set executable/module paths from document content or an untrusted upload.
- The trusted helper disables Node network transports. The input guard rejects active content, external media/data relationships, DTDs and externally linked embedded workbooks. No model, provider SDK or cloud renderer is called. A private temporary workspace is deleted after success or failure. A 120-second limit applies per render pass; limits are 150 pages, 100 MB compressed input, 250 MB unpacked parts, 300 MB rendered outputs and 8 million pixels per page.
- The parent owns a dedicated render worker and terminates it only after an atomic, input-hash-bound completion receipt (or on timeout/failure). This avoids a Windows native-runtime teardown failure without accepting nonzero crash exits as success. Each PNG/layout must still independently pass validation.
- The UI shows the reason for blocked export and a downloadable visual report, including repair history and validation coverage. A one-entry **session-local** cache avoids rendering an unchanged deck again; deck, renderer/helper or policy changes invalidate it. After a font update, restart the UI or change `PPTX_QA_FONT_REVISION`.
- Offline OOXML tests explicitly opt into a rendering-boundary fake; they do not claim visual validation. To run the real local render/repair integration as well, configure the two paths and set `PPTX_QA_INTEGRATION=1` before running `pytest`. No external API key is needed.

### Streamlit Cloud rendering deployment

1. Deploy a revision containing `packages.txt` beside the root `app.py`. Community Cloud installs these operating-system dependencies during its build; `pip install` alone is insufficient. See [Streamlit's dependency documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).
2. Leave `PPTX_QA_BACKEND` unset/`auto`, or set it to `libreoffice`. Remove desktop-only `PPTX_QA_NODE`/`PPTX_QA_ARTIFACT_MODULE` secrets if using `auto`. `PPTX_QA_LIBREOFFICE` is optional; normal Linux installations are detected on PATH.

### Presentation narrative and design quality

Presentation planning now reviews metric-only headings, generic subtitles,
repeated findings, missing themes and repetitive single-chart composition.
The configured `LLMGateway` receives at most one additional editorial/semantic
repair request. Python never merges unrelated metrics to satisfy a chart or page
quota. If a safe plan still has quality findings, it remains available with a
review warning. Evidence-only recovery is labelled as a draft beside the download,
and its planning failure is visible in the same section. Data and rendered-layout
validation remain independent requirements and are not an aesthetic certification.

The `kpi_band` layout places selected exact values above one to three charts and
a grounded takeaway below them. Explicit themed layouts preserve the selected
chart type and no longer become automatic single-metric KPI pages. Older cached
single-metric plans retain their compatibility behavior.

The optional presentation artwork upload accepts a static PNG/JPEG (under 8 MB,
100 pixels minimum dimension, at most 16 megapixels) for the cover and overview.
The image remains an illustration, preserves its aspect ratio, and never enters
LLM requests or the document evidence model. Choose artwork appropriate to the
uploaded document. No photograph is fabricated or copied from another issuer.
Changing or removing the artwork invalidates the native export cache.

For a local visual regression preview with synthetic, clearly labelled data,
install development dependencies and configure the normal local renderer, then run
`python -m scripts.preview_presentation_layouts --output .tmp_ppt_review/preview --layout kpi_band`.
The output directory must be new. `--artwork /absolute/path/image.png` is optional.
Preview data must never be presented as an analysis of an uploaded document.
3. Reboot the app after deployment and confirm **PowerPoint export environment ready: LibreOfficeRenderer** before spending time on a document. The startup check renders a synthetic chart page, contains no uploaded data, and caches success per session/runtime. A warning does not disable analysis or other export formats, but clearly states that verified PPT export is unavailable.
4. For failures, download **complete export diagnostic report (qa_report.json)**. Its top-level `is_export_blocked` includes actual build/render failures, alongside separate `financial_qa`, `visual_qa` and `export_error` sections. Reporting never re-runs automatic repair on the live result. The dedicated `ppt_visual_qa.json` is also available for visual failures.

The Linux renderer uses an isolated user profile per conversion, suppresses macro execution, strips application secrets from the subprocess environment, rejects active/external PPT resources and enforces network restrictions with an inherited seccomp filter (only local Unix-domain sockets allowed). Failure to enforce isolation blocks export. The parent terminates its own process group on timeout; no unrelated Office processes are killed. This is not a general filesystem sandbox for arbitrary office uploads; the renderer receives the app-generated PPT package.

LibreOffice supplies actual PDF/PNG pixels and PDF text. Shape bounds/IDs come from OOXML, not a recovered LibreOffice object tree; the receipt explicitly discloses this. Checks include page count/aspect ratio, missing visible text, blank data regions, source/visual collisions and bounds. Group-transformed objects currently fail explicitly rather than certifying incorrect coordinates. The editable PPT is never replaced by the PDF or images. Existing position-only repairs and content-preservation checks remain active.

PDF reports use ReportLab independently of PowerPoint rendering. Noto CJK's PostScript-outline fonts work in LibreOffice but cannot be loaded by ReportLab's TrueType reader. The PDF exporter skips incompatible faces, checks required CJK glyphs, and uses the embeddable `fonts-wqy-zenhei` package on Linux. Font families have distinct registry names so English and Chinese sessions cannot reuse the wrong face. If no compatible installed font is available, standard CJK CID fonts are a last resort (not embedded; appearance depends on the viewer). A failure in PDF, Markdown or CSV disables only that download and does not hide verified PowerPoint downloads or QA diagnostics. Linux CI exercises actual production fonts on Python 3.11 and 3.12.

Run `PPTX_QA_LIBREOFFICE_INTEGRATION=1 python -m pytest -ra` on Linux with `packages.txt` dependencies installed. `.github/workflows/rendering-linux.yml` runs this deployment test (offline socket probe, actual chart rendering, and application-template export) alongside the full suite on pushes/PRs. Windows unit-test success alone does **not** certify Streamlit Cloud readiness; check the Linux job and the app's startup result after deployment.

This gate does not certify visual taste, exact glyph clipping, PowerPoint/Google Slides rendering parity, or live-model analytical quality. Those still require representative-document and human visual review. There is no document-type or issuer-specific repair rule.

## Latency and safe reuse

The `2026-09-22-evidence-scope-readability-v18` pipeline invalidates older extraction/export caches. Audit qualifications follow explicit source-column geometry, not calendar dates; unmarked columns remain `unknown`. Presentation review flags omitted newer evidence within the same entity/metric scope and asks the model to include material context or explain the exclusion in `coverage_notes`. Different period lengths and adjusted/reported definitions remain separate.

Company facts paginate with their evidence instead of disappearing into notes. Analytical commentary uses 18-point type with measured text capacity, and short KPI series can reflow into a complete same-page table. All capacity rules depend on content and available space, never an issuer, page number or fixed amount. Fresh model planning is still required to improve the wording/selection of a previously downloaded deck.

- Independent discovery chunks run with up to four concurrent cloud requests by default. `LLM_DISCOVERY_WORKERS=1` restores serial operation (allowed range: 1-4); existing deployment overrides remain effective, and you should reduce the value if your provider rate-limits concurrent requests. Loopback/local models and adapters that have not opted into thread-safe requests remain serial. All requests still go through `LLMGateway`. Chunk results are merged in source order, and a failed chunk cannot produce a successful partial profile.
- For thread-safe cloud clients, semantic resolution of more than 48 unique metrics uses batches of at most 48 under the same concurrency limit. Each batch sees the complete metric vocabulary and shared source context; no terms are dropped, missing mappings remain explicitly unresolved, and any failed batch fails the stage. Smaller vocabularies and local/stateful clients retain a single request. This reduces long serial output waits but repeats input context, so token cost can increase; it does not guarantee a particular end-to-end speedup or identical model wording.
- Table-header lookups reuse page word geometry, and completed pdfplumber page layout caches are released after copying raw cells and evidence. Extraction strategies and validation gates are unchanged.
- Hosted logs now include `stage_started` and `stage_finished` with duration and completion/failure status, without document text, API keys, or exception payloads. A process killed by the host may have a start event but no finish event. These timings diagnose bottlenecks; they do not provide background execution or reconnect recovery.
- Successful chunk discoveries are checkpointed in the existing document cache. Public hosting uses the existing per-session temporary directory, not a global cache. Exact chunk contents/pages, prompt, response schema, model, endpoint, privacy mode and temperature determine reuse. Failed/malformed responses are never cached; API keys are never written to this cache. Retrying can reuse completed chunks, while profile merging and later semantic/financial validations still run.
- Targeted analysis reuses observations already extracted from every selected table/text row. The former second pass only re-filtered those same rows and discarded duplicate IDs. Sparse-evidence recovery still re-extracts after reconstructing additional source tables.
- The UI keeps one native PPT build in session memory, keyed by the full evidence/plan/report state and template contents. Financial QA always runs, even on reuse. Rendered QA retains its separate content/renderer/policy validation cache, so a renderer change requires new rendering. Changed source values, units, labels, periods, narrative, template or plan invalidate native-build reuse. Generation code changes must bump `_build_cache_key`'s version. Only successfully verified builds are stored.
- PDF reports are optional: click **Generate PDF report** when needed. Unchanged PDF bytes are retained only in the current session. PPT no longer waits for automatic PDF generation. PDF errors remain isolated from other exports.
- The export panel reports financial QA, native build, rendered QA and total export times separately, along with cache reuse flags. Pipeline stage times remain under **Technical Details**. Compare first-run and repeated-run times separately; cache hits do not represent first-run speed.

For a reproducible offline microbenchmark, run `python -m scripts.benchmark_performance` after installing development dependencies. It compares identical synthetic discovery results with simulated 40 ms requests, plus cold/warm native template exports with a **stub renderer**. Add `--real-renderer` to measure actual rendering with the configured local backend; deployment CI runs this variant with LibreOffice. The output identifies the backend. This benchmark uses no user PDF or model API and is not an end-to-end prospectus speed claim. Actual Linux rendering and cached-byte equivalence are also tested in deployment CI.

## Known Limitations

Borderless-table extraction preserves multi-line header fragments and uses local PDF word coordinates to align sparse rows, including blank percentage cells beside reported amounts. A nearby `%` or an `except percentages` unit note is not evidence that every column is a percentage. Numeric candidates must form discrete cells with no trailing or interleaved prose: wrapped date sentences are retained in page text, not appended as table rows. Unresolved sparse data rows retain their raw values, are excluded from numeric observations, and block verified export with `ambiguous_table_alignment`; implausible percentages still block export. After updating from the older extractor, restart the app, review the analysis scope and run analysis again (table cache version `tables-v10`). Exporting an old in-memory result does not re-extract its tables.

Bare `share of` wording no longer forces an amount into percentage units. Monetary allocations retain their source currency, scale, raw values and evidence; intrinsic ratios and source-marked percentage cells/columns remain supported. Both table and UI result cache identities are updated so new analysis uses the corrected rules. Existing incorrectly typed observations still fail the financial export gate rather than receiving a guessed currency or scale at export time.

- Only one PDF is processed at a time, synchronously; there is no API server, database, authentication, queue, or multi-user workspace.
- The parser currently enforces a 200 MiB upload limit in code. Although `MAX_UPLOAD_MB` is present in `.env.example`, that environment value is not yet wired into the parser.
- Scope review is mandatory in the Streamlit workflow. The selected ranges improve cost and focus but can omit relevant material if the routing model misses it; the user should inspect the proposed ranges.
- OCR-required pages are detected through an adapter, but no OCR engine is bundled.
- Image/chart candidates are detected, but pixel extraction and provider-specific vision transport are not implemented. Such content is reported as unavailable rather than silently interpreted.
- PDF table extraction remains layout-dependent. Bordered and aligned borderless tables are supported, while ambiguous, highly graphical, and image-only tables can remain unresolved.
- Explicit metric-period-value text extraction is deliberately narrow; structured digital tables are the strongest input path.
- The generic pipeline supports varied data-rich documents, but the newest and deepest narrative/presentation QA is currently strongest for financial and offering-style material.
- Presentation rendering uses the bundled FOURIER template as its current visual base; it is not yet a user-selectable template system.
- Provider behavior is abstracted through LiteLLM, but live provider contract tests are intentionally excluded from the default offline suite.

## Future Roadmap

The highest-value next steps are:

- a bundled local OCR implementation;
- pixel-backed vision/chart extraction;
- broader targeted text-observation schemas;
- more generic non-financial claim and presentation semantics;
- user-selectable presentation templates;
- additional table-layout and live-provider contract fixtures;
- background execution and resumable processing for very large documents;
- an API surface and structured JSON download in the UI.

The existing package boundaries are intended to support later multi-PDF comparison, CSV/Excel/DOCX/PPTX input, persistence, batch analysis, and shared workspaces without rewriting the core evidence model.

## Engineering Specification

The authoritative specification is [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md). Repository-specific working instructions are in [AGENTS.md](AGENTS.md).
