"""PDF layout whitespace must not stall evidence validation or merge values."""

from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as Validator


@pytest.mark.parametrize(("text", "expected"), [
    ("USD 6M period; 6M2025", {"6", "2025"}),
    ("USD (6M) period; 9M2024", {"-6", "2024"}),
    ("(6M) USD; 12M2023", {"-6", "2023"}),
    ("USD −6M period; 3M2022", {"-6", "2022"}),
    ("6M USD; 9M period; FY2025", {"6", "2025"}),
    ("6M period; 9M ended; 12M2024", {"2024"}),
    ("Output 12\n345; 6M2025", {"12", "345", "2025"}),
    ("Output 12  345; 6M2025", {"12", "345", "2025"}),
])
def test_layout_whitespace_preserves_money_periods_and_separate_values(text, expected):
    assert Validator._numbers(text) == expected


def test_long_pdf_whitespace_finishes_in_a_bounded_subprocess():
    # Isolate the performance regression: the old C regex can hold the GIL,
    # so a thread timeout cannot reliably stop it and would hang the test run.
    # Ten seconds is deliberately generous for these small synthetic pages.
    script = textwrap.dedent("""
        from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as V

        for space in (" ", "\\t", "\\n", "\\u00a0"):
            gap = space * 20_000
            for text, expected in (
                ("Section" + gap + "End; 6M2025", {"2025"}),
                ("USD" + gap + "Unknown; 6M2025", {"2025"}),
                ("6M" + gap + "Unknown; 6M2025", {"6", "2025"}),
                ("USD" + gap + "6M period; 6M2025", {"6", "2025"}),
                ("(6M)" + gap + "USD; 6M2025", {"-6", "2025"}),
            ):
                assert V._numbers(text) == expected
            amount = "6M" + gap + "USD"
            spans = V._money_spans(amount)
            assert any(start == 0 and end == len(amount) for start, end in spans)
            assert V._money_spans(gap + "Unknown") == []
    """)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=10, check=True,
    )
