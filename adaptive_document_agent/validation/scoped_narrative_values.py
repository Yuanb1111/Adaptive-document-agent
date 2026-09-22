"""Detect explicit endpoint values borrowed from a differently named measure.

This is a conservative provenance check, not a semantic synonym engine. The
model owns labels and meaning; exact retained labels bind an explicit from/to
amount. A number elsewhere on the slide is not evidence for that measure.
"""

from decimal import Decimal, InvalidOperation
import re

from adaptive_document_agent.models import Observation, PresentationSlide


_AMOUNT = re.compile(
    r"\b(?:from|to)\s+(?:(?:[A-Z]{3}|[$€£¥])\s*)?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<scale>thousand|million|billion|bn|[kmb])?(?!\w)", re.IGNORECASE)
_SCALES = {"": 1, "k": 1000, "thousand": 1000, "m": 1_000_000,
           "million": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000,
           "billion": 1_000_000_000}


def _number(value):
    try:
        return abs(Decimal(str(value).strip().replace(",", "").strip("()")))
    except InvalidOperation:
        return None


def scoped_value_errors(slide: PresentationSlide, observations: list[Observation],
                        label_catalog: list[Observation] | None = None) -> list[str]:
    by_label: dict[str, list[Observation]] = {}
    selected_ids = {o.id for o in observations}
    for obs in label_catalog if label_catalog is not None else observations:
        for label in (obs.metric_original, obs.metric_canonical, obs.presentation_label):
            if label:
                label = " ".join(label.replace("_", " ").casefold().split())
                variants = {label}
                for match in re.finditer(r"\b(\w+)/(\w+)\b", label):
                    variants.update(label[:match.start()] + option + label[match.end():] for option in match.groups())
                for variant in variants:
                    group = by_label.setdefault(variant, [])
                    if obs.id in selected_ids:
                        group.append(obs)
    errors = []
    for component in [slide.title, slide.message, *slide.bullets]:
        # Preserve decimal points and split only definite statement boundaries.
        for clause in re.split(r";|\n|,?\s+\b(?:but|while|whereas)\b\s+|(?<=[.!?])\s+(?=[A-Z])", component):
            matches = []
            for label in by_label:
                pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in label.split()) + r"(?!\w)"
                matches.extend((m.start(), m.end(), label) for m in re.finditer(pattern, clause, re.IGNORECASE))
            selected = []
            for match in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0])):
                if not any(match[0] < old[1] and match[1] > old[0] for old in selected):
                    selected.append(match)
            selected.sort()
            for idx, (_, end, label) in enumerate(selected):
                segment = clause[end:selected[idx + 1][0] if idx + 1 < len(selected) else len(clause)]
                named = by_label[label]
                for amount in _AMOUNT.finditer(segment):
                    scale = (amount.group("scale") or "").casefold()
                    number = _number(amount.group("number")) * _SCALES[scale]
                    def supports(obs):
                        # Explicit scale uses normalized values; otherwise also
                        # allow the exact source-unit display, never a guessed scale.
                        return number == _number(obs.value) or (not scale and number == _number(obs.raw_value))
                    if any(supports(o) for o in named):
                        continue
                    owners = [o for o in observations if supports(o) and o not in named]
                    if owners:
                        errors.append(f"slide {slide.id}: '{label}' uses endpoint {amount.group(0)!r} supported by another metric, not its own retained values. Preserve the metric definition and revise the claim.")
    return list(dict.fromkeys(errors))
