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


@dataclass
class ExchangeConfig:
    provider: str
    model: str
    tokens_offered: int
    want_provider: str
    want_model: str
    api_key: str
    proxy_port: int = 9100
    proxy_url: str = ""

    def register_message(self) -> dict:
        return {
            "type": "register",
            "provider": self.provider,
            "model": self.model,
            "tokens_offered": self.tokens_offered,
            "want_provider": self.want_provider,
            "want_model": self.want_model,
            "proxy_url": self.proxy_url,
        }


@dataclass
class PairingInfo:
    offer_id: str
    temp_key: str
    peer_url: str
    peer_provider: str
    peer_model: str
    tokens_granted: int
    tokens_to_serve: int

    @classmethod
    def from_message(cls, msg: dict) -> PairingInfo:
        return cls(
            offer_id=msg["offer_id"],
            temp_key=msg["temp_key"],
            peer_url=msg["peer_url"],
            peer_provider=msg["peer_provider"],
            peer_model=msg["peer_model"],
            tokens_granted=msg["tokens_granted"],
            tokens_to_serve=msg["tokens_to_serve"],
        )
