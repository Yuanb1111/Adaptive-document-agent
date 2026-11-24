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
_SOURCE_SENTENCE_START=re.compile(r'^(?:attributes?|describes?|notes?|states?|reports?|explains?|'
    r'indicates?|shows?|identifies?|records?|discloses?|clarifies?|confirms?|'
    r'emphasizes?|emphasises?|highlights?|mentions?|observes?|provides?|'
    r'specifies?|summarizes?|summarises?|sets\s+out)\b',re.I)
_REPORTING_VERB=(r'(?:attributes?|describes?|notes?|states?|reports?|explains?|indicates?|shows?|'
    r'identifies?|records?|discloses?|clarifies?|confirms?|emphasizes?|emphasises?|'
    r'highlights?|mentions?|observes?|provides?|specifies?|summarizes?|summarises?|sets\s+out)')
_SCOPED_SOURCE_ATTRIBUTION=re.compile(
    rf'^(?:For|Within|During)\s+[^.!?\n]{{1,220}},\s+the source\s+(?:{_REPORTING_VERB}|links?)\b',re.I)
_COMPANY_ATTRIBUTED_SENTENCE=re.compile(rf'^(?P<speaker>the company|it)\s+'
    rf'(?P<verb>{_REPORTING_VERB})\s+(?P<predicate>.+[.!?])$',re.I)
_SOURCE_SENTENCE_BOUNDARY=re.compile(r'(?<=[.!?])\s+')
_AMBIGUOUS_QUOTING=re.compile(r'["“”‘]|(?<!\w)[\'’]')
_AMBIGUOUS_ABBREVIATION=re.compile(r'\b(?:e\.g|i\.e|etc|vs|approx|no|fig|dr|mr|mrs|ms|inc|ltd|co)\.',re.I)
_DECLARATIVE_PREDICATE=re.compile(r'\b(?:is|are|was|were|has|have|had|reported|stated|'
    r'indicated|covered|found|identified|observed|confirmed|assessed|monitored|cited|believed|'
    r'rose|fell|increased|decreased|reflected|used|said|says|considered|reviewed|concerns?)\b',re.I)
_AMBIGUOUS_SUBJECT=re.compile(r'^(?:it|they|this|that|these|those|he|she|which|the former|the latter)\b',re.I)
_SOURCE_CONTEXT_FIELDS={'scope','description','quote','continuation_quotes'}
_SOURCE_AXIS_CATEGORY=re.compile(rf'\b(?P<count>{_CARDINAL_WORDS})-axis\s+'
    r'(?P<noun>[A-Za-z]+(?:-[A-Za-z]+)*)\b',re.I)
_COORDINATED_AXIS_CATEGORIES=re.compile(rf'\b(?P<count>{_CARDINAL_WORDS})-axis'
    r'(?P<shared>\s+and\s+(?P<other>[A-Za-z]+(?:-[A-Za-z]+)*)\s+'
    r'(?P<noun>[A-Za-z]+(?:-[A-Za-z]+)*))\b',re.I)
_STANDARD_IDENTIFIER=re.compile(r'\b(?:IAS|IFRS|HKAS|HKFRS)\s+(?P<number>\d{1,2})\b',re.I)
_STANDARD_REFERENCE=re.compile(r'\b(?P<prefix>(?:under|in\s+accordance\s+with|pursuant\s+to|according\s+to|'
    r'as\s+required\s+by|complies\s+with)\s+)?(?P<code>(?:IAS|IFRS|HKAS|HKFRS)\s+\d{1,2})\b',re.I)
_STANDARD_VALUATION_TAIL=re.compile(r'^(?:\s+|\s*:\s*)(?:lower[- ]of[- ]cost|'
    r'lower\s+cost(?=\s*/\s*NRV\b)|net\s+realizable\s+value|(?:impairment\s+)?test(?:s|ing)?)\b',re.I)
_STANDARD_MEASURE_TAIL=re.compile(r'^\s*(?:years?|months?|weeks?|days?|hours?|units?|'
    r'thousands?|millions?|billions?|percent(?:age)?|basis\s+points?)\b',re.I)
_PROOF_PAGE_PREFIX=re.compile(r'^(?:p\.|page)\s*(?P<page>[1-9]\d*)\s*:\s*',re.I)


