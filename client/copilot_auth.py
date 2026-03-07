from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass

import httpx

GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

EDITOR_VERSION = "vscode/1.95.0"
EDITOR_PLUGIN_VERSION = "copilot/1.250.0"
USER_AGENT = "GithubCopilot/1.250.0"
COPILOT_SUPPORTED_MODELS_DOCS_URL = (
    "https://docs.github.com/en/copilot/reference/ai-models/supported-models"
)


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass
class CopilotToken:
    github_token: str
    copilot_token: str
    expires_at: float


async def request_device_code() -> DeviceCode:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GITHUB_DEVICE_CODE_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "scope": "read:user",
            },
            headers={
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return DeviceCode(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data["verification_uri"],
            expires_in=data["expires_in"],
            interval=data.get("interval", 5),
        )


async def poll_for_access_token(
    device_code: str,
    interval: int = 5,
    expires_in: int = 900,
) -> str:
    deadline = time.monotonic() + expires_in
    poll_interval = interval

    async with httpx.AsyncClient(timeout=10.0) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)

            resp = await client.post(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={
                    "Accept": "application/json",
                },
            )
            data = resp.json()

            if "access_token" in data and data["access_token"]:
                return data["access_token"]

            error = data.get("error", "")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                poll_interval += 5
                continue
            elif error == "expired_token":
                raise TimeoutError("Device code expired. Please try again.")
            elif error == "access_denied":
                raise PermissionError("Authorization denied by user.")
            elif error:
                raise RuntimeError(
                    f"OAuth error: {error} - {data.get('error_description', '')}"
                )

    raise TimeoutError("Device code expired before authorization completed.")


async def exchange_for_copilot_token(github_token: str) -> CopilotToken:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GITHUB_COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
            },
        )
        if resp.status_code == 401:
            raise PermissionError(
                "GitHub token invalid or expired. Please re-authenticate."
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Copilot token exchange failed (HTTP {resp.status_code}): {resp.text}"
            )

        data = resp.json()
        token = data.get("token")
        if not token:
            raise RuntimeError("Copilot token response missing 'token' field")

        expires_at = _parse_token_expiry(token)

        return CopilotToken(
            github_token=github_token,
            copilot_token=token,
            expires_at=expires_at,
        )


def _parse_token_expiry(token: str) -> float:
    match = re.search(r"exp=(\d+)", token)
    if match:
        return float(match.group(1))
    return time.time() + 1800


async def refresh_copilot_token(github_token: str) -> CopilotToken:
    return await exchange_for_copilot_token(github_token)


async def fetch_copilot_models(copilot_token: str) -> list[str]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.githubcopilot.com/models",
            headers={
                "Authorization": f"Bearer {copilot_token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
                "Copilot-Integration-Id": "vscode-chat",
                "Openai-Organization": "github-copilot",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        models: list[str] = []
        for model in data.get("data", []):
            capabilities = model.get("capabilities", {})
            if capabilities.get("type") != "chat":
                continue
            model_id = model.get("id")
            if model_id:
                models.append(model_id)
        return models


async def fetch_public_copilot_models() -> list[str]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            COPILOT_SUPPORTED_MODELS_DOCS_URL,
            headers={
                "Accept": "text/html",
                "User-Agent": USER_AGENT,
            },
        )
        resp.raise_for_status()

    page = resp.text
    start_marker = '<h2 id="supported-ai-models-in-copilot"'
    end_marker = '<h2 id="model-retirement-history"'
    start = page.find(start_marker)
    end = page.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return []

    section = page[start:end]
    names = re.findall(r'<th scope="row">([^<]+)</th>', section)

    models: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = html.unescape(name).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        models.append(normalized)

    return models
