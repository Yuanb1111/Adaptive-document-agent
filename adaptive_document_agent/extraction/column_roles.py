"""Evidence rules for percentage columns, shared by reconstruction and extraction.

Position and numeric magnitude alone never establish a percentage unit.
"""

import re

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric, is_financial_statement_metric


def explicit_percentage(text: str | None) -> bool:
    """Recognise unit/ratio wording without matching e.g. shareholders or rates payable."""
    text = (text or "").casefold()
    if re.search(r"%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)", text):
        return False
    marked = bool(re.search(
        r"[%％]|\b(?:percent(?:age)?|pct|margin|proportion)\b"
        r"|\b(?:tax|growth|interest)\s+rate\b"
        r"|占比|份额|比例|毛利率|利润率", text
    ))
    # A share header can identify a ratio, but monetary allocations also use
    # "share of". The wording alone cannot override monetary source units.
    share_header = bool(re.search(r"\bshare(?:\s+of\b|\s*$)", text))
    return marked or (share_header and not is_financial_statement_metric(text))


def intrinsic_percentage(metric: str) -> bool:
    """Use the metric's own semantics, without inherited table units."""
    return classify_metric(metric).is_percentage


def percentage_column(header: str, cells: list[str | None]) -> bool:
    """Require a header or consistently marked cells, never adjacent amounts.

    Mixed amount/ratio rows share year columns. A majority vote would propagate
    a synthetic percent header onto the remaining monetary rows; individual
    marked cells and intrinsic ratios are still handled during extraction.
    """
    nonempty = [cell for cell in cells if cell and cell.strip() not in {"-", "—", "–"}]
    return explicit_percentage(header) or bool(
        nonempty and all(explicit_percentage(cell) for cell in nonempty)
    )