def _split_reported_sentence_groups(sentences, *, assessment_prose=False):
    """Keep complete direct statements in their original order and scope."""
    if (not _SOURCE_SENTENCE_START.match(sentences[0])
            or any(not re.match(r'[A-Z]',sentence) or sentence[-1] not in '.!?'
                   or not (_SOURCE_SENTENCE_START.match(sentence) or _DECLARATIVE_PREDICATE.search(sentence)
                           or assessment_prose and re.search(r'\b(?:tested|judged)\b', sentence, re.I))
                   for sentence in sentences)):
        return None
    units=[sentences[0]]
    for sentence in sentences[1:]:
        if _AMBIGUOUS_SUBJECT.match(sentence):
            units[-1]+=' '+sentence
        else:
            units.append(sentence)
    groups=[units[0]]
    for sentence in units[1:]:
        extended=groups[-1]+' '+sentence
        if len(extended)<=700:
            groups[-1]=extended
        else:
            groups.append(sentence if _SOURCE_SENTENCE_START.match(sentence)
                          else 'Reports the following. '+sentence)
    return groups if all(len(group)<=700 for group in groups) else None


def split_source_description(description, *, assessment_prose=False):
    """Split an overlong description at safe, complete sentence boundaries."""
    if _AMBIGUOUS_QUOTING.search(description) or _AMBIGUOUS_ABBREVIATION.search(description):
        return None
    sentences=[part.strip() for part in _SOURCE_SENTENCE_BOUNDARY.split(description.strip())]
    if len(sentences)<2 or any(not sentence or len(sentence)>700 for sentence in sentences):
        return None
    if all(_SOURCE_SENTENCE_START.match(sentence) for sentence in sentences):
        return sentences
    if _SCOPED_SOURCE_ATTRIBUTION.match(sentences[0]):
        # Preserve the complete scoped statement under the rendered attribution.
        sentences[0]='Reports the following. '+sentences[0]
    if groups:=_split_reported_sentence_groups(sentences, assessment_prose=assessment_prose):
        return groups
    # Repeat an explicitly established company subject at the split boundary.
    matched=[_COMPANY_ATTRIBUTED_SENTENCE.fullmatch(sentence) for sentence in sentences]
    if (not all(matched) or matched[0]['speaker'].casefold()!='the company'
            or any(re.search(r'\bit\b',match['predicate'],re.I) for match in matched)):
        return None
    groups=[f"Reports that the company {match['verb']} {match['predicate']}" for match in matched]
    return groups if all(len(group)<=700 for group in groups) else None


def split_overlong_source_descriptions(items):
    """Keep each source scope and proof on every resulting description."""
    if not isinstance(items,list):
        return items
    expanded=[]
    changed=False
    for item in items:
        if not isinstance(item,dict) or set(item)-_SOURCE_CONTEXT_FIELDS:
            return items
        description=item.get('description')
        if not isinstance(description,str) or len(description)<=700:
            expanded.append(item)
            continue
        if not (split_sentences:=split_source_description(description)):
            return items
        for sentence in split_sentences:
            expanded.append({**item,'description':sentence})
        changed=True
    if not changed or len(expanded)>8:
        return items
    return expanded


