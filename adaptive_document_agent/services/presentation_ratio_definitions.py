"""Bind ratio copy to explicit source row footnotes, without inferring formulas.

Only explicit division definitions with a source-bound row marker are parsed.
Its footnote marker must belong to the selected ratio row on the same page.
Unknown definitions remain unknown; observations and model output stay intact.
"""

from __future__ import annotations

import json
import re
from math import isclose

from adaptive_document_agent.models import SourceEvidence, ValidationIssue
from adaptive_document_agent.document_model import period_sort_key
from .presentation_share_claims import share_direction_supported, source_row
from .presentation_evidence import ambiguous_source_table_ids, observation_uses_ambiguous_table


def _key(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def _literal_definitions(text, marker, label):
    """Parse literal division grammar; never supply a financial formula by name."""
    found = []
    pattern = (r"\(" + re.escape(marker) + r"\)\s*(?:"
               r"Calculated\s+by\s+dividing\s+|The\s+calculation\s+of\s+)"
               r".*?(?:\.(?!\d)|;|$)")
    for match in re.finditer(pattern, text, re.I | re.S):
        quote = " ".join(match[0].split())
        body = re.sub(r"^\(\d+\)\s*", "", quote).rstrip(".;")
        divided = re.fullmatch(r"Calculated by dividing (.+?) by (.+)", body, re.I)
        if divided:
            numerator, denominator = divided.groups()
        else:
            defined = re.fullmatch(r"The calculation of (.+?) is based on (.+?) divided by (.+)", body, re.I)
            if not defined or _key(defined[1]) != _key(label):
                continue
            numerator, denominator = defined[2], defined[3]
        multiplier = None
        scaled = re.fullmatch(r"(.+?) and multiplied by (\d+(?:\.\d+)?)%?", denominator, re.I)
        if scaled:
            # Percent observations can use only a literally stated 100 factor.
            # Other multipliers need an explicit representation contract.
            if float(scaled[2]) != 100:
                continue
            denominator, multiplier = scaled[1], 100
        if not numerator or not denominator or max(len(numerator), len(denominator)) > 180:
            continue
        found.append((match.start(), numerator, denominator, quote, multiplier))
    return found


def ratio_definitions(result):
    """Return row-bound literal definitions, not semantic guesses from percentages."""
    pages = {p.page_number: p.text for p in result.document.pages}
    ambiguous = ambiguous_source_table_ids(result)
    found = {}
    # Parse once per source row, even when the row contains many periods.
    rows = {}
    for item in result.observations:
        if (item.unit not in {"percent", "percentage", "%"}
                or item.validation_status != "valid"
                or observation_uses_ambiguous_table(item, ambiguous)):
            continue
        for evidence in item.evidence:
            if (evidence.row_label and item.effective_table_id
                    and evidence.table_id in {None, item.effective_table_id}):
                rows.setdefault((evidence.page, item.effective_table_id, evidence.row_label), []).append(item.id)
    for (page, table, label), ids in rows.items():
        text = pages.get(page, "")
        label_pattern = r"\s+".join(re.escape(word) for word in label.split())
        anchors = list(re.finditer(r"^[ \t]*" + label_pattern + r"\s*\((\d+)\)", text, re.I | re.M))
        if len(anchors) != 1:
            continue
        anchor = anchors[0]
        definitions = _literal_definitions(text[anchor.end():], anchor[1], label)
        if len(definitions) != 1:
            continue
        definition = definitions[0]
        intervening = text[anchor.end():anchor.end() + definition[0]]
        if re.search(r"\(" + re.escape(anchor[1]) + r"\)", intervening):
            # Footnote numbers restart between tables. The later row must not
            # lend its definition to an earlier table's same-number marker.
            continue
        _, numerator, denominator, quote, multiplier = definition
        found[(page, table, label)] = {
            "metric": label, "numerator": numerator, "denominator": denominator,
            "page": page, "table_id": table, "quote": quote,
            "observation_ids": list(dict.fromkeys(ids)),
        }
        if multiplier is not None:
            found[(page, table, label)]["multiplier"] = multiplier
    return list(found.values())


_RATIO_TO = re.compile(
    r"\b(ratio\s+to\s+)([\w -]+?)(?=\s+(?:declined|increased|decreased|rose|fell|"
    r"grew|dropped|expanded|contracted|was|is|remained)\b|[.,;!?]|$)", re.I)
_PERCENT_OF = re.compile(r"\b(?:as\s+)?(?:a\s+)?percentage\s+of\s+([\w -]+?)(?=\s+and\b|[.,;!?]|$)", re.I)


def _bound_subject(text, definition, *, term="ratio"):
    """Accept a literal source label or its explicit preceding-clause subject."""
    metric = re.sub(r"\s+ratio\b.*$", "", definition["metric"], flags=re.I)
    numerator = definition["numerator"]

    def source_phrase(phrase):
        # Expand only initialisms mechanically present in the source label,
        # e.g. A&B for the source words 'alpha and beta'. No metric alias list.
        for left, right in re.findall(r"(\w+)\s+and\s+(\w+)", numerator, re.I):
            phrase = re.sub(r"\b" + left[0] + r"\s*&\s*" + right[0] + r"\b",
                            left + " and " + right, phrase, flags=re.I)
        key = _key(re.sub(r"^(?:the|a|an)\s+", "", phrase.strip(), flags=re.I))
        return key == _key(metric) or (len([w for w in key.split() if w != "and"]) >= 2
                                      and f" {key} " in f" {_key(numerator)} ")

    ratio = re.search(r"\b" + re.escape(term) + r"\b", text, re.I)
    if ratio is None:
        return False
    clauses = re.split(r"[.;,]|\b(?:while|whereas)\b", text[:ratio.start()], flags=re.I)
    prefix = clauses[-1].strip()
    if prefix.casefold() in {"the", "this", "the reported", "reported"}:
        return True  # One unambiguous selected ratio, without a second named subject.
    if prefix.casefold() == "its" and len(clauses) > 1:
        antecedent = re.split(r"\s+(?:rose|grew|fell|increased|decreased|declined|expanded|contracted)\b",
                              clauses[-2].strip(), maxsplit=1, flags=re.I)
        return len(antecedent) == 2 and source_phrase(antecedent[0])
    return source_phrase(prefix)


_POSSESSIVE_SHARE = re.compile(
    r"\b(?:while|whereas)\s+its\s+share\s+of\s+(?:the\s+)?"
    r"(?P<denominator>.+?)\s+"
    r"(?P<direction>rose|fell|grew|increased|decreased|declined|expanded|contracted)\b",
    re.I,
)


def source_defined_possessive_share(text, selected, visible, eligible, definitions):
    """Validate one possessive share against a literal ratio footnote and its rows.

    The reported ratio, numerator and denominator must all be selected, visible
    where applicable, unique by period and arithmetically consistent. This
    cannot turn an unrelated percentage into a claimed share.
    """
    matches = list(_POSSESSIVE_SHARE.finditer(text))
    if len(matches) != 1 or len(re.findall(r"\bshare\b", text, re.I)) != 1:
        return []
    match = matches[0]
    selected_ids = {item.id for item in selected}
    visible_ids = {item.id for item in visible}
    eligible_ids = {item.id for item in eligible}
    percentage_ids = {item.id for item in selected if item.unit in {"percent", "percentage", "%"}}
    supported = []
    for definition in definitions:
        ratio_ids = set(definition["observation_ids"])
        source_denominator = _key(definition["denominator"])
        stated_denominator = _key(match["denominator"])
        denominator_matches = (stated_denominator == source_denominator or (
            source_denominator.startswith("annual ")
            and stated_denominator == source_denominator.removeprefix("annual ")
            and all(item.period_type == "fiscal_year" for item in selected if item.id in ratio_ids)
        ))
        if (not ratio_ids or percentage_ids != ratio_ids or not ratio_ids <= visible_ids & eligible_ids
                or not denominator_matches
                or not _bound_subject(text, definition, term="share")):
            continue
        rows = {}
        for label in ("numerator", "denominator"):
            grouped = {}
            for item in selected:
                if (item.id in eligible_ids and item.unit not in {"percent", "percentage", "%"}
                        and _key(source_row(item)) == _key(definition[label])):
                    grouped.setdefault(item.period, []).append(item)
            rows[label] = grouped
        ratios = sorted((item for item in selected if item.id in ratio_ids),
                        key=lambda item: period_sort_key(item.period))
        if len(ratios) < 2 or len({item.period for item in ratios}) != len(ratios):
            continue
        if not share_direction_supported(ratios, match.group()):
            continue
        for ratio in ratios:
            numerator = rows["numerator"].get(ratio.period, [])
            denominator = rows["denominator"].get(ratio.period, [])
            if (len(numerator) != 1 or len(denominator) != 1 or denominator[0].value == 0
                    or numerator[0].unit != denominator[0].unit
                    or numerator[0].currency != denominator[0].currency
                    or numerator[0].entity != denominator[0].entity
                    or numerator[0].period_type != denominator[0].period_type
                    or numerator[0].period_basis != denominator[0].period_basis):
                break
            decimal = re.search(r"\.(\d+)", ratio.raw_value or "")
            tolerance = 0.5 * 10 ** (-len(decimal[1])) if decimal else 0.5
            if not isclose(100 * numerator[0].value / denominator[0].value,
                           ratio.value, rel_tol=0, abs_tol=tolerance + 1e-6):
                break
        else:
            supported.append(ratios)
    return supported[0] if len(supported) == 1 else []


def _rewrite(text, definition, known_labels):
    """Replace an explicit ratio denominator only within a single bound ratio."""
    denominator = definition["denominator"]
    caption = f"Ratio denominator: {denominator} (see source pages)."
    text = reconcile_missing_definition(text, definition)
    if len(re.findall(r"\bratios?\b", text, re.I)) > 1:
        return text
    if re.search(r"\bratio\b", text, re.I) and not _bound_subject(text, definition):
        return text
    matches = list(_RATIO_TO.finditer(text))
    if matches:
        labels = {_key(label) for label in known_labels}
        return _RATIO_TO.sub(lambda m: m[1] + denominator
                            if _key(m[2]) in labels and _key(m[2]) != _key(denominator) else m[0], text)
    if re.search(r"\bratio\b", text, re.I) and any(
            _key(m[1]) != _key(denominator) for m in _PERCENT_OF.finditer(text)):
        # A caveat may contain a negated second denominator. Retain the full
        # original in the audit; do not patch individual words into a false caveat.
        return caption
    for label in known_labels:
        if _key(label) == _key(denominator):
            continue
        pattern = r"\b" + re.escape(label) + r"\s+intensity\b"
        if re.search(pattern, text, re.I):
            return caption
    return text


_MISSING_DEFINITION = re.compile(
    r"\b(?:source\s+)?(?:denominator|definition|formula)\s+(?:is\s+|was\s+)?"
    r"(?:not\s+(?:supplied|provided|disclosed|available|defined|specified)|unknown|unavailable)\b", re.I)


def reconcile_missing_definition(text, definition):
    """Replace only an explicit absence claim for the bound metric, preserving other caveats."""
    if not _MISSING_DEFINITION.search(text):
        return text
    # A literal metric name (or an unqualified standalone absence clause) is
    # required. Another named measure must not borrow this definition.
    denial = _MISSING_DEFINITION.search(text)
    prefix = text[:denial.start()].strip(" ;,.")
    prefix = re.sub(r"^(?:reported|source|the)\s+", "", _key(prefix))
    prefix = re.sub(r"\s+only$", "", prefix)
    if prefix and prefix != _key(definition["metric"]):
        return text
    replacement = (f"Source definition for {definition['metric']}: numerator {definition['numerator']}; "
                   f"denominator {definition['denominator']}")
    return _MISSING_DEFINITION.sub(replacement, text)


def prepare_topic_ratio_definitions(selection, lookup, result):
    """Supply source definitions before theme compilation, retaining original model caveats."""
    definitions = ratio_definitions(result)
    for topic in selection.topics:
        ids = {item.id for sid in topic.series_ids for item in lookup.get(sid, [])}
        bound = [d for d in definitions if ids.intersection(d["observation_ids"])]
        for definition in bound:
            original = list(topic.caveats)
            topic.caveats = [reconcile_missing_definition(text, definition)
                            if len(bound) == 1 or _key(definition["metric"]) in _key(text) else text
                            for text in original]
            if topic.caveats == original:
                continue
            message = json.dumps({"topic_id": topic.id, "original_caveats": original,
                                  "display_caveats": topic.caveats, "definition": definition}, ensure_ascii=False)
            if not any(w.code == "presentation_topic_definition" and w.message == message
                       for w in result.validation_warnings):
                result.validation_warnings.append(ValidationIssue(
                    code="presentation_topic_definition", stage="presentation", severity="info",
                    message=message, related_ids=[topic.id, *definition["observation_ids"]],
                    evidence=[SourceEvidence(page=definition["page"], table_id=definition["table_id"],
                        row_label=definition["metric"], text=definition["quote"],
                        extraction_method="explicit_ratio_footnote", confidence=1.0)],
                ))


def prepare_presentation_ratio_definitions(result, plan=None):
    """Correct display copy and keep literal definitions and original copy in audit."""
    plan = plan or result.presentation_plan
    if plan is None:
        return []
    definitions = ratio_definitions(result)
    charts = {c.id: c for c in result.charts}
    observations = {o.id: o for o in result.observations}
    themes = {t.id: t for t in plan.themes}
    known_labels = {o.metric_original for o in result.observations if o.metric_original}
    notes, replacements = [], {}
    for slide in plan.slides:
        if slide.slide_type != "analysis":
            continue
        ids = set(slide.observation_ids)
        for cid in [*slide.chart_ids, *(cid for b in slide.visual_blocks for cid in b.chart_ids)]:
            if cid in charts:
                ids.update(charts[cid].observation_ids)
        ids.update(oid for b in slide.visual_blocks for oid in b.observation_ids)
        bound = [d for d in definitions if ids.intersection(d["observation_ids"])]
        # A sentence with several ratios needs model-resolved subject binding.
        if len(bound) != 1:
            continue
        definition = bound[0]
        rate_ids = {oid for oid in ids if oid in observations
                    and observations[oid].unit in {"percent", "percentage", "%"}}
        if not rate_ids <= set(definition["observation_ids"]):
            # A second percentage series must not borrow this row's footnote.
            continue
        changes = {}
        theme = themes.get(slide.theme_id)
        for target, fields, prefix in (
            (slide, ("title", "message", "analytical_question", "selection_reason"), "slide"),
            (theme, ("question", "rationale"), "theme"),
        ):
            if target is None:
                continue
            for field in fields:
                original = getattr(target, field)
                revised = _rewrite(original, definition, known_labels)
                if revised != original:
                    changes[prefix + "." + field] = {"original": original, "display": revised}
                    replacements[original] = revised
                    setattr(target, field, revised)
        if theme:
            original = list(theme.caveats)
            theme.caveats = list(dict.fromkeys(_rewrite(c, definition, known_labels) for c in original))
            if theme.caveats != original:
                changes["theme.caveats"] = {"original": original, "display": theme.caveats}
        if not changes:
            continue
        message = json.dumps({"slide_id": slide.id, "definition": definition, "changes": changes},
                             ensure_ascii=False, sort_keys=True)
        if not any(w.code == "presentation_ratio_definition" and w.message == message for w in result.validation_warnings):
            result.validation_warnings.append(ValidationIssue(
                code="presentation_ratio_definition", stage="presentation", severity="info", message=message,
                related_ids=[slide.id, *definition["observation_ids"]],
                evidence=[SourceEvidence(page=definition["page"], table_id=definition["table_id"],
                                         row_label=definition["metric"], text=definition["quote"],
                                         extraction_method="explicit_ratio_footnote", confidence=1.0)],
            ))
        notes.append(f"Bound ratio denominator to the explicit source definition on p. {definition['page']} for {slide.id}.")
    for slide in plan.slides:
        slide.bullets = [replacements.get(text, text) for text in slide.bullets]
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *notes]))
    return notes
