from typing import TypedDict

import httpx


class _ProviderCfg(TypedDict):
    base_url: str
    auth_header: str
    auth_prefix: str
    extra_headers: dict[str, str]


PROVIDER_CONFIG: dict[str, _ProviderCfg] = {
    "openai": {
        "base_url": "https://api.openai.com",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "extra_headers": {"anthropic-version": "2023-06-01"},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "auth_header": "x-goog-api-key",
        "auth_prefix": "",
        "extra_headers": {},
    },
    "github-copilot": {
        "base_url": "https://api.githubcopilot.com",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {
            "Editor-Version": "vscode/1.95.0",
            "Editor-Plugin-Version": "copilot/1.250.0",
            "User-Agent": "GithubCopilot/1.250.0",
            "Copilot-Integration-Id": "vscode-chat",
            "Openai-Organization": "github-copilot",
        },
    },
}


def _build_auth_headers(provider: str, api_key: str) -> dict[str, str]:
    config = PROVIDER_CONFIG[provider]
    auth_header: str = config["auth_header"]
    auth_prefix: str = config["auth_prefix"]
    extra_headers: dict[str, str] = config["extra_headers"]
    return {
        auth_header: auth_prefix + api_key,
        **extra_headers,
    }


async def validate_key(provider: str, api_key: str) -> tuple[bool, str]:
    config = PROVIDER_CONFIG[provider]
    headers = _build_auth_headers(provider, api_key)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if provider == "anthropic":
                resp = await client.post(
                    f"{config['base_url']}/v1/messages",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 1,
                        "messages": [],
                    },
                )
                if resp.status_code == 401:
                    return False, "Invalid API key"
                return True, "OK"
            elif provider == "gemini":
                resp = await client.get(
                    f"{config['base_url']}/v1beta/models",
                    headers=headers,
                )
            elif provider == "github-copilot":
                resp = await client.get(
                    f"{config['base_url']}/models",
                    headers=headers,
                )
            else:
                resp = await client.get(
                    f"{config['base_url']}/v1/models",
                    headers=headers,
                )

            if resp.status_code == 200:
                return True, "OK"
            return False, f"Validation failed (HTTP {resp.status_code})"
        except httpx.RequestError as e:
            return False, f"Network error: {e}"


async def fetch_provider_models(provider: str, api_key: str) -> tuple[list[str], str]:
    if provider not in {"openai", "anthropic", "gemini"}:
        return [], "Live model fetch is only available for API key providers"

    config = PROVIDER_CONFIG[provider]
    headers = _build_auth_headers(provider, api_key)

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if provider == "anthropic":
                resp = await client.get(
                    f"{config['base_url']}/v1/models",
                    headers=headers,
                )
            elif provider == "gemini":
                resp = await client.get(
                    f"{config['base_url']}/v1beta/models",
                    headers=headers,
                )
            else:
                resp = await client.get(
                    f"{config['base_url']}/v1/models",
                    headers=headers,
                )
        except httpx.RequestError as e:
            return [], f"Network error: {e}"

    if resp.status_code in {401, 403}:
        return [], "API key rejected"
    if resp.status_code != 200:
        return [], f"Model fetch failed (HTTP {resp.status_code})"

    try:
        payload = resp.json()
    except ValueError:
        return [], "Model fetch failed (invalid JSON response)"

    models: list[str] = []
    seen: set[str] = set()

    for item in payload.get("data", []):
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id and model_id not in seen:
            seen.add(model_id)
            models.append(model_id)

    if provider == "gemini":
        models = []
        seen = set()
        for item in payload.get("models", []):
            name = item.get("name")
            methods = item.get("supportedGenerationMethods", [])
            if not isinstance(name, str) or not name:
                continue
            if "generateContent" not in methods:
                continue
            normalized = name[7:] if name.startswith("models/") else name
            if normalized and normalized not in seen:
                seen.add(normalized)
                models.append(normalized)

    if not models:
        return [], "No models returned by provider"

    return models, "OK"
