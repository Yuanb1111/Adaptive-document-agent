"""Bind source-authored analysis pages to their calculation and companion rows."""
import re

from pydantic import BaseModel, ConfigDict, Field,model_serializer,model_validator
from adaptive_document_agent.models.executive_brief import BriefQuote

from adaptive_document_agent.services.presentation_evidence import (
    ambiguous_source_table_ids, observation_uses_ambiguous_table)
from .audit_source_layout import audit_source_page
from .reported_source_context import QualifiedSourceCopy,qualified_source_statement


STANDARD_AUTHORED_COPY_CHARACTERS = 2000
CONTINUED_AUTHORED_COPY_CHARACTERS = 3000
MAX_RETAINED_FINDINGS = 8


def authored_copy_limit(requirements):
    """Reserve a possible continuation only under an explicit larger analysis budget."""
    from adaptive_document_agent.services.slide_budgets import resolved_limits

    analysis = resolved_limits(requirements, section='analysis')
    report = resolved_limits(requirements)
    # This permits drafting. The export measures and enforces actual counts
    # including introduction, other report sections and every continuation.
    if analysis and min([*analysis, *report]) > MAX_RETAINED_FINDINGS:
        return CONTINUED_AUTHORED_COPY_CHARACTERS
    return STANDARD_AUTHORED_COPY_CHARACTERS


SOURCE_SHARE_RULES = (
    'For a material share of a population, check this item’s own literal passage. If it states '
    'that a majority was affected, or explicitly gives a share clearly above half for that same '
    'population and event, preserve the source-reported majority in words. Keep the exact '
    'population, balance date, event date, and any uncertainty that matters to that distinction. '
    'When the source gives a material portion below half, convey its supported qualitative '
    'extent and attribute the disclosure to the source. For a substantial portion, saying '
    'only "some" loses that information. Assess the size in context and retain the named '
    'population, including when it is broader than the selected component. '
    'An unrelated percentage, a growth rate, an ambiguous range or two amounts without a '
    'reported share cannot establish that extent. Keep unbound percentages out of visible copy. '
)


SOURCE_EXPLANATION_RULES = (
    'Keep each material source explanation attached to what it explains. A reason for '
    'a measure’s generally high or low level differs from a reason for a change in a '
    'particular interval. Where the source gives both, preserve both with their own '
    'factors, affected populations and stated timing. Read the full source passage '
    'for each trajectory. Preserve its material stable phases and each subsequent '
    'turning point in source order, with the cause and offset attached to the exact '
    'period they explain. Check the last dated movement as well as the first. '
    'A general industry or method description without an explicit date needs its own '
    'source-defined scope. Keep it separate from dated company results and drivers. '
    'Also keep separate explanations '
    'for distinct changes, limitations and qualified judgments. Read related source '
    'sections for a broader explanation, any risk inferred by the source, and its own '
    'assessment or response. Preserve the supported qualitative extent of a material effect. '
    + SOURCE_SHARE_RULES +
    'Preserve the indication, test basis and result separately '
    'when the source distinguishes them. Treat all such context as attributed source '
    'claims with complete literal proof. A calculation-method explanation may repeat exact '
    'day-count parameter phrases from its own complete quoted definition. Those parameters '
    'describe the formula and must never be presented as observed durations or amounts. '
)


