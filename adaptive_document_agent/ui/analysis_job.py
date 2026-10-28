"""A session-owned analysis worker. No Streamlit calls run on this thread."""

import logging
from threading import RLock, Thread
from uuid import uuid4

from adaptive_document_agent.services.pipeline_completion import is_complete
from .processing_progress import ProcessingProgress
from adaptive_document_agent.services.analysis_deadline import AnalysisDeadline, AnalysisTimeLimitExceeded

_LOGGER = logging.getLogger('adaptive_document_agent.timing.analysis_attempt')


def new_attempt():
    progress = ProcessingProgress(None)
    progress.update('Starting analysis')
    return {'id': uuid4().hex, 'state': 'running', 'stage': 'Starting analysis',
            'lock': RLock(), 'progress': progress, 'published': False,
            'deadline': AnalysisDeadline(started_at=progress.started_at)}


def snapshot(attempt):
    with attempt['lock']:
        if attempt['state'] == 'running' and not attempt['deadline'].remaining:
            attempt['progress'].fail('15-minute limit reached; stopping, no new model requests')
            attempt['progress'].stopped_at = attempt['deadline'].expires_at
        return {**attempt, 'progress': attempt['progress'].snapshot()}


def start_worker(target):
    worker = Thread(target=target, name='document-analysis', daemon=True)
    worker.start()
    return worker


def execute(attempt, *, gateway_factory, orchestrator_factory, raw_pdf, scope_key,
            scope, analysis_focus, cache, resume, presentation_budget, scope_usage):
    """Publish terminal state last, after result/usage metadata are available."""
    gateway = None
    _LOGGER.info('Analysis attempt %s started', attempt['id'])

    def update(stage):
        attempt['deadline'].check()
        with attempt['lock']:
            attempt['stage'] = stage
            attempt['progress'].update(stage)
        _LOGGER.info('Analysis attempt %s stage: %s', attempt['id'], stage)

    try:
        gateway = gateway_factory()
        gateway.run_deadline = attempt['deadline']
        attempt['deadline'].check()
        gateway.usage.extend(scope_usage)
        result = orchestrator_factory(gateway, cache=cache).analyse_pdf(
            raw_pdf, progress=update, analysis_focus=analysis_focus, scope=scope,
            **({'resume': resume} if resume is not None else {}),
            **({'presentation_budget': presentation_budget} if presentation_budget is not None else {}))
        if not attempt['deadline'].remaining and result.failed_stage != 'analysis_time_limit':
            from adaptive_document_agent.agent.analysis_time_limit import retain_timed_out_result
            result = retain_timed_out_result({'result': result, 'stage': attempt['stage'],
                'reporting_ready': is_complete(result) or result.retry_from == 'reporting'},
                gateway, attempt['deadline'])
        with attempt['lock']:
            attempt['result'] = result
            if is_complete(result):
                attempt['progress'].update('Complete')
                attempt['state'] = 'complete'
            else:
                attempt['failure'] = {
                    'scope_key': scope_key, 'scope': scope,
                    'message': (str(AnalysisTimeLimitExceeded()) if result.failed_stage == 'analysis_time_limit' else
                        'Analysis is incomplete. Retry to continue from retained evidence; see the source and stage diagnostics.'),
                    'usage': list(gateway.usage)}
                attempt['progress'].fail('15-minute analysis limit reached' if result.failed_stage == 'analysis_time_limit'
                                         else 'Analysis incomplete: ' + attempt['stage'])
                attempt['state'] = 'partial'
    except BaseException as exc:
        interrupted = not isinstance(exc, Exception)
        with attempt['lock']:
            attempt['failure'] = {
                'scope_key': scope_key, 'scope': scope,
                'message': ('Analysis was interrupted. Retry to reuse successful cached work.' if interrupted
                            else f'Analysis could not be completed: {exc}'),
                'usage': list(getattr(gateway, 'usage', []))}
            diagnostics = getattr(exc, 'diagnostics', None)
            if isinstance(diagnostics, dict):
                attempt['failure']['diagnostics'] = diagnostics
            attempt['progress'].fail('Analysis stopped: ' + attempt['stage'])
            attempt['state'] = 'interrupted' if interrupted else 'failed'
    _LOGGER.info('Analysis attempt %s %s at %s', attempt['id'], attempt['state'], attempt['stage'])
