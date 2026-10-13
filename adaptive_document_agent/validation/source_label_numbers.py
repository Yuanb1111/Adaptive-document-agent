"""Keep literal source-label annotations out of quantitative claim checks."""
import re


def without_source_label_annotations(text, observations):
    """Remove parenthesized digits only inside an exact retained metric label.

    This does not authorize the annotation number as an amount elsewhere and
    does not alter source records or the text seen by semantic claim validation.
    """
    labels = {label for item in observations
              for label in [item.metric_original, *(e.row_label for e in item.evidence)]
              if label and re.search(r'[A-Za-z\u4e00-\u9fff]', label)
              and re.search(r'\(\d+\)', label)}
    # Chart labels omit source list bullets; the metric words and annotation
    # must still match literally. Do not strip signs or numeric prefixes.
    labels.update(label.lstrip(' •·▪◦') for label in list(labels))
    for label in sorted(labels, key=len, reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(label) + r'(?!\w)',
                      lambda match: re.sub(r'\(\d+\)', '', match[0]), text, flags=re.I)
    return text
