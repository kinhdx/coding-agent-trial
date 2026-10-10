from __future__ import annotations

import json

import pytest
import yaml

from trial.gateway import PRICES
from trial.usage import Usage, cost, usage_from_body


def sse(*events: dict) -> bytes:
    return "".join(f"event: x\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def test_anthropic_stream_merges_start_and_delta():
    body = sse({"type": "message_start", "message": {"model": "claude-sonnet-5-5", "usage": {
                   "input_tokens": 120, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 500,
                   "output_tokens": 1}}},
               {"type": "content_block_delta", "delta": {"text": "hi"}},
               {"type": "message_delta", "usage": {"output_tokens": 340}})
    assert usage_from_body(body) == Usage(120, 3000, 500, 340, True)


def test_chat_completions_counts_cached_tokens_inside_prompt_tokens():
    body = sse({"choices": [{"delta": {"content": "x"}}]},
               {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 50,
                                         "prompt_tokens_details": {"cached_tokens": 800}}})
    body += b"data: [DONE]\n\n"
    assert usage_from_body(body) == Usage(200, 800, 0, 50, True)


def test_responses_api_completed_event():
    body = sse({"type": "response.created", "response": {"usage": None}},
               {"type": "response.completed", "response": {"model": "grok-build-0.1", "usage": {
                   "input_tokens": 900, "output_tokens": 70, "input_tokens_details": {"cached_tokens": 600}}}})
    assert usage_from_body(body) == Usage(300, 600, 0, 70, True)


def test_plain_json_body_and_missing_usage():
    assert usage_from_body(json.dumps({"usage": {"input_tokens": 5, "output_tokens": 2}}).encode()).found
    assert not usage_from_body(b'{"data": []}').found
    assert not usage_from_body(b"not json").found


def test_cost_uses_cache_rates_and_long_context_tier():
    prices = yaml.safe_load("""
m: {input: 1.0, cache_read: 0.2, output: 2.0, long_context: {above: 200000, input: 2.0, cache_read: 0.4, output: 4.0}}
""")
    assert cost(Usage(200_000, 0, 0, 0, True), "m", prices) == pytest.approx(0.2)
    assert cost(Usage(100_000, 50_000, 0, 10_000, True), "m", prices) == pytest.approx(0.1 + 0.01 + 0.02)
    assert cost(Usage(150_000, 100_000, 0, 0, True), "m", prices) == pytest.approx(0.3 + 0.04)
    assert cost(Usage(1, 0, 0, 0, True), "m-20260901", prices) is not None
    assert cost(Usage(1, 0, 0, 0, True), "unknown", prices) is None


def test_every_trial_model_has_a_price():
    for model in ("claude-sonnet-5-5", "grok-build-0.1", "deepseek-v4-pro"):
        assert model in PRICES
