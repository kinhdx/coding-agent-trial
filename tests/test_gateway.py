from __future__ import annotations

import json

import httpx
from starlette.testclient import TestClient

from trial.gateway import Ledger, create_app


def upstream(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.dumps({"model": "claude-sonnet-5-5", "usage": {"input_tokens": 1000, "output_tokens": 100}})
        return httpx.Response(200, stream=httpx.ByteStream(body.encode()), headers={"content-type": "application/json"})
    return httpx.MockTransport(handler)


def test_key_is_injected_and_call_is_priced(tmp_path):
    seen: list[httpx.Request] = []
    ledger = Ledger(tmp_path, budget_usd=5)
    app = create_app(ledger, {"anthropic": "real-key"}, transport=upstream(seen))
    with TestClient(app) as client:
        r = client.post("/run-1/anthropic/v1/messages", json={"model": "claude-sonnet-5-5"},
                        headers={"x-api-key": "placeholder", "authorization": "Bearer placeholder"})
    assert r.status_code == 200
    assert seen[0].url == "https://api.anthropic.com/v1/messages"
    assert seen[0].headers["x-api-key"] == "real-key"
    assert "authorization" not in seen[0].headers
    entry = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    assert entry["run"] == "run-1" and entry["usage_found"] and entry["complete"]
    assert not entry["stream"] and not entry["stream_usage"]
    assert entry["cost_usd"] == (1000 * 2.0 + 100 * 10.0) / 1_000_000


def test_calls_are_refused_once_the_budget_is_spent(tmp_path):
    (tmp_path / "calls.jsonl").write_text(json.dumps({"cost_usd": 5.0}) + "\n", encoding="utf-8")
    seen: list[httpx.Request] = []
    app = create_app(Ledger(tmp_path, budget_usd=5), {"anthropic": "k"}, transport=upstream(seen))
    with TestClient(app) as client:
        r = client.post("/run-1/anthropic/v1/messages", json={})
    assert r.status_code == 429 and r.json()["error"]["type"] == "budget_exceeded"
    assert seen == []


def test_unconfigured_provider_is_rejected(tmp_path):
    app = create_app(Ledger(tmp_path, budget_usd=5), {"anthropic": "k", "xai": ""}, transport=upstream([]))
    with TestClient(app) as client:
        assert client.post("/run-1/xai/v1/responses", json={}).status_code == 404
        assert client.post("/run-1/openai/v1/x", json={}).status_code == 404
