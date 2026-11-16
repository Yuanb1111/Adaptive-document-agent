"""Separate literal qualitative source speech from row-calculated comparisons."""
import re
from pydantic import BaseModel,ConfigDict,Field,model_validator,model_serializer
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


class QualifiedSourceCopy(BaseModel):
    """Model-owned source meaning; no quantity or semantic approval is inferred."""
    model_config=ConfigDict(extra='forbid')
    scope: str = Field(min_length=1,max_length=220,description=
        'Exact bound period labels (for example the supplied FY or interim labels) or '
        'the literal named source discussion scope. Never expand a supplied interim label '
        'to a months-ended date phrase unless the complete phrase occurs in this item’s '
        'own contiguous quote, including its paragraph opener. No leading For/In, direction or amount.')
    description: str = Field(min_length=10,max_length=700,description=
        'Faithful source-attributed qualitative effect and population, beginning with a verb '
        'such as describes. No amounts, rates, counts, calculated comparisons or attribution '
        'prefix. Preserve adverse context, directions, conditions and management attribution.')
    quote: BriefQuote = Field(description=
        'Complete contiguous literal original passage and physical source page supporting '
        'the meaning. Use continuation_quotes for further passages or page continuations; '
        'never join text from different pages in one quote. Each quote has at most 1800 '
        'characters. Numeric proof does not authorize a number in the visible description.')
    continuation_quotes: list[BriefQuote] = Field(default_factory=list,max_length=3,description=
        'Further literal proof for this same explanation, each with its own physical page. '
        'Split a long contiguous quotation at word boundaries without deleting any words. '
        'These proofs share the existing page evidence capacity and require literal binding.')

    @model_validator(mode='before')
    @classmethod
    def split_long_literal_proof(cls,values):
        if not isinstance(values,dict):return values
        quote=values.get('quote')
        if isinstance(quote,dict) and 'continuation_quotes' in quote:
            nested=quote['continuation_quotes'];existing=values.get('continuation_quotes',[])
            if (not isinstance(nested,list) or not isinstance(existing,list)
                    or (existing and existing!=nested)):
                return values
            # Move only this exact typed field; unknown quote fields still fail.
            nested=[BriefQuote.model_validate(q).model_dump(mode='json') for q in nested]
            quote={k:v for k,v in quote.items() if k!='continuation_quotes'}
            values={**values,'quote':quote,'continuation_quotes':nested}
        if not isinstance(quote,dict) or not isinstance(quote.get('text'),str) or len(quote['text'])<=1800:
            return values
        continuations=values.get('continuation_quotes',[])
        if not isinstance(continuations,list):return values
        from adaptive_document_agent.services.source_quotes import split_literal_quote
        parts=split_literal_quote(quote['text'])
        return {**values,'quote':{**quote,'text':parts[0]},'continuation_quotes':[
            *({**quote,'text':part} for part in parts[1:]),*continuations]}

    @model_serializer(mode='wrap')
    def omit_empty_continuations(self,handler):
        values=handler(self)
        if not self.continuation_quotes:values.pop('continuation_quotes',None)
        return values

    @property
    def proof_quotes(self):
        return [self.quote,*self.continuation_quotes]

    @property
    def proof_text(self):
        # Keep separate passages distinct so numeric grammar cannot bridge a gap.
        return '\n\n[Separate literal source passage]\n\n'.join(q.text for q in self.proof_quotes)


def qualified_source_statement(item):
    """Normalize grammar only; never rewrite the source quotation or its meaning."""
    scope=re.sub(r'^(?:(?:For|In|During|Within)\s+)+','',item.scope.strip(),flags=re.I)
    description=item.description.strip()
    description=description[:1].lower()+description[1:]
    return f'For {scope}, the source {description}'+('' if description.endswith(('.','!','?')) else '.')


def source_context_paragraphs(parts):
    """Pack unchanged adjacent statements into at most four audience paragraphs.

    The main comparison owns the fifth bullet. This is lossless layout grouping,
    not a limit on qualifications, proof or the independently reviewed meaning.
    """
    count=min(len(parts),4)
    return [' '.join(parts[i*len(parts)//count:(i+1)*len(parts)//count])
            for i in range(count)] if count else []


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
    def qualitative_quote(words,proof=None,*,scope=''):
        # Literal source conditions are not measured levels. Product/category
        # compounds must also occur in a bound row label; never infer a new
        # category. Standalone worded counts/rates retain the quantity guard.
        source=normalize_quote(proof).casefold() if proof is not None else ' '.join(sources).casefold()
        words=_IDENTIFIER.sub(lambda m:' ' if not _CURRENCY_IDENTIFIER.match(m[0])
            and not _PERIOD_IDENTIFIER.fullmatch(m[0]) and re.search(
            r'(?<!\w)'+re.escape(m[0])+r'(?!\w)',source,re.I) else m[0],words)
        from .source_context_periods import mask_source_horizons
        words=mask_source_horizons(words,source)
        if proof is not None:
            from .source_context_periods import mask_reporting_period_references
            words=mask_reporting_period_references(words,proof,scope)
        if _QUANTITY.search(words):
            return False
        from adaptive_document_agent.services.source_duration_conditions import mask_worded_duration_conditions
        words=mask_worded_duration_conditions(words,source)
        labels_text=' '.join(labels).casefold()
        words=_LABEL_COMPOUND.sub(lambda m: ' ' if re.search(
            r'(?<!\w)'+re.escape(m[0])+r'(?!\w)',labels_text,re.I) else m[0],words)
        return not _QUANTITY.search(cardinal_claim_text(words))
    from adaptive_document_agent.validation.claim_validator import _ALL_DIRECTIONAL_WORDS
    def scope_is_literal(scope_text,proof=None):
        if proof is not None:
            from .source_context_periods import mask_source_periods,mask_source_horizons
            scope_text=mask_source_horizons(mask_source_periods(
                scope_text,proof,scope=True,periods=periods),proof)
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
        from .source_context_periods import mask_source_periods
        description=bound_period_dates(mask_source_periods(item.description,item.proof_text,periods=periods),periods,mask=True)
        if description is not None:
            for period in sorted(set(periods),key=len,reverse=True):
                description=re.sub(r'(?<!\w)'+re.escape(period)+r'(?!\w)',' ',description,flags=re.I)
        if (statement is None or description is None or not qualitative_quote(description,item.proof_text,scope=item.scope)
                or not scope_is_literal(re.sub(r'^(?:(?:For|In|During|Within)\s+)+','',
                                               item.scope.strip(),flags=re.I),item.proof_text)
                or not all(any(q.page==proof.page and normalize_quote(proof.text)
                           in normalize_quote(q.text) for q in quotes) for proof in item.proof_quotes)):
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
