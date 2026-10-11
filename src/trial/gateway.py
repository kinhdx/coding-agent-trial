"""Egress gateway: the only process that holds API keys and the only route from a sandbox to the internet.

Sandboxes sit on an internal Docker network with no default route. Each harness is pointed at
http://gateway:8080/<run_id>/<provider>/..., gets a placeholder key, and the gateway:

- replaces the placeholder with the real key for that provider and forwards the request upstream,
- reads token usage from the response body, prices it, and appends one line per call to the ledger,
- refuses new model calls once the ledger total reaches the budget.

Port 3128 is an HTTP proxy for everything else (sandboxes get HTTPS_PROXY pointing at it, with the run id
as the proxy user name). It tunnels only hosts on the allowlist and records every attempt, so a harness that
tries to reach the internet shows up in the results instead of failing silently on DNS.

    uv run python -m trial.gateway        (env: ANTHROPIC_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY, BUDGET_USD,
                                            LEDGER_DIR, EGRESS_ALLOW)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

import httpx
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from trial.usage import cost, model_from, payloads, usage_from_body

UPSTREAMS = {
    # provider: (base URL, header that carries the key, key format, environment variable)
    "anthropic": ("https://api.anthropic.com", "x-api-key", "{}", "ANTHROPIC_API_KEY"),
    "xai": ("https://api.x.ai", "authorization", "Bearer {}", "XAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/anthropic", "x-api-key", "{}", "DEEPSEEK_API_KEY"),
}
# Hop-by-hop and credential headers are never copied from the sandbox request.
DROP_HEADERS = {"host", "content-length", "connection", "authorization", "x-api-key", "accept-encoding",
                "transfer-encoding", "proxy-authorization"}
PRICES = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "prices.yaml").read_text(encoding="utf-8"))


class Ledger:
    def __init__(self, folder: Path, budget_usd: float) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.calls = folder / "calls.jsonl"
        self.egress = folder / "egress.jsonl"
        self.budget = budget_usd
        self.spent = sum(json.loads(line).get("cost_usd") or 0 for line in self._lines(self.calls))

    @staticmethod
    def _lines(path: Path) -> list[str]:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []

    def record(self, path: Path, entry: dict) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.spent += entry.get("cost_usd") or 0


def create_app(ledger: Ledger, keys: dict[str, str], transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30), transport=transport)

    async def forward(request: Request) -> Response:
        run_id, provider, rest = request.path_params["run"], request.path_params["provider"], request.path_params["rest"]
        if provider not in UPSTREAMS or not keys.get(provider):
            return JSONResponse({"error": f"provider {provider!r} is not configured"}, status_code=404)
        if ledger.spent >= ledger.budget:
            return JSONResponse({"type": "error", "error": {"type": "budget_exceeded", "message":
                                 f"trial budget of {ledger.budget} USD is spent"}}, status_code=429)
        base, header, fmt, _ = UPSTREAMS[provider]
        headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_HEADERS}
        headers[header] = fmt.format(keys[provider])
        headers["accept-encoding"] = "identity"  # the body is relayed byte for byte and parsed for usage
        body = await request.body()
        url = f"{base}/{rest}" + (f"?{request.url.query}" if request.url.query else "")
        started = time.monotonic()
        upstream = await client.send(client.build_request(request.method, url, headers=headers, content=body),
                                     stream=True)
        captured = bytearray()

        async def relay():
            complete = False
            try:
                async for chunk in upstream.aiter_raw():
                    captured.extend(chunk)
                    yield chunk
                complete = True
            finally:
                await upstream.aclose()
                _settle(run_id, provider, rest, body, bytes(captured), upstream, started, complete)

        out_headers = {k: v for k, v in upstream.headers.items()
                       if k.lower() not in {"content-length", "transfer-encoding", "connection"}}
        return StreamingResponse(relay(), status_code=upstream.status_code, headers=out_headers)

    def _settle(run_id, provider, rest, request_body, response_body, upstream, started, complete) -> None:
        usage = usage_from_body(response_body)
        try:
            sent = json.loads(request_body) if request_body else {}
        except json.JSONDecodeError:
            sent = {}
        sent = sent if isinstance(sent, dict) else {}
        model = sent.get("model") or model_from(payloads(response_body))
        price = cost(usage, model, PRICES) if usage.found else None
        ledger.record(ledger.calls, {
            "ts": time.time(), "run": run_id, "provider": provider, "path": rest, "model": model,
            "status": upstream.status_code, "seconds": round(time.monotonic() - started, 3),
            "usage_found": usage.found, "input": usage.input, "cache_read": usage.cache_read,
            "cache_write": usage.cache_write, "output": usage.output,
            "cost_usd": round(price, 6) if price is not None else None,
            # A call can come back without usage when the client closes the stream early, or when a chat
            # completions stream does not ask for the final usage chunk.
            "complete": complete, "stream": bool(sent.get("stream")),
            "stream_usage": bool((sent.get("stream_options") or {}).get("include_usage"))})

    async def health(_: Request) -> Response:
        return JSONResponse({"spent_usd": round(ledger.spent, 4), "budget_usd": ledger.budget})

    return Starlette(routes=[Route("/health", health),
                             Route("/{run}/{provider}/{rest:path}", forward,
                                   methods=["GET", "POST", "PUT", "DELETE", "PATCH"])])


async def egress_proxy(ledger: Ledger, allow: set[str], host: str = "0.0.0.0", port: int = 3128) -> None:
    """HTTP CONNECT proxy that tunnels allowlisted hosts and records every attempt with its run id."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target = (lines[0].split(" ") + ["", ""])[:2]
        run_id = ""
        for line in lines[1:]:
            if line.lower().startswith("proxy-authorization: basic "):
                run_id = base64.b64decode(line.split(" ", 2)[2]).decode("utf-8", "replace").split(":")[0]
        target_host = target.split("//")[-1].split("/")[0].split(":")[0]
        allowed = method == "CONNECT" and target_host in allow
        ledger.record(ledger.egress, {"ts": time.time(), "run": run_id, "method": method, "target": target,
                                      "allowed": allowed})
        if not allowed:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        host_name, _, port_text = target.partition(":")
        try:
            up_reader, up_writer = await asyncio.open_connection(host_name, int(port_text or 443))
        except OSError:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                dst.close()

        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))

    server = await asyncio.start_server(handle, host, port)
    async with server:
        await server.serve_forever()


async def _main() -> None:
    ledger = Ledger(Path(os.environ.get("LEDGER_DIR", "/ledger")), float(os.environ.get("BUDGET_USD", "20")))
    keys = {name: os.environ.get(env, "") for name, (_, _, _, env) in UPSTREAMS.items()}
    allow = {h.strip() for h in os.environ.get("EGRESS_ALLOW", "").split(",") if h.strip()}
    config = uvicorn.Config(create_app(ledger, keys), host="0.0.0.0", port=8080, log_level="warning")
    await asyncio.gather(uvicorn.Server(config).serve(), egress_proxy(ledger, allow))


if __name__ == "__main__":
    asyncio.run(_main())