def group_adjacent_source_context(items, *, max_items=8):
    """Free only the required slots by joining adjacent descriptions with identical evidence."""
    import json

    if not isinstance(items,list) or len(items)<=max_items:
        return items
    def owner(item):
        if (not isinstance(item,dict) or item.keys()-_SOURCE_CONTEXT_FIELDS
                or not isinstance(item.get('scope'),str) or not isinstance(item.get('quote'),dict)
                or not isinstance(item.get('description'),str) or len(item['description'])<10
                or not isinstance(item.get('continuation_quotes',[]),list)):
            return None
        return json.dumps([item['scope'],item['quote'],item.get('continuation_quotes',[])],
                          ensure_ascii=False,sort_keys=True)

    entries=[(item,owner(item)) for item in items]
    needed=len(entries)-max_items
    # First use joins that already fit a single description. If a longer
    # join is necessary, preserve it intact for the existing capacity request.
    for bounded in (True,False):
        joined=[]
        for item,key in entries:
            if needed and key is not None and joined and key==joined[-1][1]:
                prior=joined[-1][0]
                separator=' ' if prior['description'].rstrip().endswith(('.','!','?','。','！','？')) else '\n\n'
                description=prior['description']+separator+item['description']
                if not bounded or len(description)<=700:
                    joined[-1]=({**prior,'description':description},key)
                    needed-=1
                    continue
            joined.append((item,key))
        if not needed:
            return [item for item,_ in joined]
        entries=joined
    return items


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
        original=values
        quote=values.get('quote')
        if isinstance(quote,dict) and 'continuation_quotes' in quote:
            nested=quote['continuation_quotes'];existing=values.get('continuation_quotes',[])
            if (not isinstance(nested,list) or not isinstance(existing,list)
                    or (existing and existing!=nested)):
                return values
            # Move only this exact typed field; defer validation until after
            # bounded literal splitting. Unknown fields still fail on the
            # ordinary BriefQuote validation below.
            quote={k:v for k,v in quote.items() if k!='continuation_quotes'}
            values={**values,'quote':quote,'continuation_quotes':nested}
        continuations=values.get('continuation_quotes',[])
        if not isinstance(continuations,list):return values

        def flatten_typed_continuation(raw):
            """Move only the typed nested continuation field, preserving list order."""
            if not isinstance(raw,dict) or 'continuation_quotes' not in raw:
                return [raw]
            nested=raw['continuation_quotes']
            # One typed nesting level is enough for transport repair. Deeper
            # structures remain invalid input instead of triggering an
            # unbounded recursive walk over model-owned JSON.
            if (not isinstance(nested,list) or len(nested)>2 or any(
                    isinstance(child,dict) and 'continuation_quotes' in child for child in nested)):
                return None
            parent={key:value for key,value in raw.items() if key!='continuation_quotes'}
            return [parent,*nested]

        flattened_continuations=[]
        for continuation in continuations:
            parts=flatten_typed_continuation(continuation)
            if parts is None:
                # Leave the malformed payload untouched for Pydantic's
                # ordinary strict validation; never discard malformed proof.
                return original
            flattened_continuations.extend(parts)
            if len(flattened_continuations)>3:
                return original
        flattening_changed=flattened_continuations!=continuations
        continuations=flattened_continuations
        from adaptive_document_agent.services.source_quotes import split_literal_quote

        def split_quote(raw):
            if isinstance(raw,BriefQuote):
                raw=raw.model_dump(mode='json')
            if (not isinstance(raw,dict) or not isinstance(raw.get('text'),str)
                    or len(raw['text'])<=1800):
                return [raw]
            return [{**raw,'text':part} for part in split_literal_quote(raw['text'])]

        primary=split_quote(quote)
        continuation_parts=[]
        for continuation in continuations:
            continuation_parts.extend(split_quote(continuation))
        if (len(primary)==1 and len(continuation_parts)==len(continuations)
                and not flattening_changed):
            return values
        if len(continuation_parts)+len(primary)-1>3:
            return original
        return {**values,'quote':primary[0], 'continuation_quotes':[
            *primary[1:],*continuation_parts]}

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


def _description_without_owned_page_prefix(item):
    description=item.description.strip()
    match=_PROOF_PAGE_PREFIX.match(description)
    if match and any(str(quote.page)==match['page'] for quote in item.proof_quotes):
        body=description[match.end():]
        if len(body)>=10:
            return body
    return description


def qualified_source_scope(item):
    return re.sub(r'^(?:(?:For|In|During|Within)\s+)+','',item.scope.strip(),flags=re.I)


def qualified_source_statement(item):
    """Normalize grammar only; never rewrite the source quotation or its meaning."""
    scope=qualified_source_scope(item)
    description=_description_without_owned_page_prefix(item)
    prefix_removed=description!=item.description.strip()
    description=description[:1].lower()+description[1:]
    if prefix_removed and not _SOURCE_SENTENCE_START.match(description):
        description='reports that '+description
    return f'For {scope}, the source {description}'+('' if description.endswith(('.','!','?')) else '.')


def source_context_scope_prefixes(items,periods):
    """Share only exactly rendered scopes across already separate source items."""
    return {bound_period_dates(qualified_source_statement(item),periods):
        (item.scope,bound_period_dates(f'For {qualified_source_scope(item)}, ',periods)) for item in items}


