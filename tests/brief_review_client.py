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
    def generate_text(self, messages, **kwargs):
        prefix = 'Return only JSON matching this schema: '
        if (messages and messages[0]['content'].startswith(prefix)
                and json.loads(messages[0]['content'][len(prefix):]).get('title') == 'BriefMeaningReview'):
            # The text transport owns max_tokens; MockLLMClient's structured
            # fixture only accepts its semantic temperature argument.
            _, response = self.generate_structured(messages[1:], BriefMeaningReview,
                **{k: v for k, v in kwargs.items() if k == 'temperature'})
            return response
        direction_start = next((i for i, message in enumerate(messages) if message['content'].startswith(
            'Independently read the DIRECTION ASSERTED BY AUDIENCE WORDS')), None)
        if direction_start is not None:
            from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
            from tests.brief_direction_fixture import accepted_directions
            self.calls.append(messages)
            value = accepted_directions(messages[direction_start:], BriefClaimDirectionReview, self._last_meaning_review['items'])
            return LLMResponse(text=value.model_dump_json(), usage=LLMUsage(provider='mock', model='mock'))
        return super().generate_text(messages, **kwargs)

    @property
    def editorial_calls(self):
        return [call for call in self.calls if not any(message['content'].startswith((
            'Independently review each supplied briefing claim',
            'Independently read the DIRECTION ASSERTED BY AUDIENCE WORDS')) for message in call)]

    def generate_structured(self, messages, response_model, **kwargs):
        if response_model.__name__ == 'BriefClaimDirectionReview':
            from tests.brief_direction_fixture import accepted_directions
            self.calls.append(messages)
            value = accepted_directions(messages, response_model, self._last_meaning_review['items'])
            return value, LLMResponse(text=value.model_dump_json(), usage=LLMUsage(provider='mock', model='mock'))
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
            value, response = super().generate_structured(messages, response_model, **kwargs)
            if response_model is BriefMeaningReview:
                self._last_meaning_review = value.model_dump(mode='json')
            return value, response
        self.calls.append(messages)
        content = messages[1]['content']
        rows = json.loads(content[content.index('['):content.rindex(']')+1])
        value = BriefMeaningReview(items=[dict(index=row['index'], accepted=True,
            reason='Independent accepted semantic fixture for source/transport test',
            numeric_comparison=False, comparisons=[]) for row in rows])
        self._last_meaning_review = value.model_dump(mode='json')
        return value, LLMResponse(text=value.model_dump_json(), usage=LLMUsage(provider='mock', model='mock'))
