"""Independent accepted-review fixture for tests focused on quoting/patch transport.

Explicit queued reviewer responses always take precedence, so adversarial
meaning and reviewer-failure tests still exercise their own supplied verdicts.
All calls remain in the real mock ledger; editorial_calls isolates the transport
being asserted by older quote/schema tests.
"""
import json

from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.mock import MockLLMClient
from adaptive_document_agent.services.llm.usage import LLMUsage


class BriefReviewClient(MockLLMClient):
    @property
    def editorial_calls(self):
        return [call for call in self.calls if not call[0]['content'].startswith('Independently review each supplied briefing claim')]

    def generate_structured(self, messages, response_model, **kwargs):
        next_response = self.responses[0] if self.responses else None
        invalid_string = False
        if isinstance(next_response, str):
            try:
                next_response = json.loads(next_response)
            except ValueError:
                invalid_string = True
        explicit_review = (isinstance(next_response, dict) and 'items' in next_response
            and (not next_response['items'] or 'accepted' in next_response['items'][0]))
        if response_model is not BriefMeaningReview or explicit_review or invalid_string:
            return super().generate_structured(messages, response_model, **kwargs)
        self.calls.append(messages)
        content = messages[1]['content']
        rows = json.loads(content[content.index('['):content.rindex(']')+1])
        value = BriefMeaningReview(items=[dict(index=row['index'], accepted=True,
            reason='Independent accepted semantic fixture for source/transport test',
            numeric_comparison=False, comparisons=[]) for row in rows])
        return value, LLMResponse(text=value.model_dump_json(), usage=LLMUsage(provider='mock', model='mock'))
