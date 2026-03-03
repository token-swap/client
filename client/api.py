import httpx


PROVIDER_CONFIG = {
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
}


async def validate_key(provider: str, api_key: str) -> tuple[bool, str]:
    config = PROVIDER_CONFIG[provider]
    headers = {
        config["auth_header"]: config["auth_prefix"] + api_key,
        **config["extra_headers"],
    }

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
