"""Explicit accepted direction fixtures for tests of unrelated source contracts.

These copy the test's scripted source verdict, not production semantic logic.
Adversarial direction tests supply independent responses instead.
"""
import json


def accepted_directions(messages, schema, verdicts):
    rows = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    by_index = {row['index']: row for row in verdicts}
    return schema.model_validate({'items': [dict(index=row['index'],
        comparisons=[dict(comparison_index=binding['comparison_index'], claim=binding['claim'],
            predicate=binding['claim'], direction=by_index[row['index']]['comparisons'][binding['comparison_index']]['direction'],
            absolute_magnitude=by_index[row['index']]['comparisons'][binding['comparison_index']].get('absolute_magnitude', False),
            reason='Explicit accepted direction fixture for a separate source/transport contract.')
            for binding in row['comparisons']], omitted_directional_claims=[])
        for row in rows]})
