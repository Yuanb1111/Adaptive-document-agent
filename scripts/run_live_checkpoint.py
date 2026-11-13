"""Run or resume analysis with a real LLMGateway and the matching original PDF.

Credentials are read from the chosen environment file and never printed or saved.
Every invocation has one shared configurable deadline; no provider fallback.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import SecretStr

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.services.analysis_deadline import AnalysisDeadline
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.routing import create_llm_client
from adaptive_document_agent.services.pipeline_completion import is_complete


def export_verified(result, source_pdf, args):
    """Use the application's real export gates and retain renderings for review."""
    from adaptive_document_agent.services.export import export_pptx_with_report
    from adaptive_document_agent.services.presentation_rendering import ArtifactRenderer, configured_renderer
    base = (ArtifactRenderer(str(args.render_node), str(args.render_module))
            if args.render_node and args.render_module else configured_renderer())

    class CaptureRenderer:
        identity = base.identity
        coverage = getattr(base, 'coverage', ())
        calls = 0

        def render(self, payload, directory):
            pages = base.render(payload, directory)
            self.calls += 1
            destination = args.output / 'rendered' / f'pass-{self.calls}'
            destination.mkdir(parents=True, exist_ok=False)
            for number, page in enumerate(pages, 1):
                (destination / f'slide-{number:03}.png').write_bytes(page.png)
                (destination / f'slide-{number:03}.json').write_text(
                    json.dumps(page.layout, ensure_ascii=False, indent=2), encoding='utf-8')
            return pages

    verified = export_pptx_with_report(result, source_pdf=source_pdf, renderer=CaptureRenderer(),
                                      progress=lambda message: print(message, flush=True))
    target = args.output / 'analysis_presentation.pptx'
    target.write_bytes(verified.payload)
    (args.output / 'pptx_qa.json').write_text(json.dumps(verified.report.to_dict(),
        ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(pptx=str(target.resolve()), visual_status=verified.report.status,
                slide_count=verified.report.slide_count,
                output_sha256=hashlib.sha256(verified.payload).hexdigest())


def settings_for(path: Path, provider: str, model: str) -> LLMSettings:
    values = {**dotenv_values(path), **os.environ}
    configured = values.get('LLM_PROVIDER', 'deepseek').lower()
    selected = ProviderName(provider)
    if selected == ProviderName.MOCK:
        raise ValueError('Live checkpoint execution forbids the mock provider')
    matching = configured == provider
    key = ((values.get('LLM_API_KEY') if matching else None)
           or values.get(provider.upper() + '_API_KEY'))
    base_url = (values.get(provider.upper() + '_BASE_URL')
                or (values.get('LLM_BASE_URL') if matching else None))
    mode = ('local_only' if values.get('LOCAL_ONLY', 'false').lower() == 'true'
            else values.get('EXECUTION_MODE', 'auto').lower())
    if not key and selected not in {ProviderName.OLLAMA, ProviderName.OPENAI_COMPATIBLE}:
        raise ValueError('No credential configured for the selected provider')
    return LLMSettings(provider=selected, model=model, api_key=SecretStr(key) if key else None,
        base_url=base_url, privacy_mode=PrivacyMode(mode),
        timeout_seconds=float(values.get('LLM_TIMEOUT_SECONDS', '120')),
        discovery_workers=int(values.get('LLM_DISCOVERY_WORKERS', '4')),
        brief_initial_findings=int(values.get('LLM_BRIEF_INITIAL_FINDINGS', '7')),
        simple_task_reasoning=values.get('LLM_SIMPLE_TASK_REASONING', 'reduced'),
        presentation_strategy='retained_analysis')


def run(args) -> dict:
    source = None
    if not args.fresh:
        if args.checkpoint is None:
            raise ValueError('--checkpoint is required for a reporting continuation')
        source = PipelineResult.model_validate_json(args.checkpoint.read_bytes())
    raw_pdf = args.pdf.read_bytes()
    source_hash = hashlib.sha256(raw_pdf).hexdigest()
    if source is not None and source_hash != source.document.sha256:
        raise ValueError('Original PDF does not match the saved checkpoint')
    settings = settings_for(args.env, args.provider, args.model)
    overrides = {key: getattr(args, argument) for key, argument in (
        ('discovery_workers', 'workers'), ('brief_initial_findings', 'brief_findings'))
        if getattr(args, argument, None) is not None}
    if overrides:
        settings = settings.model_copy(update=overrides)
        settings = LLMSettings.model_validate(settings.model_dump())
    args.output.mkdir(parents=True, exist_ok=False)

    class DiagnosticGateway(LLMGateway):
        def generate_structured(self, messages, response_model, **kwargs):
            try:
                value = super().generate_structured(messages, response_model, **kwargs)
            except Exception as exc:
                chain, current = [], exc
                while current is not None:
                    entry = dict(type=type(current).__name__, message=str(current))
                    response = getattr(current, 'response', None)
                    if response is not None:
                        entry['response'] = response.text
                    chain.append(entry)
                    current = current.__cause__
                target = args.output / f'structured-error-{len(self.usage):03}-{uuid4().hex[:8]}.json'
                target.write_text(json.dumps(dict(operation=response_model.__name__, errors=chain),
                    ensure_ascii=False, indent=2), encoding='utf-8')
                raise
            finally:
                save_summary()
            if response_model.__name__ in {'RetainedPageRevisions','PriorityPagePatch'}:
                prefix='copy-revisions' if response_model.__name__=='RetainedPageRevisions' else 'priority-patch'
                (args.output / f'{prefix}-{len(self.usage):03}-{uuid4().hex[:8]}.json').write_text(
                    value.model_dump_json(indent=2), encoding='utf-8')
            return value

    gateway = DiagnosticGateway(create_llm_client(settings), settings, cache_enabled=False)
    started = perf_counter()
    gateway.run_deadline = AnalysisDeadline(limit_seconds=args.analysis_timeout_seconds)
    summary = dict(started_at=datetime.now(timezone.utc).isoformat(),
        provider=settings.provider.value, model=settings.model, original_sha256=source_hash,
        checkpoint=None if args.fresh else str(args.checkpoint), resume_supplied=source is not None,
        request_cache_enabled=False,
        cloud_request_limit=gateway.discovery_workers,
        initial_brief_capacity=settings.brief_initial_findings,
        mode='live_fresh_pdf' if args.fresh else 'live_reporting_resume',
        limit_seconds=gateway.run_deadline.limit_seconds,
        limit_includes_pptx_qa=bool(args.export_pptx),
        status='running', complete=False)
    summary_lock = Lock()

    def save_summary():
        with summary_lock:
            summary['elapsed_seconds'] = round(perf_counter() - started, 3)
            summary['llm_calls'] = len(gateway.usage)
            (args.output / 'run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            (args.output / 'llm_usage.json').write_text(json.dumps(gateway.usage, ensure_ascii=False, indent=2), encoding='utf-8')

    def progress(stage):
        event = dict(elapsed_seconds=round(perf_counter() - started, 3), stage=stage,
                     llm_calls=len(gateway.usage))
        print(json.dumps(event, ensure_ascii=False), flush=True)
        with (args.output / 'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        summary['stage'] = stage
        save_summary()

    try:
        if not args.skip_probe:
            progress('Checking the configured live model')
            gateway.generate_text([dict(role='user', content='Reply OK only.')], stage='diagnostic', max_tokens=64)
        progress('Analysing the original PDF from ingestion' if args.fresh
                 else 'Resuming the saved reporting checkpoint')
        from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
        result = DocumentOrchestrator(gateway).analyse_pdf(raw_pdf,
            resume=None if args.fresh else source, progress=progress)
        ready = is_complete(result)
        summary.update(status=result.pipeline_state, pipeline_complete=ready,
            complete=ready and not args.export_pptx,
            failed_stage=result.failed_stage, failure_details=result.failure_details,
            timings_ms=result.timings_ms, stage_details_ms=result.stage_details_ms)
        (args.output / 'analysis_data.json').write_text(result.model_dump_json(indent=2), encoding='utf-8')
        (args.output / 'analysis_report.md').write_text(result.report_markdown, encoding='utf-8')
        if args.export_pptx and ready:
            gateway.run_deadline.check()
            progress('Exporting the complete report through native and rendered PowerPoint QA')
            summary.update(export_verified(result, raw_pdf, args))
            gateway.run_deadline.check()
            summary.update(complete=True, status='complete')
            (args.output / 'analysis_data.json').write_text(result.model_dump_json(indent=2), encoding='utf-8')
    except Exception as exc:
        summary.update(status='failed', complete=False, error_type=type(exc).__name__, error=str(exc))
        if summary.get('pipeline_complete') and args.export_pptx:
            summary['failed_stage'] = 'pptx_export'
        reports = {}
        for name in ('financial_report', 'preflight_report', 'report'):
            value = getattr(exc, name, None)
            if value is not None:
                reports[name] = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value.to_dict()
        if reports:
            (args.output / 'failure_qa.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        save_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--export-pptx', action='store_true')
    parser.add_argument('--fresh', action='store_true', help='Read only the original PDF; ignore checkpoints and start from ingestion without any saved analysis')
    parser.add_argument('--analysis-timeout-seconds', type=float, help='One shared attempt budget, 60–7200 seconds; default ANALYSIS_TIMEOUT_SECONDS or 900')
    parser.add_argument('--workers', type=int, choices=range(1, 9), help='Shared cloud request limit (1–8); local and stateful clients remain serial')
    parser.add_argument('--brief-findings', type=int, choices=range(3, 8), help='Initial material brief finding capacity (3–7), preserving reserved supplementary capacity')
    parser.add_argument('--skip-probe', action='store_true', help='Reuse an already verified connection; all analysis requests remain real')
    parser.add_argument('--render-node', type=Path)
    parser.add_argument('--render-module', type=Path)
    outcome = run(parser.parse_args())
    raise SystemExit(0 if outcome['complete'] else 1)