def source_context_paragraphs(parts, *, scope_prefixes=None):
    """Pack adjacent statements into at most four audience paragraphs."""
    scoped=scope_prefixes or {}
    groups=[[part] for part in parts]
    while len(groups)>4:
        pairs=[(sum(map(len,left+right)),index) for index,(left,right) in enumerate(zip(groups,groups[1:]))
               if scoped.get(left[-1]) and scoped.get(left[-1])==scoped.get(right[0])]
        if not pairs:
            break
        _,index=min(pairs)
        groups[index:index+2]=[groups[index]+groups[index+1]]

    count=min(len(groups),4)
    paragraphs=[]
    for index in range(count):
        previous=None
        statements=[]
        for group in groups[index*len(groups)//count:(index+1)*len(groups)//count]:
            for statement in group:
                scope=scoped.get(statement)
                if scope and scope==previous and statement.startswith(scope[1]+'the source '):
                    statement='The source also '+statement[len(scope[1]+'the source '):]
                statements.append(statement)
                previous=scope
        paragraphs.append(' '.join(statements))
    return paragraphs


def _mask_source_axis_categories(text,proof):
    """Mask a worded axis count only when its adjacent product noun is literal."""
    if not proof:
        return text
    owned={}
    for match in _SOURCE_AXIS_CATEGORY.finditer(proof):
        count=match['count'].casefold()
        noun=match['noun'].casefold()
        owned.setdefault(count,set()).add(noun)

    def category_owned(count,noun):
        return any(noun==source or noun+'s'==source or source+'s'==noun
                   for source in owned.get(count,set()))

    def coordinated(match):
        noun=match['noun'].casefold()
        if not category_owned(match['count'].casefold(),noun):
            return match[0]
        other=match['other'].casefold()
        if other.endswith('-axis'):
            second_owned=category_owned(other.removesuffix('-axis'),noun)
        else:
            variants={noun,noun+'s',noun.removesuffix('s')}
            second_owned=any(re.search(r'(?<!\w)'+re.escape(other)+r'\s+'+re.escape(label)+r'(?![\w-])',
                                       proof,re.I) for label in variants)
        return ' '+match['shared'] if second_owned else match[0]

    def replace(match):
        return ' ' if category_owned(match['count'].casefold(),match['noun'].casefold()) else match[0]

    return _SOURCE_AXIS_CATEGORY.sub(replace,_COORDINATED_AXIS_CATEGORIES.sub(coordinated,text))


def _mask_source_standard_identifiers(text,proof):
    """Mask only an exact source-owned accounting-standard number in citation grammar."""
    if not proof:
        return text
    owned={' '.join(match[0].split()).casefold()
           for match in _STANDARD_IDENTIFIER.finditer(proof)}

    def replace(match):
        code=' '.join(match['code'].split()).casefold()
        tail=text[match.end():]
        if (code not in owned or _STANDARD_MEASURE_TAIL.match(tail)
                or not (match['prefix'] or _STANDARD_VALUATION_TAIL.match(tail))):
            return match[0]
        return match[0][:match.start('code')-match.start()]+' '*len(match['code'])

    return _STANDARD_REFERENCE.sub(replace,text)


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
    """Separate source-owned qualitative context and exact method parameters.

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
            from adaptive_document_agent.services.calendar_claims import mask_scoped_month_days
            from adaptive_document_agent.services.calendar_claims import mask_scoped_year_ranges
            from adaptive_document_agent.services.source_day_count import (
                literal_day_count_conventions, mask_day_count_conventions)
            from .source_context_periods import mask_reporting_period_references
            words=mask_reporting_period_references(words,proof,scope)
            words=mask_scoped_month_days(words,scope,proof)
            words=mask_scoped_year_ranges(words,scope,proof)
            words=_mask_source_standard_identifiers(words,proof)
            words=mask_day_count_conventions(words,literal_day_count_conventions(proof))
        if _QUANTITY.search(words):
            return False
        from adaptive_document_agent.services.source_duration_conditions import mask_worded_duration_conditions
        words=mask_worded_duration_conditions(words,source)
        labels_text=' '.join(labels).casefold()
        words=_LABEL_COMPOUND.sub(lambda m: ' ' if re.search(
            r'(?<!\w)'+re.escape(m[0])+r'(?!\w)',labels_text,re.I) else m[0],words)
        # A spelled axis count can be a literal product-category modifier.
        # Bind only the exact hyphenated count and adjacent noun to this item's
        # own proof; this does not authorize a measured count or model number.
        if proof is not None:
            words=_mask_source_axis_categories(words,proof)
        # “One of the/these/those …” is a qualitative partitive idiom, not a
        # count claim. Keep explicit following counts (e.g. “one of two”) intact.
        cardinal_text=re.sub(r'\bone\s+of(?=\s+(?:the|these|those)\b)',
                             'a member of',words,flags=re.I)
        return not _QUANTITY.search(cardinal_claim_text(cardinal_text))
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
        description=bound_period_dates(mask_source_periods(_description_without_owned_page_prefix(item),
            item.proof_text,periods=periods),periods,mask=True)
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
