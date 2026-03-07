from __future__ import annotations
from dataclasses import dataclass


PROVIDERS = {
    "openai": [
        "gpt-5.2",
        "gpt-5.2-pro",
        "gpt-5.3-codex",
        "gpt-5-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "o3",
        "o4-mini",
    ],
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
    ],
    "gemini": [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ],
}

# Fallback model list for github-copilot when dynamic fetch fails
# or when selecting github-copilot as the "want" provider
COPILOT_MODELS_FALLBACK = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "o4-mini",
    "o3-mini",
    "claude-sonnet-4",
    "claude-3.5-sonnet",
    "gemini-2.0-flash-001",
]


@dataclass
class ExchangeConfig:
    provider: str
    model: str
    tokens_offered: int
    want_provider: str
    want_model: str
    api_key: str
    auth_method: str = "api_key"  # "api_key" or "copilot"
    github_token: str = ""  # GitHub OAuth token (for copilot token refresh)
    input_tokens_offered: int = 0
    output_tokens_offered: int = 0
    advanced: bool = False
    proxy_port: int = 9100
    proxy_url: str = ""

    def register_message(self) -> dict[str, str | int]:
        tokens_offered = self.tokens_offered
        if self.advanced:
            tokens_offered = self.input_tokens_offered + self.output_tokens_offered

        message = {
            "type": "register",
            "provider": self.provider,
            "model": self.model,
            "tokens_offered": tokens_offered,
            "want_provider": self.want_provider,
            "want_model": self.want_model,
            "proxy_url": self.proxy_url,
        }
        if self.advanced:
            message["input_tokens_offered"] = self.input_tokens_offered
            message["output_tokens_offered"] = self.output_tokens_offered
        return message


@dataclass
class PairingInfo:
    offer_id: str
    temp_key: str
    proxy_key: str
    peer_url: str
    peer_provider: str
    peer_model: str
    tokens_granted: int
    tokens_to_serve: int
    input_tokens_granted: int = 0
    output_tokens_granted: int = 0
    input_tokens_to_serve: int = 0
    output_tokens_to_serve: int = 0
    advanced: bool = False

    @classmethod
    def from_message(cls, msg: dict[str, object]) -> PairingInfo:
        def _to_int(value: object) -> int:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    return 0
            return 0

        input_tokens_granted = _to_int(msg.get("input_tokens_granted", 0))
        output_tokens_granted = _to_int(msg.get("output_tokens_granted", 0))
        input_tokens_to_serve = _to_int(msg.get("input_tokens_to_serve", 0))
        output_tokens_to_serve = _to_int(msg.get("output_tokens_to_serve", 0))
        advanced = (
            input_tokens_granted > 0
            or output_tokens_granted > 0
            or input_tokens_to_serve > 0
            or output_tokens_to_serve > 0
        )
        return cls(
            offer_id=str(msg["offer_id"]),
            temp_key=str(msg["temp_key"]),
            proxy_key=str(msg["proxy_key"]),
            peer_url=str(msg["peer_url"]),
            peer_provider=str(msg["peer_provider"]),
            peer_model=str(msg["peer_model"]),
            tokens_granted=_to_int(msg.get("tokens_granted", 0)),
            tokens_to_serve=_to_int(msg.get("tokens_to_serve", 0)),
            input_tokens_granted=input_tokens_granted,
            output_tokens_granted=output_tokens_granted,
            input_tokens_to_serve=input_tokens_to_serve,
            output_tokens_to_serve=output_tokens_to_serve,
            advanced=advanced,
        )
