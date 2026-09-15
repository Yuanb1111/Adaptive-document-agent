# Adaptive Document Intelligence Agent

An evidence-grounded, provider-independent application for analysing arbitrary data-rich PDFs. The system inspects the actual document before deciding which analyses are useful. It does not ask the user to choose a hard-coded document type and does not use LLMs for arithmetic.

## Project Overview

The application accepts one PDF, preserves page-level text/table/image provenance, discovers the document's purpose and available information, builds a global observation model, proposes and scores possible analyses, executes supported calculations in Python, validates results, and renders a dynamic report.

Its central responsibility split is:

- LLM: semantic discovery, metric interpretation, analysis value judgment, insight language.
- Python: parsing, normalisation, arithmetic, statistics, ranking, unit checks, safe formulas, consistency checks.
- Validators: decide whether extracted data and results are trustworthy enough to show.

PDF text is always treated as untrusted source material. Instructions embedded in a PDF are never executed or followed.

## Architecture

```text
PDF -> page parser -> text/tables/images -> document discovery
    -> semantic resolution -> global observation index
    -> candidate generation -> value scoring -> validated plan
    -> targeted observations -> deterministic tools -> validators
    -> grounded insights -> dynamic report/chart plans -> Streamlit UI
```

Provider calls use this boundary:

```text
Agent module -> LLMGateway -> LLMClient -> LiteLLMProvider -> configured provider
```

No analysis module imports a provider-specific SDK or LiteLLM.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For development and tests:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Configuration

Copy `.env.example` to `.env` and fill only the values needed for the selected provider. Never commit `.env` or API keys.

Common settings:

```dotenv
EXECUTION_MODE=auto
LOCAL_ONLY=false
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
LLM_API_KEY=
LLM_BASE_URL=http://localhost:11434
LLM_TIMEOUT_SECONDS=120
LLM_TEMPERATURE=0
```

Optional stage-specific model routes are supported with `LLM_DISCOVERY_MODEL`, `LLM_SEMANTIC_MODEL`, `LLM_EXTRACTION_MODEL`, `LLM_PLANNER_MODEL`, `LLM_VISION_MODEL`, `LLM_INSIGHT_MODEL`, and `LLM_REPORT_MODEL`.

The Streamlit sidebar can also accept a key for the current process. UI-entered keys are masked, not written to disk, and not logged.

## Cloud Providers

Cloud mode sends relevant, targeted document content to the configured provider. The UI shows this explicitly.

### OpenAI

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.6-terra
OPENAI_API_KEY=...
```

### DeepSeek

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
DEEPSEEK_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com
```

