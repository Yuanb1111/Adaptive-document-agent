# Adaptive Document Intelligence Agent

Analyse one PDF in Streamlit and turn its findings into a report and an editable PowerPoint. The agent selects analyses from the evidence it finds. Each chart links back to its underlying observations and PDF pages.

## Quick start

Use Python 3.11 or later. From the repository root, run the following in PowerShell. On macOS or Linux, activate the environment with `source .venv/bin/activate` on the second line.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

1. Choose a model provider and model in the sidebar. Cloud providers require an API key.
2. Upload a PDF to start analysis. To request a focus, output language or slide limit, fill in **Analysis and PPT requirements (optional)** before uploading. You can also review the proposed page ranges.
3. Inspect findings and their source pages, then download the editable PowerPoint, Markdown or PDF report, observation CSV, or full analysis JSON. Verified PowerPoint export requires a local slide renderer such as LibreOffice Impress. **Application status** shows renderer availability.

[Beginner guide (中文 PDF)](static/Adaptive_Document_Agent_Beginner_Guide_Public_2026-09-30.pdf) · [Report customization](docs/REPORT_CUSTOMIZATION.md)

## Models and privacy

Use the sidebar for a single session, or copy [.env.example](.env.example) to `.env` for local defaults. Set `LLM_PROVIDER` and `LLM_MODEL` together. When switching providers, clear the example’s DeepSeek `LLM_BASE_URL` or replace it with the intended endpoint.

| Mode | Provider setting | Connection |
| --- | --- | --- |
| Cloud | `openai`, `deepseek`, `gemini`, `openrouter` | Set `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, or `OPENROUTER_API_KEY` for the chosen provider. It receives the selected document content. |
| Local Only | `ollama` | Start Ollama with an installed model and set `LLM_BASE_URL=http://localhost:11434`. |
| Local Only | `openai_compatible` | Start a local server such as vLLM and set its endpoint, e.g. `LLM_BASE_URL=http://localhost:8000/v1`. |

Click the lightning bolt beside **Model** to turn Fast on for supported OpenAI models. Click it again to use your project's default speed. Set `OPENAI_FAST_MODE=true` to start with Fast enabled. Fast pricing varies by model. [OpenAI Fast pricing](https://openai.com/api-fast-mode/)

Set `LOCAL_ONLY=true` for either local configuration. Model requests are restricted to loopback endpoints, and a local failure stops the run. Keep API keys out of Git. For a public Streamlit deployment, set `PUBLIC_DEPLOYMENT=true` so each visitor supplies their own key. [Deployment details](docs/FOURIER_STREAMLIT_UI.md#deployment)

## How analysis works

The parser extracts page text and tables into observations that retain raw values, units, periods and source locations. The model uses the shared `LLMGateway` to select and explain useful analyses. Python performs the calculations and checks units, periods and evidence. Before export, PowerPoint checks the slide contents and renders each page to check layout. [Architecture and data model](docs/MASTER_PROMPT.md)

Digital text and tables provide the best coverage. The app flags pages that need OCR. Bundled OCR and extraction of values from chart images are planned extensions. Ambiguous table alignment can block verified export.

## Development

The Python suite uses generated PDFs and mock model responses. Run it without provider credentials. The browser component tests use Node.js 22.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
node --test tests/test_completion_notification_frontend.mjs tests/test_progress_timer_frontend.mjs
```

[Evaluation protocol](docs/EVALUATION_PROTOCOL.md) · [Engineering notes](docs/) · [Contributor instructions](AGENTS.md)
