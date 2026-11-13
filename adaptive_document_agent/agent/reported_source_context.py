"""Separate literal qualitative source speech from row-calculated comparisons."""
import re
from pydantic import BaseModel,ConfigDict,Field
from adaptive_document_agent.models.executive_brief import BriefQuote

from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.services.calendar_claims import bound_period_dates
from adaptive_document_agent.services.number_words import cardinal_claim_text

_CLAUSE=re.compile(r'(?:^|(?<=[.!?])\s+|(?<=[.!?]["”])\s+)'
    r'(?P<clause>(?P<scope>(?:(?:For|Within|During)\b[^.!?\n]{0,240}?,\s*)?)'
    r'[Tt]he source states:\s*["“](?P<quote>[^"“”\n]{20,1400})["”][.;]?)'
    r'(?=\s|$)')
_QUANTITY=re.compile(r'\d|[%％$€£¥]|人民币|美元|港元|欧元|百分之|百分点|基点|'
    r'\b(?:percent|percentage|USD|RMB|CNY|HKD|EUR|GBP|thousands?|millions?|billions?|'
    r'trillions?|basis\s+points?)\b',re.I)
_YEAR_SCOPE=re.compile(r'(?:19|20)\d{2}(?:\s*(?:to|and|,|;|[–-])\s*(?:19|20)\d{2})*',re.I)
_CARDINAL_WORDS=('zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
                 'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
                 'twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred')
_LABEL_COMPOUND=re.compile(rf'\b(?:{_CARDINAL_WORDS})(?:-(?:{_CARDINAL_WORDS}))*-[a-z]+\b',re.I)
_IDENTIFIER=re.compile(r'(?<!\w)(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*(?!\w)')
_CURRENCY_IDENTIFIER=re.compile(r'^(?:USD|RMB|CNY|HKD|EUR|GBP|JPY|AUD|CAD|CHF)-?\d',re.I)
_PERIOD_IDENTIFIER=re.compile(r'^(?:FY|Q[1-4]-?|H[12]-?)(?:19|20)\d{2}E?$',re.I)
_DURATION_CONDITION=re.compile(rf'\b(?:within|under|over|at\s+least|up\s+to|more\s+than|'
    rf'less\s+than|no\s+(?:more|less|later)\s+than)\s+(?:{_CARDINAL_WORDS})'
    rf'(?:[\s-]+(?:{_CARDINAL_WORDS}))*[\s-]+(?:years?|months?|weeks?|days?|hours?)\b',re.I)


class QualifiedSourceCopy(BaseModel):
    """Model-owned source meaning; no quantity or semantic approval is inferred."""
    model_config=ConfigDict(extra='forbid')
    scope: str = Field(min_length=1,max_length=220,description=
        'Exact bound period labels (for example the supplied FY or interim labels) or '
        'the literal named source discussion scope. No leading For/In, direction or amount.')
    description: str = Field(min_length=10,max_length=700,description=
        'Faithful source-attributed qualitative effect and population, beginning with a verb '
        'such as describes. No amounts, rates, counts, calculated comparisons or attribution '
        'prefix. Preserve adverse context, directions, conditions and management attribution.')
    quote: BriefQuote = Field(description=
        'Complete contiguous literal original passage and physical source page supporting '
        'the meaning. Numeric proof does not authorize a number in the visible description.')


def qualified_source_statement(item):
    """Normalize grammar only; never rewrite the source quotation or its meaning."""
    scope=re.sub(r'^(?:(?:For|In|During|Within)\s+)+','',item.scope.strip(),flags=re.I)
    description=item.description.strip()
    description=description[:1].lower()+description[1:]
    return f'For {scope}, the source {description}'+('' if description.endswith(('.','!','?')) else '.')


def observation_context_labels(rows):
    """Expose only the labels already bound to the provided observation rows."""
    labels=[]
    for row in rows:
        values=row if isinstance(row,dict) else row.model_dump()
        labels.append(values.get('metric_original',values.get('metric','')))
        for key in ('dimensions','category_dimensions','categories'):
            labels.extend(value for value in values.get(key,{}).values() if isinstance(value,str))
    return [label for label in labels if label]


