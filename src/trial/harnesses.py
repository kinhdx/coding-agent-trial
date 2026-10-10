"""How each harness is started inside its sandbox image and pointed at the gateway.

Every harness gets a placeholder key and a base URL of the form http://gateway:8080/<run_id>/<provider>,
so the real key never enters the sandbox and every model call is attributed to its run. Versions are pinned
in sandbox/Dockerfile.<name>.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PLACEHOLDER_KEY = "sk-sandbox-placeholder"
GATEWAY = "http://gateway:8080"


@dataclass(frozen=True)
class Harness:
    name: str
    image: str
    model: str
    command: tuple[str, ...]
    provider: str  # gateway route
    env: dict[str, str] = field(default_factory=dict)
    auth_method: str | None = None  # ACP authenticate method, when the agent requires one

    def environment(self, run_id: str) -> dict[str, str]:
        base = f"{GATEWAY}/{run_id}/{self.provider}"
        return {k: v.format(base=base, key=PLACEHOLDER_KEY, model=self.model) for k, v in self.env.items()}


HARNESSES = {
    "claude-code": Harness(
        name="claude-code",
        image="trial-claude-code",
        model="claude-sonnet-5-5",
        command=("claude-agent-acp",),
        provider="anthropic",
        env={"ANTHROPIC_BASE_URL": "{base}", "ANTHROPIC_API_KEY": "{key}", "ANTHROPIC_MODEL": "{model}",
             "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-5-5",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"},
    ),
    "grok-build": Harness(
        name="grok-build",
        image="trial-grok-build",
        model="grok-build-0.1",
        command=("grok", "agent", "--model", "grok-build-0.1", "stdio"),
        provider="xai",
        env={"XAI_API_KEY": "{key}", "GROK_XAI_API_BASE_URL": "{base}/v1", "GROK_MODELS_BASE_URL": "{base}/v1"},
        auth_method="xai.api_key",
    ),
    "dsh": Harness(
        name="dsh",
        image="trial-dsh",
        model="deepseek-v4-pro",
        command=("dsh", "--profile", "acp", "--patch", "/etc/dsh/model.yml"),
        provider="deepseek",
        env={"DEEPSEEK_API_KEY": "{key}", "DEEPSEEK_BASE_URL": "{base}",
             "DSH_PERMISSION_MODE": "workspace-write", "DSH_TELEMETRY_MODE": "DISABLED"},
    ),
}