PERIOD_AND_ASSURANCE_RULES = (
    'Use "[amount] as of [date]" for a point-in-time balance. For flows use '
    '"[amount] for [period]" or "[period]: [amount]"; '
    'do not enclose a positive monetary amount in parentheses, which denote an accounting '
    'negative. Keep dates adjacent in a direction interval and put the supporting levels '
    'in a separate sentence instead of inserting parenthetical amounts between endpoints. '
    'Use exact supplied period labels for row-bound claims. In source_context.scope, '
    'copy any source-only discussion window from the item’s own literal proof, including '
    'both the duration and end date in a complete months-ended phrase. If the source '
    'discusses a comparison of two such periods, preserve both complete phrases in '
    'their source order. Prefer the literal year or reporting-window wording in that '
    'item’s proof to shorthand drawn from a different table. When a scope '
    'combines bound annual periods and a separately stated discussion window, keep the '
    'bound annual labels and copy the discussion window in full. Include the paragraph '
    'opener in the contiguous proof when it establishes that timing. '
    'planned_source_citations.bound_periods are the actual row coordinates, not a prompt '
    'to invent alternate labels. A dated snapshot is not a fiscal-year or interim flow. '
    'Never demand or introduce FY/6M aliases for dated balances, or invent dates for FY '
    'or interim rows. A related source-only discussion may retain its literal proved '
    'timing in words. Reviewers must verify proposed scope corrections against these '
    'bindings and the complete source; earlier feedback cannot authorize a new period. '
    'If complete proof exceeds one quote, use continuation_quotes for the remaining literal '
    'passages, each with its own physical page number. Never merge across page boundaries '
    'or remove intervening words to fit. Every proof is checked independently. '
    'For EVERY row-bound direction, put the exact metric and BOTH exact comparison periods '
    'inside that same clause: "[metric] rose from [start] to [end]". A preceding dated-level '
    'list may use "as of" for each level. In the separate direction clause, put each exact date '
    'directly after "from" or "to". '
    'A dated-level list does not supply an omitted endpoint to "then rose to [end]", "fell to [end]", '
    '"rising through [end]" or "the earlier decline". For a multi-leg trajectory, give each '
    'leg its own metric and start/end pair, or retain the full dated-level list without those '
    'incomplete directional predicates. Do not infer a comparison start from the first row. '
    'When both source values are signed cash outflows, a more-negative value means more '
    'cash used and a less-negative value means less cash used. State the direction of cash use '
    'explicitly and retain the original signed amounts, units and exact periods. '
    'Source-only drivers belong in source_context with their literal discussion scope and '
    'complete proof, not in message as an additional unbound direction. '
    'Source-attributed qualitative paraphrases may preserve a material effect with exact '
    'context_evidence, without publishing any unbound amounts, rates or measurements. '
    'Do not demand a verbatim visible quote instead of a faithful qualitative paraphrase. '
    'source_context provides explicitly declared source-only explanations with a full '
    'literal proof and scope; the compiler displays them separately from row calculations. '
    'Its quote already supplies the source proof; do not repeat that same passage in '
    'context_evidence. '
    'Verify every effect, population, condition, direction and attribution against the '
    'complete original source. Declaring source context is never semantic approval. '
    'A source_context explanation need not repeat its proof verbatim. Preserve its '
    'actual effect, timing, population and qualifications without new measurements. '
    'Literal source timing may remain in source_context even without a measured row: '
    'keep quoted annual years and complete months-ended date phrases as discussion scope, '
    'not new numeric comparison endpoints. Use explicit temporal wording such as '
    '"during [source year]"; do not turn a measured count or amount into a year. '
    'A literal source named interval may include those dates in its scope. '
    'Compact ISO dates and spelled calendar dates are equivalent when they identify the '
    'same exact bound source date. Do not reject an ISO spelling merely because a '
    'table uses year columns under a complete as-of date header. Verify the full '
    'header and bound row; never invent a day from a bare fiscal-year label. '
    'Do not demand a visible literal quotation or numeric comparison endpoints for '
    'a faithful declared source-only explanation. Its complete original quotation '
    'is proof for the independent semantic review, not another measured series. '
    'Every raw amount uses its row unit INCLUDING its scale, not just its currency code. '
    'source_rows.amount_literal supplies an exact supported spelling when available. '
    'For example, a raw cell 1,250 in USD thousands means USD 1,250 thousand, never '
    'USD 1,250. Use a scale suffix on EVERY amount, including components, or put an '
    'explicit "(USD in thousands)" declaration at the beginning of that same message '
    'paragraph. This declaration governs later same-currency raw numerals in that paragraph; '
    'an explicit amount suffix overrides it. Prefer amount_literal on every typed amount '
    'to avoid ambiguity. A title or chart unit does not govern the message. Preserve the actual '
    'bound currency and scale; the example does not authorize USD or thousands elsewhere. '
    'When a bound raw value fails only because its scale was omitted, correct its unit; '
    'do not delete that supported value or add unrelated companion rows. '
    'For a source-only causal effect with no eligible numeric series, use an attributed '
    'qualitative effect rather than an increase/decrease predicate: for example, '
    '"Within [literal source scope], the source links [factors] to a longer [source-defined '
    'cycle]" or "The source describes [factors] as consuming cash within [literal scope]." '
    'Choose words faithful to the actual source, preserving direction, affected measure, '
    'factors and qualifications. Do not reuse the example if unsupported. A source-only '
    'effect has no invented measurement endpoints, but must keep its exact context_evidence. '
    'In the main quantitative message, phrases such as "an increase in [unbound metric]" '
    'still need row bindings; adding "the source says" does not resolve them. Put '
    'source-only effects in source_context and verify them against its original proof. '
    'For source-defined nonnumeric category descriptions, retain the complete boundary '
    'in words with its exact quotation; never change it or turn it into a measured level. '
    'Keep a literal technical modifier with the product category that it defines in the proof. '
    'For a row-bound amount or change, use the exact bound period labels even in parentheses '
    'and source attributions. Do not expand a fiscal-year or interim label into a calendar date. If the levels have '
    'different reporting bases, list their exact dated values separately instead of asserting a '
    'direction across those bases. State a source-attributed driver separately and retain its '
    'literal source scope without turning it into a comparison between incompatible endpoints. '
    'A source-defined named interval must retain its literal name; do not narrow it to the '
    'subset of periods used by the chart comparison. An attributed qualitative explanation '
    'for that broader named scope is distinct from a numeric comparison across unequal durations. '
    'Read a prose citation together with its preceding and following source pages. A continuation '
    'may inherit its period, entity and measure from the preceding paragraph opening, while later '
    'paragraphs on the same page can concern different periods. A driver_quote alone does not '
    'establish that scope. Attribute a driver to the period stated in its own paragraph; a '
    'within-period explanation does not establish a comparison with another period. If the '
    'paragraph scope is unavailable, report the uncertainty instead of supplying an interval. '
    'When a discussion has a literal dated window but does not separately date a related '
    'effect, distinguish those scopes explicitly: describe the effect within that named '
    'discussion and state that no separate comparison pair is supplied. Do not assign the '
    'window as new metric endpoints or discard the known discussion context. '
    'For source prose without eligible numeric rows, preserve the supported qualitative driver '
    'and the actual effect attributed by the source. An explicitly attributed qualitative '
    'explanation, supported by exact context_evidence, may say that a factor lengthened a '
    'cycle or shifted exposure without supplying new numeric endpoints. Do not invent a '
    'comparison interval when the source gives none; retain any literal timing qualifier. '
    'Keep the stated role without adding a favorable or adverse judgment the source '
    'does not make. Preserve a material composition shift toward or away from a source-defined '
    'category in attributed words, with its literal interval and exact supporting quotation. '
    'When that composition has no eligible numeric row, use the qualitative nominal form '
    '"The source describes a shift toward [category] during [literal source scope]" '
    '(or "away from" when supported). Do not recast it as "the share increased/decreased", '
    'which asserts a separate unbound measurement comparison. The source meaning and '
    'material adverse effect must remain; only its numerical-predicate framing changes. '
    'Do not replace that shift with a generic mention of adverse context. Numeric comparisons '
    'require bound rows and explicit endpoints; distinguish them from a literally supported '
    'source-attributed qualitative explanation. Do not turn prose-only factors into additional '
    'numerical trend claims. Do not require '
    'their unbound amounts on the analysis page. '
    'For a source-only trajectory without an eligible numeric series, retain a source-attributed '
    'qualitative shape, such as an initial dip followed by a rebound, rather than asserting '
    'an additional row-bound comparison for that unbound metric. Keep its literal scope and '
    'exact quotation; this does not authorize new amounts or calculated endpoints. '
    'A calculation definition may retain its literal day-count convention when complete '
    'context_evidence quotes the method and exact parameter phrases. Copy those phrases '
    'verbatim, such as [number] days for a given year or [number] days for a [duration]-month '
    'period. These are quoted method parameters, not additional measurements. Do not use '
    'them as amounts elsewhere or invent a calendar conversion. '
    'For material source-only qualifications without eligible rows, preserve their qualitative '
    'meaning, including adverse or limiting effects, and distinguish related gross/net or other '
    'populations. Do not require unbound percentages or thresholds. Do not present reassurance '
    'such as "relatively low" as an objective, population-wide conclusion. A source-attributed '
    'management judgment may remain alongside the material adverse shift and its exact '
    'source-defined scope, supported by literal context_evidence. Preserve those qualitative '
    'limits in the same discussion; neither the judgment nor the adverse shift substitutes '
    'for the other. Do not broaden a judgment about a subset. '
    'Only use an audit label for a row explicitly marked with that status. Unknown means unmarked. '
    'Never propagate a label to another period or measure based on a shared heading. '
    'When a chart reports CAGR alongside its raw levels, cite the matching reported CAGR companion row. '
    'State the reported CAGR and any recalculated CAGR in separate sentences, with explicit attribution '
    'and the exact start and end years in each sentence. Use the bound original chart unit for the levels. '
    'A Python-calculated CAGR is a derived result, not a source table cell. It may be stated as '
    '"The calculated CAGR was [rate] from [exact start period] to [exact end period]" when the '
    'supplied calculation and its input rows support it. Do not remove such a calculated rate '
    'merely because the source does not report a CAGR cell. Do not relabel it as reported. '
    'For a monetary calculated difference, use the exact signed Python change with '
    'a calculated-change label, full source metric and both periods. Prefer '
    'bound_calculations.amount_literal as its explicit currency-and-scale spelling when supplied. '
    'The calculation value is in base units; never put that base-unit numeral under a different '
    'paragraph scale without its own explicit unit suffix. '
    'Preserve its negative '
    'sign even when a loss widened in magnitude. A widening description need not add a '
    'second derived numeral. Never copy a positive loss magnitude as a signed delta. '
)
_PERIOD_ASSURANCE = re.compile(
    r'(?P<period>\b(?:FY\d{4}|\d{1,2}M\d{4}|\d{4}-\d{2}-\d{2})\b)\s*'
    r'\(\s*(?P<status>unaudited|audited)\s*\)', re.I)


