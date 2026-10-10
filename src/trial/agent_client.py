"""ACP client side of a run: answers the agent's permission requests by policy and records what it does.

The client advertises no file system or terminal capability, so each harness uses its own built-in tools
inside the sandbox. What the client controls is the approval step: harnesses that ask before a tool call get
an answer from `decide()`, and every request and answer is written to the transcript. Claude Code and Grok Build
ask before edits and commands; dsh in workspace-write mode runs its tools inside /work without asking, so for
dsh the containment comes from the sandbox and the network alone.
"""
from __future__ import annotations

import json
import posixpath
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acp import RequestPermissionResponse
from acp.schema import AllowedOutcome, DeniedOutcome, PermissionOption, ToolCallUpdate

WORKSPACE = "/work"
WRITE_KINDS = {"edit", "delete", "move"}


def decide(tool_call: ToolCallUpdate) -> tuple[bool, str]:
    """Allow tool calls that stay inside the sandbox workspace; refuse network fetches and writes elsewhere."""
    if tool_call.kind == "fetch":
        return False, "network fetch is not allowed in the sandbox"
    if tool_call.kind in WRITE_KINDS:
        for loc in tool_call.locations or []:
            path = posixpath.normpath(loc.path.replace("\\", "/"))
            if path != WORKSPACE and not path.startswith(WORKSPACE + "/"):
                return False, f"write outside {WORKSPACE}: {path}"
    return True, "inside the workspace"


def pick(options: list[PermissionOption], allow: bool) -> str | None:
    wanted = ("allow_once", "allow_always") if allow else ("reject_once", "reject_always")
    for kind in wanted:
        for option in options:
            if option.kind == kind:
                return option.option_id
    return None


@dataclass
class TrialClient:
    transcript: Path
    tool_calls: set[str] = field(default_factory=set)
    permission_requests: int = 0
    denied: list[str] = field(default_factory=list)
    message_chars: int = 0

    def _log(self, event: str, payload: Any) -> None:
        data = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
        with self.transcript.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), "event": event, "data": data}, ensure_ascii=False) + "\n")

    async def request_permission(self, options: list[PermissionOption], session_id: str,
                                 tool_call: ToolCallUpdate, **kwargs: Any) -> RequestPermissionResponse:
        self.permission_requests += 1
        allow, reason = decide(tool_call)
        option_id = pick(options, allow)
        if not allow:
            self.denied.append(reason)
        self._log("permission", {"tool_call": tool_call.model_dump(mode="json", exclude_none=True),
                                 "allow": allow, "reason": reason, "option": option_id})
        if option_id is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id=option_id))

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        kind = getattr(update, "session_update", None)
        if kind == "tool_call":
            self.tool_calls.add(update.tool_call_id)
        elif kind == "agent_message_chunk" and getattr(update.content, "text", None):
            self.message_chars += len(update.content.text)
        self._log("update", update)

    # The client does not offer file system, terminal or elicitation support; agents use their own tools.
    async def write_text_file(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def read_text_file(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def create_terminal(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def terminal_output(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def release_terminal(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def wait_for_terminal_exit(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def kill_terminal(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    async def ext_method(self, method: str, params: dict) -> dict:
        self._log("ext_method", {"method": method})
        return {}

    async def ext_notification(self, method: str, params: dict) -> None:
        self._log("ext_notification", {"method": method})

    def on_connect(self, conn: Any) -> None:
        pass