def reported_source_components(text,quotes,*,periods=(),labels=(),declared=()):
    """Move only explicit, numeric-free literal quotations into source context.

    The caller must first bind every quote to its supplied original page. This
    function supplies neither a semantic verdict nor numeric evidence. The
    complete published context still needs independent full-source review.
    """
    periods=tuple(p for p in periods if p)
    sources=[normalize_quote(q.text) for q in quotes]
    def qualitative_quote(words,proof=None):
        # Literal source conditions are not measured levels. Product/category
        # compounds must also occur in a bound row label; never infer a new
        # category. Standalone worded counts/rates retain the quantity guard.
        source=normalize_quote(proof).casefold() if proof is not None else ' '.join(sources).casefold()
        words=_IDENTIFIER.sub(lambda m:' ' if not _CURRENCY_IDENTIFIER.match(m[0])
            and not _PERIOD_IDENTIFIER.fullmatch(m[0]) and re.search(
            r'(?<!\w)'+re.escape(m[0])+r'(?!\w)',source,re.I) else m[0],words)
        if _QUANTITY.search(words):
            return False
        labels_text=' '.join(labels).casefold()
        words=_LABEL_COMPOUND.sub(lambda m: ' ' if re.search(
            r'(?<!\w)'+re.escape(m[0])+r'(?!\w)',labels_text,re.I) else m[0],words)
        words=_DURATION_CONDITION.sub(' ',words)
        return not _QUANTITY.search(cardinal_claim_text(words))
    from adaptive_document_agent.validation.claim_validator import _ALL_DIRECTIONAL_WORDS
    def scope_is_literal(scope_text):
        scope=bound_period_dates(scope_text,periods,mask=True)
        if scope is None:
            return False
        for period in sorted(set(periods),key=len,reverse=True):
            scope=re.sub(r'(?<!\w)'+re.escape(period)+r'(?!\w)',' ',scope,flags=re.I)
        literal_scope=scope_text.strip().rstrip(',').strip()
        literal_scope=re.sub(r'^(?:For|Within|During)\s+','',literal_scope)
        if _YEAR_SCOPE.fullmatch(literal_scope):
            # A bare reported discussion year is metadata, not an invented FY
            # or a counted noun. Never accept "2024 devices" through this path.
            known={year for period in periods for year in re.findall(r'(?:19|20)\d{2}',period)}
            return set(re.findall(r'(?:19|20)\d{2}',literal_scope))<=known
        return not _QUANTITY.search(scope) and not any(re.search(
            r'\b'+re.escape(word)+r'\b',scope,re.I) for word in _ALL_DIRECTIONAL_WORDS)
    matches=[m for m in _CLAUSE.finditer(text) if qualitative_quote(m['quote'])
             and scope_is_literal(m['scope'])
             and any(normalize_quote(m['quote']) in source for source in sources)]
    spans=[(m.start('clause'),m.end('clause'),m['clause']) for m in matches]
    for item in declared:
        statement=bound_period_dates(qualified_source_statement(item),periods)
        description=bound_period_dates(item.description,periods,mask=True)
        if description is not None:
            for period in sorted(set(periods),key=len,reverse=True):
                description=re.sub(r'(?<!\w)'+re.escape(period)+r'(?!\w)',' ',description,flags=re.I)
        if (statement is None or description is None or not qualitative_quote(description,item.quote.text)
                or not scope_is_literal(re.sub(r'^(?:(?:For|In|During|Within)\s+)+','',
                                               item.scope.strip(),flags=re.I))
                or not any(q.page==item.quote.page and normalize_quote(item.quote.text)
                           in normalize_quote(q.text) for q in quotes)):
            continue
        pattern=r'(?:^|(?<=[.!?])\s+)(?P<clause>'+re.escape(statement)+r')(?=\s|$)'
        spans.extend((m.start('clause'),m.end('clause'),m['clause']) for m in re.finditer(pattern,text))
    spans=sorted(set(spans))
    if not spans:
        return text,[]
    main=text
    for start,end,_ in reversed(spans):
        main=main[:start]+main[end:]
    main=' '.join(main.split())
    if not main:
        return text,[]  # A source quote cannot replace the whole analytical page.
    return main,[value for _,_,value in spans]