### Gemini

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
```

### OpenRouter

```dotenv
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4.1-mini
OPENROUTER_API_KEY=...
LLM_BASE_URL=https://openrouter.ai/api/v1
```

Provider switching is configuration-only; agent business logic does not change.

## Local Ollama

Start Ollama and ensure the configured model is already available locally:

```dotenv
EXECUTION_MODE=local_only
LOCAL_ONLY=true
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
LLM_BASE_URL=http://localhost:11434
```

Then launch the application. Local Only mode rejects a cloud provider and never silently falls back to one.

## Local OpenAI-Compatible Server

For vLLM or another local OpenAI-compatible endpoint:

```dotenv
EXECUTION_MODE=local_only
LOCAL_ONLY=true
LLM_PROVIDER=openai_compatible
LLM_MODEL=your-local-model
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=
```

Local Only accepts only loopback hosts (`localhost`, `127.0.0.1`, or `::1`) for compatible endpoints. A remote URL is treated as cloud even if the provider name is `openai_compatible`.

## Privacy

- No document content is persisted outside the local content-addressed cache.
- API keys are represented as secret values and never written or intentionally logged.
- Local Only is enforced when constructing the gateway, before document content can be sent.
- There is no local-to-cloud fallback path.
- Full confidential document text is not included in routine logs.
- Uploaded filenames are not trusted; internal IDs derive from SHA-256 content hashes.

Delete `.adaptive_document_cache/` if local extraction caching is not desired between runs.

## How Analysis Works

1. Validate PDF signature, readability, encryption state, size, and page count.
2. Extract page text/layout with PyMuPDF, bordered and aligned-borderless tables with pdfplumber-backed strategies, and image candidates.
3. Flag pages that likely require OCR instead of silently ignoring them.
4. Build a compact page map for large documents, let the configured LLM route the user's focus to complete relevant page ranges, and require the user to review and confirm that scope before deep processing.
5. Discover purpose, sections, metrics, dimensions, entities, periods, units, and limitations.
6. Preserve original metric names while applying only high-confidence semantic mappings.
7. Build and query a global observation index.
8. Generate analyses only when required structures exist, then score and bound the list.
9. Execute calculations through the deterministic tool registry or safe AST formula engine.
10. Validate extraction, semantics, calculations, mathematical consistency, evidence, and report language.
11. Generate evidence-backed insights and a document-specific report structure.
12. Plan charts only where they answer a useful analytical question, show direct value labels and provenance, and offer compatible line, bar, area, pie, scatter, horizontal-bar, and data-table views.

## Data Model

`Observation` is the central generic fact model. It stores the original and optional canonical metric, numeric and raw values, unit/scale/currency, period, entity, arbitrary dimensions, confidence, and one or more `SourceEvidence` records.

Every source includes a one-based page number, extraction method, confidence, and optional text, table ID, row/column labels, and bounding box. Results list all input observation IDs and carry their evidence forward.

## Validation

The initial implementation includes:

- extraction checks for missing, low-confidence, duplicate, and conflicting observations;
- semantic checks for risky merges of differently qualified metrics;
- unit/currency compatibility and sample-size gates before execution;
- calculation checks for failures, non-finite values, divide-by-zero, and unsafe formulas;
- generic total-versus-component consistency checks;
- evidence requirements for numeric results;
- report checks for unsupported causal language.

A failed or uncertain stage produces a visible warning or excludes the result. It never fabricates a replacement value.

## Launch

```powershell
python -m streamlit run app.py
```

Configure a provider and model in the sidebar. Optionally describe an analysis focus in plain language, upload one PDF, select **Review analysis scope**, inspect the proposed page ranges, and then select **Analyse selected pages** after confirmation. Leaving the focus blank uses automatic discovery. The results area contains Overview, Analysis, Charts, Extracted Data, Sources, Data Quality, and Technical Details tabs, followed by Markdown, JSON, and CSV downloads.

## Testing

Tests use generated PDFs and `MockLLMClient`; no real API key is required.

```powershell
python -m pytest
```

Coverage includes provider/privacy rules, structured-output repair, PDF validation, OCR detection, table reconstruction, semantic conservatism, observation indexing, candidate/planner gates, numeric parsing, deterministic tools, safe formulas, validators, report/chart planning, exports, and an end-to-end synthetic PDF pipeline.

## Known Limitations

- OCR has an adapter and page detection but no bundled OCR engine.
- Vision/chart candidates are detected, but pixel extraction and provider-specific image transport are not yet implemented; unsupported vision is reported explicitly.
- PDF tables vary widely; bordered and aligned-borderless layouts are supported, while ambiguous or image-only tables remain explicitly unresolved.
- Text observation extraction recognises a narrow explicit metric-period-value form; rich table extraction is the stronger first-version path.
- Consistency checks currently implement generic total/component relationships; LLM-discovered formula relationships can be expanded later.
- A live provider integration test is intentionally absent from the default suite.
- The prototype processes one PDF synchronously and has no authentication, database, or background queue.

## Future Roadmap

Recommended next steps are a local OCR implementation, pixel-backed vision adapter, broader targeted text observation schemas, formula-relationship discovery, more table-layout fixtures, provider contract tests behind opt-in credentials, and background execution for very large documents. The package boundaries also allow future multi-PDF comparison, CSV/Excel/DOCX/PPTX ingestion, API endpoints, persistence, and batch analysis without rewriting the core pipeline.

## Engineering Specification

The authoritative specification is [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md). Repository-specific instructions are in [AGENTS.md](AGENTS.md).