def _check_explicit_period_assurance(text, observations):
    """Reject an adjacent label that has no matching row for the named period."""
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    by_period = {}
    for observation in observations:
        if observation.period:
            period = bound_period_dates(observation.period, [observation.period])
            by_period.setdefault(period.upper(), set()).add(observation.audited_status)
    for match in _PERIOD_ASSURANCE.finditer(text):
        period, status = match['period'].upper(), match['status'].lower()
        if status not in by_period.get(period, ()):
            raise ValueError(f'{period} has no bound row explicitly marked {status}. '
                             'Keep the exact period and value and remove the unsupported qualifier.')


class RetainedPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=180,
        description='Concise metric and scope label. Put dated direction and trajectory in the message. '
                    'If the title itself asserts a change, it must state both complete comparison dates.')
    message: str = Field(min_length=1, max_length=STANDARD_AUTHORED_COPY_CHARACTERS,
        description='Aim for under 900 characters using exact source period labels and shared explicit units. '
                    'Keep material source qualifications and dated components intact. Final physical '
                    'page budgets and rendered text fit are checked separately; never truncate evidence.')
    companion_ids: list[str] = Field(default_factory=list, max_length=40,
        description='Only extra rows used in visible copy. Choose row references from this finding’s '
                    'allowed_companion_rows. Use [] when its primary observations are sufficient.')
    context_evidence: list[BriefQuote] = Field(default_factory=list, max_length=8,
        description='Exact literal quotations from supplied source_pages, keyed by their supplied '
                    'physical page number, supporting qualitative '
                    'qualifications or drivers outside the primary row evidence. These do not '
                    'authorize additional amounts or companion rows. Complete literal calendar '
                    'dates in these quotations can support the dates of attributed source events. '
                    'Complete literal calculation definitions may bind their exact day-count parameters '
                    'in a method description, never an unrelated measurement.')
    source_context: list[QualifiedSourceCopy] = Field(default_factory=list,max_length=8,
        description='Optional qualitative source explanations, each with its literal proof and '
                    'scope. No new measurements or calculated conclusions. They remain visible '
                    'and require fresh independent original-source review.')

    @model_validator(mode='after')
    def bounded_proof_capacity(self):
        # Existing capacity: eight standalone quotes plus eight context proofs.
        if len(self.all_context_evidence)>16:
            raise ValueError('Complete page proof exceeds the existing 16-quotation evidence capacity')
        return self

    @model_serializer(mode='wrap')
    def _compatible_source_context(self,handler):
        values=handler(self)
        if not self.source_context:
            values.pop('source_context',None)
        elif 'context_evidence' in values:
            proofs={(q.page,q.text) for item in self.source_context for q in item.proof_quotes}
            values['context_evidence']=[q for q in values['context_evidence']
                if (q['page'],q['text']) not in proofs]
        return values

    @property
    def all_context_evidence(self):
        from adaptive_document_agent.services.source_quotes import normalize_quote
        quotes=list(self.context_evidence)
        for item in self.source_context:
            for proof in item.proof_quotes:
                if not any(q.page==proof.page and normalize_quote(proof.text)
                           in normalize_quote(q.text) for q in quotes):
                    quotes.append(proof)
        return quotes


