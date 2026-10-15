"""A session-owned analysis worker. No Streamlit calls run on this thread."""

import logging
from threading import RLock, Thread
from uuid import uuid4

from adaptive_document_agent.services.pipeline_completion import is_complete
from .processing_progress import ProcessingProgress

_LOGGER = logging.getLogger('adaptive_document_agent.timing.analysis_attempt')


def new_attempt():
    progress = ProcessingProgress(None)
    progress.update('Starting analysis')
    return {'id': uuid4().hex, 'state': 'running', 'stage': 'Starting analysis',
            'lock': RLock(), 'progress': progress, 'published': False}


def snapshot(attempt):
    with attempt['lock']:
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
        with attempt['lock']:
            attempt['stage'] = stage
            attempt['progress'].update(stage)
        _LOGGER.info('Analysis attempt %s stage: %s', attempt['id'], stage)

    try:
        gateway = gateway_factory()
        gateway.usage.extend(scope_usage)
        result = orchestrator_factory(gateway, cache=cache).analyse_pdf(
            raw_pdf, progress=update, analysis_focus=analysis_focus, scope=scope,
            **({'resume': resume} if resume is not None else {}),
            **({'presentation_budget': presentation_budget} if presentation_budget is not None else {}))
        with attempt['lock']:
            attempt['result'] = result
            if is_complete(result):
                attempt['progress'].update('Complete')
                attempt['state'] = 'complete'
            else:
                attempt['failure'] = {
                    'scope_key': scope_key, 'scope': scope,
                    'message': 'Analysis is incomplete. Retry to continue from retained evidence; see the source and stage diagnostics.',
                    'usage': list(gateway.usage)}
                attempt['progress'].fail('Analysis incomplete: ' + attempt['stage'])
                attempt['state'] = 'partial'
    except BaseException as exc:
        interrupted = not isinstance(exc, Exception)
        with attempt['lock']:
            attempt['failure'] = {
                'scope_key': scope_key, 'scope': scope,
                'message': ('Analysis was interrupted. Retry to reuse successful cached work.' if interrupted
                            else f'Analysis could not be completed: {exc}'),
                'usage': list(getattr(gateway, 'usage', []))}
            attempt['progress'].fail('Analysis stopped: ' + attempt['stage'])
            attempt['state'] = 'interrupted' if interrupted else 'failed'
    _LOGGER.info('Analysis attempt %s %s at %s', attempt['id'], attempt['state'], attempt['stage'])
