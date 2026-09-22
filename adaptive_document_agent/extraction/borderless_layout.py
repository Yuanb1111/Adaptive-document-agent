"""Local geometric evidence for borderless tables; no value-based column guesses."""

from dataclasses import dataclass, field
import re
from statistics import median


@dataclass
class SourceLine:
    text: str
    spans: list[tuple[int, int, float, float]] = field(default_factory=list)
    top: float | None = None
    bottom: float | None = None

    def bounds(self, start: int, end: int) -> tuple[float, float] | None:
        words = [s for s in self.spans if s[0] < end and s[1] > start]
        if words:
            return min(s[2] for s in words), max(s[3] for s in words)
        # Preserved fixed-layout text can also supply column coordinates. A
        # collapsed prose line cannot: its character offsets are not geometry.
        if not self.spans and re.search(r"\S {2,}\S", self.text):
            return float(start), float(end)
        return None


def source_lines(page: object, text: str, clean) -> list[SourceLine]:
    if hasattr(page, "extract_words"):
        try:
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
        except (AttributeError, TypeError, ValueError):
            words = []
        if words:
            groups: list[list[dict]] = []
            for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
                if not groups or abs(word["top"] - groups[-1][0]["top"]) > 3:
                    groups.append([])
                groups[-1].append(word)
            result = []
            for group in groups:
                pieces, spans, offset = [], [], 0
                for word in sorted(group, key=lambda w: w["x0"]):
                    token = clean(word["text"])
                    if not token:
                        continue
                    pieces.append(token)
                    spans.append((offset, offset+len(token), float(word["x0"]), float(word["x1"])))
                    offset += len(token)+1
                result.append(SourceLine(" ".join(pieces), spans, min(w["top"] for w in group), max(w["bottom"] for w in group)))
            return result
    return [SourceLine(line) for line in text.splitlines()]


def column_anchors(full_rows: list[list[tuple[float, float]]], width: int):
    """Require stable right edges in at least two complete rows."""
    rows = [r for r in full_rows if len(r) == width]
    if len(rows) < 2:
        return None
    edges = [median(r[c][1] for r in rows) for c in range(width)]
    gap = min((b-a for a, b in zip(edges, edges[1:])), default=0)
    if gap <= 0 or any(median(abs(r[c][1]-edges[c]) for r in rows) > gap*.18 for c in range(width)):
        return None
    centers = [median((r[c][0]+r[c][1])/2 for r in rows) for c in range(width)]
    return edges, centers, gap


def is_wrapped_label(prefix: SourceLine, row: SourceLine, value_boxes) -> bool:
    """Use a close hanging indent in the label column, never metric keywords.

    Section headings/bulleted children are not wrapped labels. Without source
    coordinates keep the existing conservative text-only interpretation.
    """
    if not prefix.spans or not row.spans or not value_boxes:
        return False
    if any(v is None for v in (prefix.top, prefix.bottom, row.top)):
        return False
    if (prefix.text.rstrip().endswith((":", "：")) or prefix.text.isupper()
            or re.match(r"^[–—•-]\s+", row.text)):
        return False
    height = prefix.bottom - prefix.top
    gap = row.top - prefix.bottom
    prefix_left = min(s[2] for s in prefix.spans)
    row_left = min(s[2] for s in row.spans)
    prefix_right = max(s[3] for s in prefix.spans)
    data_left = min(box[0] for box in value_boxes)
    return (height > 0 and 0 <= gap <= height * .5
            and height * .25 < row_left - prefix_left < height * 2
            and prefix_right < data_left)


def align_sparse_values(values: list[str], boxes, anchors, width: int):
    if not anchors or len(boxes) != len(values):
        return None
    edges, _, gap = anchors
    result: list[str | None] = [None] * width
    for value, (_, right) in zip(values, boxes):
        candidates = [i for i, edge in enumerate(edges) if abs(edge-right) <= gap*.3]
        if len(candidates) != 1 or result[candidates[0]] is not None:
            return None
        result[candidates[0]] = value
    return result


def geometric_headers(lines: list[SourceLine], anchors, fallback: list[str]) -> list[str]:
    """Assign actual header words to evidenced column centers, not word order."""
    if not anchors or not any(line.spans for line in lines):
        return fallback
    _, centers, gap = anchors
    columns: list[list[str]] = [[] for _ in centers]
    units: list[str | None] = [None] * len(centers)
    for line in lines:
        if re.search(r"(?i)except|thousands?|millions?|unaudited|audited", line.text):
            continue
        # Keep a multi-word heading together (e.g. '% of Total'). Its '%' may
        # start near the preceding amount column even though the phrase is
        # centered over the percentage column. Assigning words individually
        # would move that symbol onto the wrong measure.
        phrases: list[tuple[int, int, float, float]] = []
        for start, end, left, right in line.spans:
            if phrases and 0 <= left-phrases[-1][3] <= min(gap*.18, 8):
                first, _, phrase_left, _ = phrases[-1]
                phrases[-1] = first, end, phrase_left, right
            else:
                phrases.append((start, end, left, right))
        for start, end, left, right in phrases:
            word = line.text[start:end]
            center = (left+right)/2
            index = min(range(len(centers)), key=lambda i: abs(centers[i]-center))
            if abs(centers[index]-center) > gap*.55:
                continue
            plain = word.strip("()")
            if re.fullmatch(r"(?i)RMB|CNY|USD|HKD|EUR|GBP|\$|£|€|¥", plain):
                units[index] = "amount"
            elif plain in {"%", "％"}:
                units[index] = "percentage"
            elif re.fullmatch(r"[%A-Za-z][%A-Za-z/ -]*", word):
                columns[index].append(word)
    output = []
    for i, words in enumerate(columns):
        label = " ".join(words)
        if units[i] == "amount" and re.search(r"%|\bmargin\b|percent", label, re.I):
            # Conflicting header geometry: use only the independently evidenced
            # unit, not a semantically contaminated measure name.
            label = "Amount"
        elif units[i] == "percentage" and not re.search(r"%|\bmargin\b|percent|share|ratio", label, re.I):
            label = f"% {label}" if label.casefold().startswith("of ") else f"% of {label}" if label else "%"
        output.append(label or ("Amount" if units[i] == "amount" else "%" if units[i] == "percentage" else fallback[i]))
    return output
