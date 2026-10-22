"""One output-language decision shared by authors, localization and export."""
from dataclasses import dataclass


def language_key(value: str) -> str:
    value = value.strip().casefold()
    aliases = {
        'en': 'english', 'en-us': 'english', 'en-gb': 'english', '英文': 'english',
        'zh': 'chinese', 'zh-cn': 'chinese', '中文': 'chinese',
        '简体中文': 'chinese', 'simplified chinese': 'chinese',
    }
    return aliases.get(value, value)


@dataclass(frozen=True)
class PresentationLanguage:
    language: str
    origin: str
    requirement_ids: tuple[str, ...] = ()


def resolve_language(profile) -> PresentationLanguage:
    from .report_language import original_language
    requirements = profile.report_requirements
    requested = [r for r in requirements.items if r.kind == 'output_language'
                 and r.language_scope in {'body', 'all'}] if requirements else []
    if any(r.resolution != 'resolved' or not r.language.strip() for r in requested):
        raise ValueError('Resolve the ambiguous output-language requirement before export')
    source = (profile.language or '').strip()
    targets = {language_key(source if original_language(r.language) else r.language)
               for r in requested}
    if len(targets) > 1:
        raise ValueError('Conflicting output-language requirements')
    if requested:
        target = next(iter(targets))
        if not target or target in {'unknown', 'undetermined', 'mixed', 'multilingual'}:
            raise ValueError('The requested source language has not been identified')
        return PresentationLanguage(target, 'user', tuple(r.id for r in requested))
    # No guessed language for legacy records whose discovery did not identify it.
    if language_key(source) in {'unknown', 'undetermined', 'mixed', 'multilingual'}:
        raise ValueError('Source language is ambiguous; specify one output language')
    return PresentationLanguage(language_key(source), 'source' if source else 'unresolved')


def language_messages(profile):
    policy = resolve_language(profile)
    if not policy.language:
        return []
    return [{'role': 'user', 'content':
        f'Use {policy.language} consistently for all audience-facing titles, labels and prose. '
        f'This output language comes from the {policy.origin} language policy. '
        'Keep literal evidence quotes, source-table cells, proper names, identifiers, '
        'numeric values, currency/scale meanings and periods unchanged. '
        'The language of page-count instructions or internal evidence notes does not change this policy.'}]


def require_consistent_language(presentation, result):
    """Validate the actual saved display strings, never a planned language alone."""
    from .display_copy_tokens import language_copy_key
    from .report_language import audience_copy
    policy = resolve_language(result.profile)
    if not policy.language:
        return
    requirements = result.profile.report_requirements
    if (not requirements or language_key(requirements.translation_language) != policy.language
            or not requirements.copy_translations):
        raise ValueError(f'PowerPoint language verification required for {policy.language}; '
                         'prepare and independently review the complete display copy before export')
    checked = {language_copy_key(v) for v in [*requirements.copy_translations.values(),
                                       *requirements.summary_copy_translations.values()]}
    from .summary_export import verify_summary_export
    verify_summary_export(presentation, result)
    # Native pagination may subdivide a checked introduction item. The source
    # binding verifier above reconstructs it exactly before coverage accepts it.
    for slide in presentation.slides:
        for shape in slide.shapes:
            properties = shape.element.xpath('.//p:cNvPr')
            if (shape.has_text_frame and properties
                    and properties[0].get('descr', '').startswith('ADA_SUMMARY_ITEM_V2:')):
                import json
                binding = json.loads(properties[0].get('descr').split(':', 1)[1])
                if f"{binding['page_id']}:{binding['item_index']}" in requirements.summary_copy_translations:
                    checked.add(language_copy_key(shape.text))
    missing = [v for v in audience_copy(presentation) if language_copy_key(v) not in checked]
    if missing:
        raise ValueError(f'PowerPoint language coverage incomplete for {policy.language}: '
                         f'{len(missing)} unreviewed display strings: {missing[:5]}')
