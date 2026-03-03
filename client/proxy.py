from __future__ import annotations

import asyncio
import os

import httpx
from aiohttp import web
from pyngrok import ngrok

from client.api import PROVIDER_CONFIG


class ProxyServer:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        temp_key: str,
        token_budget: int,
        on_tokens_used,
    ) -> None:
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._temp_key = temp_key
        self._budget = token_budget
        self._used = 0
        self._on_tokens_used = on_tokens_used
        self._runner: web.AppRunner | None = None
        self._tunnel_url: str | None = None

    def _verify_auth(self, request: web.Request) -> bool:
        if self._provider == "openai":
            auth = request.headers.get("Authorization", "")
            return auth.removeprefix("Bearer ") == self._temp_key
        elif self._provider == "anthropic":
            return request.headers.get("x-api-key", "") == self._temp_key
        elif self._provider == "gemini":
            return request.headers.get("x-goog-api-key", "") == self._temp_key
        return False

    def _budget_exceeded(self) -> bool:
        return self._used >= self._budget

    async def _forward_and_track(
        self, request: web.Request, url: str, extra_headers: dict | None = None
    ) -> web.Response:
        if not self._verify_auth(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        if self._budget_exceeded():
            return web.json_response({"error": "Token budget exhausted"}, status=429)

        body = await request.read()
        config = PROVIDER_CONFIG[self._provider]
        headers = {
            "Content-Type": "application/json",
            config["auth_header"]: config["auth_prefix"] + self._api_key,
            **config["extra_headers"],
            **(extra_headers or {}),
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, content=body, headers=headers)

        resp_data = resp.json()
        tokens = self._extract_tokens(resp_data)
        if tokens > 0:
            self._used += tokens
            if self._on_tokens_used:
                await self._on_tokens_used(tokens)

        return web.Response(
            body=resp.content,
            status=resp.status_code,
            content_type="application/json",
        )

    def _extract_tokens(self, data: dict) -> int:
        try:
            if self._provider == "openai":
                usage = data.get("usage", {})
                return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            elif self._provider == "anthropic":
                usage = data.get("usage", {})
                return usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            elif self._provider == "gemini":
                usage = data.get("usage_metadata", {})
                return usage.get("prompt_token_count", 0) + usage.get(
                    "candidates_token_count", 0
                )
        except (AttributeError, TypeError):
            pass
        return 0

    async def _handle_openai(self, request: web.Request) -> web.Response:
        url = f"{PROVIDER_CONFIG['openai']['base_url']}/v1/chat/completions"
        return await self._forward_and_track(request, url)

    async def _handle_anthropic(self, request: web.Request) -> web.Response:
        url = f"{PROVIDER_CONFIG['anthropic']['base_url']}/v1/messages"
        return await self._forward_and_track(request, url)

    async def _handle_gemini(self, request: web.Request) -> web.Response:
        model = request.match_info.get("model", self._model)
        url = (
            f"{PROVIDER_CONFIG['gemini']['base_url']}"
            f"/v1beta/models/{model}:generateContent"
        )
        return await self._forward_and_track(request, url)

    def _create_app(self) -> web.Application:
        app = web.Application()
        if self._provider == "openai":
            app.router.add_post("/v1/chat/completions", self._handle_openai)
        elif self._provider == "anthropic":
            app.router.add_post("/v1/messages", self._handle_anthropic)
        elif self._provider == "gemini":
            app.router.add_post(
                "/v1beta/models/{model}:generateContent", self._handle_gemini
            )
        return app

    async def start(self, host: str = "127.0.0.1", port: int = 9100) -> str:
        self._runner = web.AppRunner(self._create_app())
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()

        self._tunnel_url = await asyncio.to_thread(self._create_tunnel, port)
        return self._tunnel_url

    @staticmethod
    def _create_tunnel(port: int) -> str:
        auth_token = os.environ.get("NGROK_AUTHTOKEN", "")
        if auth_token:
            ngrok.set_auth_token(auth_token)
        tunnel = ngrok.connect(str(port), "http")
        if tunnel.public_url is None:
            raise RuntimeError("ngrok tunnel did not return a public URL")
        return tunnel.public_url

    async def stop(self) -> None:
        if self._tunnel_url:
            await asyncio.to_thread(self._disconnect_tunnel, self._tunnel_url)
            self._tunnel_url = None
        if self._runner:
            await self._runner.cleanup()

    @staticmethod
    def _disconnect_tunnel(url: str) -> None:
        from pyngrok import ngrok

        try:
            ngrok.disconnect(url)
        except Exception:
            pass