class ContextEvidenceError(ValueError):
    """A qualitative citation lacks a literal binding to its supplied page."""


def _context_sources(context, result):
    from adaptive_document_agent.services.source_quotes import normalize_quote
    allowed = {p['page'] for p in context.get('source_pages', [])}
    return {p.page_number: normalize_quote(p.text) for p in result.document.pages if p.page_number in allowed}


def rebind_context_evidence(selection, context, result):
    """Correct a page number only when unchanged literal proof has one supplied match."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    sources = _context_sources(context, result)
    corrections = []
    for decision in selection.decisions:
        if decision.decision != 'include' or decision.page is None:
            continue
        for index, quote in enumerate(decision.page.context_evidence):
            text = normalize_quote(quote.text)
            if not text or text in sources.get(quote.page, ''):
                continue
            matches = [page for page, source in sources.items() if text in source]
            if len(matches) == 1:
                corrections.append(dict(insight_id=decision.insight_id, quote_index=index,
                                        original_page=quote.page, source_page=matches[0]))
                decision.page.context_evidence[index] = quote.model_copy(update={'page': matches[0]})
        for item in decision.page.source_context:
            proofs=item.proof_quotes
            for index,proof in enumerate(proofs):
                text=normalize_quote(proof.text)
                if text and text not in sources.get(proof.page,''):
                    matches=[page for page,source in sources.items() if text in source]
                    adjacent=False
                    if len(matches)>1:
                        # A continuation may end with words repeated on another
                        # page. Use only adjacent submitted proofs with the same
                        # declared page whose entire union binds literally.
                        neighbors = range(max(0, index - 1), min(index + 1, len(proofs) - 1))
                        pairs = []
                        for previous in neighbors:
                            left, right = proofs[previous:previous + 2]
                            if left.page == right.page == proof.page:
                                pairs.append(normalize_quote(left.text + ' ' + right.text))
                        matches=[page for page in matches if any(pair in sources[page] for pair in pairs)]
                        adjacent=True
                    if len(matches)==1:
                        corrections.append(dict(insight_id=decision.insight_id,source_context=True,
                            original_page=proof.page,source_page=matches[0]))
                        if adjacent:
                            corrections[-1]['basis']='contiguous_literal_proof'
                        corrected=proof.model_copy(update={'page':matches[0]})
                        if index:item.continuation_quotes[index-1]=corrected
                        else:item.quote=corrected
    return corrections


def context_evidence_pages(page, context, result):
    """Bind model-selected qualitative context without expanding numeric eligibility."""
    from adaptive_document_agent.services.source_quotes import normalize_quote
    if page is None or not page.all_context_evidence:
        return set()
    sources = _context_sources(context, result)
    pages = set()
    for index, quote in enumerate(page.all_context_evidence, 1):
        text = normalize_quote(quote.text)
        if not text or text not in sources.get(quote.page, ''):
            from adaptive_document_agent.services.literal_quote_feedback import source_passage_hint,supplied_passage_hints
            original=next((p.text for p in result.document.pages
                           if p.page_number==quote.page and p.page_number in sources),'')
            candidate=source_passage_hint(quote.text,original)
            hint=(' Complete original paragraph on the supplied page (untrusted reading aid, '
                  'not an accepted quote or semantic verdict): '+repr(candidate)) if candidate else ''
            if not candidate:
                alternatives=supplied_passage_hints(quote.text,{p.page_number:p.text
                    for p in result.document.pages if p.page_number in sources and p.page_number!=quote.page})
                if alternatives:
                    hint=(' Original passages on other supplied pages (untrusted reading aids, '
                          'not a relocated quote or semantic verdict; return a new literal citation '
                          'with its physical page number): '+repr(alternatives))
            raise ContextEvidenceError('Context evidence must be a literal quote from a supplied source page. '
                f'Quote {index} does not bind to page {quote.page}. Copy a contiguous passage and its '
                'physical page number from the source_pages record, using its page field.'+hint)
        pages.add(quote.page)
    return pages


def retained_context_citations(result):
    """Recheck persisted quotation provenance for slide/theme validators."""
    from .retained_analysis import selected_record, selection_context, selection_input_matches, RetainedAnalysisSelection
    record = selected_record(result)
    if not record or not any(d.get('page', {}).get('context_evidence') or d.get('page', {}).get('source_context')
                            for d in record['selection']['decisions'] if d.get('page')):
        return {}
    context = selection_context(result)
    if not record.get('source_authoring') or not selection_input_matches(record, context, result):
        raise ValueError('Retained qualitative context has stale source bindings')
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    return {d.insight_id: context_evidence_pages(d.page, context, result)
            for d in selection.decisions if d.decision == 'include'}


def _bound_authored_context(result, plan):
    """Recognize exact compiled model copy; this is never semantic approval.

    Generic chart-share retrieval cannot interpret source-only qualifications.
    Preserve this bound copy for the mandatory independent publication review.
    Numeric, literal-source and native presentation validation still apply.
    """
    from .retained_analysis import selected_record, selection_context, selection_input_matches, RetainedAnalysisSelection, findings
    record = selected_record(result)
    if not record or not record.get('source_authoring'):
        return {}
    context = selection_context(result)
    if not selection_input_matches(record, context, result):
        return {}
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    linked = findings(result, allow_new_copy=True)
    bound = {}
    for decision in selection.decisions:
        if decision.decision != 'include' or decision.page is None:
            continue
        insight, primary, _ = linked[decision.insight_id]
        bound[decision.insight_id] = page_bindings(decision.page, insight, primary, context, result,
                                                 with_source_context=True)
    return {s.id:bound[s.insight_ids[0]][3] for s in plan.slides if s.slide_type == 'analysis' and len(s.insight_ids) == 1
            and s.insight_ids[0] in bound
            and (s.title, s.message, set(s.observation_ids)) == bound[s.insight_ids[0]][:3]
            and (not bound[s.insight_ids[0]][3] or
                 s.bullets[:1+len(bound[s.insight_ids[0]][3])] == [s.message,*bound[s.insight_ids[0]][3]])}


def bound_authored_slide_ids(result,plan):
    return set(_bound_authored_context(result,plan))


def reported_context_bullet_positions(result,plan):
    """Only exact compiled, source-bound qualitative quotations have no row scope."""
    return {sid:set(range(1,len(parts)+1)) for sid,parts in _bound_authored_context(result,plan).items()
            if parts}


def retained_context_dates(result, *, checked_citations=None):
    """Return only calendar identities from revalidated literal context quotes."""
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
    return _retained_context_literals(result, literal_calendar_dates, checked_citations)


def retained_context_day_counts(result, *, checked_citations=None):
    """Return only literal parameters of revalidated calculation definitions."""
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
    return _retained_context_literals(result, literal_day_count_conventions, checked_citations)


def _retained_context_literals(result, extract, checked_citations):
    from .retained_analysis import RetainedAnalysisSelection, selected_record
    checked = retained_context_citations(result) if checked_citations is None else checked_citations
    record = selected_record(result)
    if not checked or not record:
        return {}
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    return {d.insight_id: set().union(*(extract(q.text)
            for q in d.page.all_context_evidence if q.page in checked.get(d.insight_id, ())))
            for d in selection.decisions if d.decision == 'include' and d.page}


def page_sources(result, linked, *, include_neighbors=True):
    from adaptive_document_agent.services.source_amount_literal import source_amount_literal
    from adaptive_document_agent.services.source_citations import evidence_pages
    ids = set().union(*(entry[1] for entry in linked.values()))
    anchors = [o for o in result.observations if o.id in ids]
    from .retained_source_inventory import complete_source_observations
    sources = complete_source_observations(result,ids) if include_neighbors else anchors
    pages = {e.page for o in sources for e in o.evidence}
    for insight, _, _ in linked.values():
        pages.update(evidence_pages(insight, [], document=result.document))
    if include_neighbors:
        # A table's discussion can begin on its next page and continue onto
        # the following page. Keep that bounded complete-page envelope on the
        # authoring wire too; it grants no extra numeric row eligibility.
        pages = {n for page in pages for n in range(page - 2, page + 3)
                 if 1 <= n <= result.document.page_count}
    originals = [p for p in result.document.pages if p.page_number in pages]
    tables = {o.effective_table_id for o in anchors if o.effective_table_id}
    ambiguous = ambiguous_source_table_ids(result)
    companions = [o for o in result.observations if o.effective_table_id in tables
                  and o.value is not None and o.validation_status == 'valid' and o.evidence
                  and not observation_uses_ambiguous_table(o, ambiguous)]
    return dict(source_pages=[audit_source_page(p) for p in originals],
                source_rows=[dict(id=o.id, table_id=o.effective_table_id,
                    metric=o.metric_original, parent=o.parent_section, categories=o.category_dimensions,
                    period=o.period, value=o.raw_value, unit=o.raw_unit, currency=o.currency,
                    amount_literal=source_amount_literal(o))
                    for o in companions])


def authored_message(page,periods):
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    from .reported_source_context import qualified_source_statement
    copy=bound_period_dates(page.message,periods)
    for item in page.source_context:
        statement=bound_period_dates(qualified_source_statement(item),periods)
        if statement not in copy:
            copy+=' '+statement
    return copy


def authored_visible_copy(page,periods):
    """Measure the same scope grouping the audience sees."""
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    from .reported_source_context import source_context_paragraphs,source_context_scope_prefixes

    message=bound_period_dates(page.message,periods)
    scopes=source_context_scope_prefixes(page.source_context,periods)
    statements=[statement for statement in scopes if statement not in message]
    return ' '.join([message,*source_context_paragraphs(statements,scope_prefixes=scopes)])


def page_bindings(page, insight, primary, context, result, *, _copy_errors=None,
                  with_source_context=False):
    """Bind provenance first; optionally collect copy failures for combined diagnostics."""
    from .presentation_insight_recovery import _numeric_support
    from adaptive_document_agent.services.calendar_claims import bound_period_dates, literal_calendar_dates
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
    context_evidence_pages(page, context, result)
    context_dates = set().union(*(literal_calendar_dates(q.text) for q in page.all_context_evidence))
    day_counts = set().union(*(literal_day_count_conventions(q.text) for q in page.all_context_evidence))
    by_id = {o.id: o for o in result.observations}
    tables = {by_id[k].effective_table_id for k in primary}
    allowed = {r['id'] for r in context['source_rows'] if r['table_id'] in tables}
    ids = primary | set(page.companion_ids)
    foreign = set(page.companion_ids) - allowed - primary
    primary_series = {(by_id[k].effective_table_id, by_id[k].metric_original) for k in primary}
    foreign.update(k for k in set(page.companion_ids) & allowed
                   if (owner := by_id[k].dimensions.get('chart_reported_cagr'))
                   and (by_id[k].effective_table_id, owner) not in primary_series)
    if foreign:
        raise ValueError(f'{insight.id}: companion rows outside its source tables: {sorted(foreign)}')
    if len(ids) > 40:
        raise ValueError(f'{insight.id}: {len(ids)} distinct observations exceed the 40-row slide limit')
    obs = [by_id[k] for k in ids]
    periods = [o.period for o in obs]
    title=bound_period_dates(page.title,[*periods,*context_dates])
    copy=authored_message(page,[*periods,*context_dates])
    limit=authored_copy_limit(result.profile.report_requirements)
    if len(authored_visible_copy(page,[*periods,*context_dates]))>limit:
        raise ValueError(f'{insight.id}: complete authored copy exceeds the {limit}-character page limit')
    full_copy=copy
    from .reported_source_context import reported_source_components,observation_context_labels
    copy,reported=reported_source_components(copy,page.all_context_evidence,periods=[*periods,*context_dates],
        labels=observation_context_labels(obs),declared=page.source_context)
    for item in page.source_context:
        statement=bound_period_dates(qualified_source_statement(item),[*periods,*context_dates])
        if statement not in reported:
            from .source_context_periods import scope_period_feedback
            scope_hint=scope_period_feedback(item.scope,[*periods,*context_dates])
            raise ValueError(f'{insight.id}: source_context must be a non-quantitative source '
                'explanation with its exact bound period labels, original proof and no numerical '
                'claim or directional scope predicate. For an unbound source-only missing-value '
                'disclosure, retain the literal named column or discussion scope in words; '
                'do not introduce an unbound fiscal/interim label or invent a calendar date. '
                f'Rejected declaration: {item.model_dump(mode="json")}. Scope binding feedback: {scope_hint}')
    for field, text in [('title', title), ('message', copy)]:
        diagnostics = []
        if not _numeric_support(text, obs, diagnostics=diagnostics, context_dates=context_dates,
                                context_day_counts=day_counts):
            error = (f'{insight.id}.{field}: amount, date or rate outside its bound evidence: {text}. '
                f'Details: {diagnostics}. Exact quoted day-count parameters: {sorted(day_counts)}. '
                'For a day-count description, quote the complete method and copy its literal parameter '
                'phrases verbatim; this does not authorize other values. Bind any used table components to their exact '
                'allowed companion rows. Do not introduce amounts found only in unbound source prose; '
                'retain the source explanation without that additional numeric claim. Preserve signed raw outflows.')
            if _copy_errors is None:
                raise ValueError(error)
            _copy_errors.append(error)
        from adaptive_document_agent.services.presentation_evidence import calculation_catalog
        from adaptive_document_agent.validation.presentation_numeric_evidence import (
            checked_money_amounts,mask_declared_calculated_amounts)
        catalog=calculation_catalog(obs)
        masked=mask_declared_calculated_amounts(text,obs,catalog.values())
        for match,supported,calculation_ids in checked_money_amounts(text,obs,catalog.values()):
            if supported and calculation_ids and masked[match.start():match.end()].strip():
                error=(f'{insight.id}.{field}: derived monetary amount {match[0]!r} needs '
                    'an explicit calculated-change label, exact source metric and one exact '
                    'comparison interval in the same sentence. Prefer the amount followed by '
                    '"from [start] to [end]". A matching numeral alone is not a calculation binding.')
                if _copy_errors is None:raise ValueError(error)
                _copy_errors.append(error)
        try:
            _check_explicit_period_assurance(full_copy if field=='message' else text, obs)
        except ValueError as exc:
            if _copy_errors is None:
                raise ValueError(f'{insight.id}.{field}: {exc}') from exc
            _copy_errors.append(f'{insight.id}.{field}: {exc}')
    from .reported_source_context import source_context_paragraphs,source_context_scope_prefixes
    scopes=source_context_scope_prefixes(page.source_context,[*periods,*context_dates])
    paragraphs=source_context_paragraphs(reported,scope_prefixes=scopes)
    if len(' '.join([copy,*paragraphs]))>limit:
        raise ValueError(f'{insight.id}: complete authored copy exceeds the {limit}-character page limit')
    return (title,copy,ids,paragraphs) if with_source_context else (title,copy,ids)


class RejectedPageAttempt(BaseModel):
    page: RetainedPage
    errors: list[str]


class AuthoredPageErrors(ValueError):
    def __init__(self, by_insight: dict[str, list[str]], *,
                 rejected_attempts: dict[str, list[RejectedPageAttempt]] | None = None):
        self.by_insight = by_insight
        self.rejected_attempts = rejected_attempts or {}
        super().__init__('\n'.join(f'{iid}: {issue}' for iid, issues in by_insight.items() for issue in issues))


def validate_authored_pages(selection, context, result):
    from adaptive_document_agent.models import PresentationSlide
    from adaptive_document_agent.validation.claim_validator import ClaimValidator
    from .retained_analysis import findings
    linked = findings(result, allow_new_copy=True)
    failures = {}
    for decision in selection.decisions:
        if decision.decision != 'include':
            continue
        insight, primary, _ = linked[decision.insight_id]
        copy_errors = []
        try:
            title, copy, ids, reported = page_bindings(decision.page, insight, primary, context, result,
                _copy_errors=copy_errors,with_source_context=True)
        except ValueError as exc:
            failures[insight.id] = [str(exc).removeprefix(f'{insight.id}: ')]
            continue
        probe = PresentationSlide(id=insight.id, slide_type='analysis', title=title, message=copy,
                                  observation_ids=sorted(ids),
                                  bullets=reported,bullet_observation_ids=[[] for _ in reported],
                                  source_pages=sorted(context_evidence_pages(decision.page, context, result)))
        observations = [o for o in result.observations if o.id in ids]
        errors = ClaimValidator().validate_slide(probe, observations)
        if copy_errors:
            failures[insight.id] = copy_errors
        if not errors:
            continue
        issues = failures.setdefault(insight.id, [])
        issues.extend(e.message for e in errors)
        if any(e.code == 'direction_scope_ambiguous' for e in errors):
            for error in errors:
                if error.code == 'direction_scope_ambiguous' and error.offending_direction:
                    issues.append(f'The exact rejected direction token is {error.offending_direction!r} '
                        f'in {error.target_component} at offsets {error.claim_start}:{error.claim_end}. '
                        'Correct this occurrence, including an attributive direction inside a driver '
                        'phrase; do not replace a different qualitative effect elsewhere in the clause.')
            periods = sorted({o.period for o in observations if o.id in primary and o.period})
            metrics = sorted({o.metric_original for o in observations})
            issues.append(f'Primary source periods are {periods}. In each directional clause, explicitly '
                'name the source metric and both source-supported endpoints for a comparison. '
                '"The decrease through [end]" supplies only one endpoint. Never infer the '
                'start from the earliest data. Separate the headline comparison from its drivers. '
                'If a driver has no source-supported interval, describe the supported event without '
                'claiming a change over an unspecified period. '
                f'Bound source metrics are {metrics}. Naming an unbound metric more explicitly '
                'cannot create a numeric comparison binding. For a prose-only trajectory, retain '
                'its source-attributed qualitative shape (for example an initial dip followed by '
                'a rebound), literal discussion scope and exact quotation, without new amounts '
                'or invented measurement endpoints. For a qualitative driver, preserve the '
                'actual source-attributed effect, not just a generic favorable/adverse label.')
        if any(e.target_component == 'title' for e in errors):
            issues.append('Use a neutral metric/scope title, or explicitly write both '
                            'comparison endpoints in the title itself. Dates in the message do not '
                            'supply a missing title endpoint.')
    if failures:
        raise AuthoredPageErrors(failures)


def writer_context(context):
    """Use short references on the wire; persist only the original observation IDs."""
    rows = context['source_rows']
    aliases = {f'row-{i}': row['id'] for i, row in enumerate(rows, 1)}
    table_by_id = {row['id']: row['table_id'] for row in rows}
    findings = []
    for finding in context['findings']:
        primary = set(finding['observation_ids'])
        tables = {table_by_id[oid] for oid in primary if oid in table_by_id}
        allowed = [alias for alias, oid in aliases.items() if oid not in primary and table_by_id[oid] in tables]
        findings.append(dict(finding, allowed_companion_rows=allowed))
    return {**context, 'findings': findings, 'source_rows': [
        {**row, 'id': alias} for alias, row in zip(aliases, rows, strict=True)]}, aliases


def source_row_assurance(result, row_refs):
    """Expose explicit per-row source annotations on the wire only."""
    status = {o.id: o.audited_status for o in result.observations
              if o.audited_status in {'audited', 'unaudited'}}
    return {ref: status[oid] for ref, oid in row_refs.items() if oid in status}


def planned_source_citations(selection, context, result):
    """Expose the compiler's actual page references, never model-proposed citations."""
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
    from adaptive_document_agent.services.source_day_count import literal_day_count_conventions
    from adaptive_document_agent.services.source_citations import evidence_pages, source_footer
    observations = {o.id: o for o in result.observations}
    insights = {i.id: i for i in result.insights}
    findings = {f['insight']['id']: f for f in context['findings']}
    available_pages = {p.page_number for p in result.document.pages}
    citations = []
    for decision in selection.decisions:
        if decision.decision != 'include':
            continue
        finding = findings.get(decision.insight_id, {})
        primary = set(finding.get('observation_ids', []))
        companions = set(decision.page.companion_ids if decision.page else [])
        ids = primary | companions
        if not primary or ids - observations.keys() or decision.insight_id not in insights:
            continue
        tables = {observations[k].effective_table_id for k in primary}
        allowed = {r['id'] for r in context.get('source_rows', []) if r['table_id'] in tables}
        if companions - primary - allowed:
            continue
        bound = [observations[k] for k in sorted(ids)]
        pages = evidence_pages(insights[decision.insight_id], bound, document=result.document)
        try:
            pages = sorted(set(pages) | context_evidence_pages(decision.page, context, result))
        except ContextEvidenceError:
            # A rejected draft has no publishable footer yet. Keep the other
            # findings reviewable so the writer can receive localized feedback.
            continue
        if not pages or set(pages) - available_pages:
            continue
        citation = dict(insight_id=decision.insight_id, observation_ids=sorted(ids),
                        source_pages=pages, footer=source_footer(pages),
                        bound_periods=sorted({o.period for o in bound if o.period}),
                        eligible_companion_rows=[r['id'] for r in context.get('source_rows', [])
                                                 if r['table_id'] in tables],
                        context_calendar_dates=sorted(set().union(*(literal_calendar_dates(q.text)
                            for q in decision.page.all_context_evidence))) if decision.page else [],
                        context_day_count_conventions=sorted(set().union(*(literal_day_count_conventions(q.text)
                            for q in decision.page.all_context_evidence))) if decision.page else [])
        marked_tables = {o.effective_table_id for o in bound
                         if o.effective_table_id and o.audited_status in {'audited', 'unaudited'}}
        if marked_tables:
            citation['bound_assurance'] = [dict(observation_id=o.id, metric=o.metric_original,
                period=o.period, audited_status=o.audited_status)
                for o in bound if o.effective_table_id in marked_tables]
        citations.append(citation)
    return citations
