"""Token usage and cost from provider responses, read by the gateway rather than reported by the harness.

The three harnesses speak different wire formats: Claude Code and dsh use the Anthropic Messages format,
Grok Build uses the OpenAI-style xAI API (chat completions or responses). Every format reports usage in a
"usage" object, but with different field names and different meanings for the input count:

- Messages: input_tokens excludes cache reads, which arrive separately as cache_read_input_tokens.
- Chat completions: prompt_tokens includes cached tokens (prompt_tokens_details.cached_tokens).
- Responses: input_tokens includes cached tokens (input_tokens_details.cached_tokens).

In a stream, usage is cumulative across events (Messages sends a partial count in message_start and the
final output count in message_delta), so the counts are merged by taking the maximum of each field.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass
class Usage:
    input: int = 0  # uncached input tokens
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    found: bool = False

    def merge(self, other: Usage) -> None:
        if not other.found:
            return
        self.found = True
        self.input = max(self.input, other.input)
        self.cache_read = max(self.cache_read, other.cache_read)
        self.cache_write = max(self.cache_write, other.cache_write)
        self.output = max(self.output, other.output)

    @property
    def prompt(self) -> int:
        return self.input + self.cache_read + self.cache_write


def normalize(u: dict) -> Usage:
    def n(key: str, source: dict | None = None) -> int:
        value = (source if source is not None else u).get(key)
        return value if isinstance(value, int) else 0

    if "input_tokens_details" in u:  # responses API
        cached = n("cached_tokens", u.get("input_tokens_details") or {})
        return Usage(n("input_tokens") - cached, cached, 0, n("output_tokens"), True)
    if "prompt_tokens" in u:  # chat completions
        cached = n("cached_tokens", u.get("prompt_tokens_details") or {})
        return Usage(n("prompt_tokens") - cached, cached, 0, n("completion_tokens"), True)
    if "input_tokens" in u or "output_tokens" in u:  # Anthropic Messages
        return Usage(n("input_tokens"), n("cache_read_input_tokens"), n("cache_creation_input_tokens"),
                     n("output_tokens"), True)
    return Usage()


def _usage_objects(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "usage" and isinstance(value, dict):
                yield value
            else:
                yield from _usage_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _usage_objects(item)


def payloads(body: bytes) -> Iterator[object]:
    """JSON documents in a response body: the body itself, or each `data:` line of a server-sent event stream."""
    text = body.decode("utf-8", errors="replace")
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue


def usage_from_body(body: bytes) -> Usage:
    total = Usage()
    for doc in payloads(body):
        for u in _usage_objects(doc):
            total.merge(normalize(u))
    return total


def model_from(docs: Iterable[object]) -> str | None:
    for doc in docs:
        if isinstance(doc, dict):
            model = doc.get("model") or (doc.get("message") or {}).get("model") or (doc.get("response") or {}).get("model")
            if isinstance(model, str):
                return model
    return None


def cost(usage: Usage, model: str | None, prices: dict) -> float | None:
    """USD cost, or None when the model has no price entry (the run is then reported as unpriced)."""
    p = prices.get(model or "")
    if p is None:
        # Providers may answer with a dated or suffixed id ("grok-build-0.1-20260901"); match on the prefix.
        p = next((v for k, v in prices.items() if model and model.startswith(k)), None)
    if p is None:
        return None
    long = p.get("long_context")
    if long and usage.prompt > long["above"]:
        p = {**p, **long}
    return (usage.input * p["input"] + usage.cache_read * p.get("cache_read", p["input"])
            + usage.cache_write * p.get("cache_write", p["input"]) + usage.output * p["output"]) / 1_000_000
