from __future__ import annotations

import asyncio
import json
import os

import aiohttp
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Select,
    Static,
    Switch,
    TextArea,
)
from textual import work

from client.api import validate_key
from client.models import PROVIDERS, ExchangeConfig, PairingInfo


class ProviderScreen(Screen[tuple[str, str]]):
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static("TokenHub", classes="title")
            yield Static("Select Provider")
            yield Select(
                [(p.capitalize(), p) for p in PROVIDERS],
                prompt="Choose provider",
                id="provider-select",
            )
            yield Static("Select Model")
            yield Select([], prompt="Choose model", id="model-select")
            yield Button("Next", id="next-btn", variant="primary")
        yield Footer()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider-select" and event.value != Select.BLANK:
            provider = str(event.value)
            models = PROVIDERS.get(provider, [])
            model_select = self.query_one("#model-select", Select)
            model_select.set_options([(m, m) for m in models])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        provider = self.query_one("#provider-select", Select).value
        model = self.query_one("#model-select", Select).value
        if provider == Select.BLANK or model == Select.BLANK:
            self.notify("Select both provider and model", severity="error")
            return
        self.dismiss((str(provider), str(model)))


class ExchangeScreen(Screen[tuple[int, str, str, bool, int, int]]):
    def __init__(self, provider: str, model: str) -> None:
        super().__init__()
        self.provider = provider
        self.model = model

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static(f"Offering: {self.provider}/{self.model}", classes="title")
            yield Static("Tokens to share", id="tokens-label")
            yield Input(placeholder="e.g. 1000", id="tokens-input", type="integer")
            with Horizontal(id="advanced-toggle-row"):
                yield Static("Advanced", id="advanced-label")
                yield Switch(id="advanced-switch")
            yield Static("Input tokens to share", id="input-tokens-label")
            yield Input(
                placeholder="e.g. 700",
                id="input-tokens-input",
                type="integer",
            )
            yield Static("Output tokens to share", id="output-tokens-label")
            yield Input(
                placeholder="e.g. 300",
                id="output-tokens-input",
                type="integer",
            )
            yield Static("Want provider")
            other_providers = [p for p in PROVIDERS if p != self.provider]
            yield Select(
                [(p.capitalize(), p) for p in other_providers],
                prompt="Choose provider",
                id="want-provider-select",
            )
            yield Static("Want model")
            yield Select([], prompt="Choose model", id="want-model-select")
            yield Button("Next", id="next-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._set_advanced_mode(False)

    def _set_advanced_mode(self, advanced: bool) -> None:
        self.query_one("#tokens-label", Static).display = not advanced
        self.query_one("#tokens-input", Input).display = not advanced
        self.query_one("#input-tokens-label", Static).display = advanced
        self.query_one("#input-tokens-input", Input).display = advanced
        self.query_one("#output-tokens-label", Static).display = advanced
        self.query_one("#output-tokens-input", Input).display = advanced

    @staticmethod
    def _parse_positive_int(value: str) -> int | None:
        try:
            parsed = int(value)
        except ValueError:
            return None
        if parsed <= 0:
            return None
        return parsed

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "want-provider-select" and event.value != Select.BLANK:
            provider = str(event.value)
            models = PROVIDERS.get(provider, [])
            model_select = self.query_one("#want-model-select", Select)
            model_select.set_options([(m, m) for m in models])

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "advanced-switch":
            self._set_advanced_mode(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        tokens_str = self.query_one("#tokens-input", Input).value
        input_tokens_str = self.query_one("#input-tokens-input", Input).value
        output_tokens_str = self.query_one("#output-tokens-input", Input).value
        advanced = self.query_one("#advanced-switch", Switch).value
        want_provider = self.query_one("#want-provider-select", Select).value
        want_model = self.query_one("#want-model-select", Select).value

        if want_provider == Select.BLANK or want_model == Select.BLANK:
            self.notify("Select wanted provider and model", severity="error")
            return
        want_provider_str = str(want_provider)
        want_model_str = str(want_model)

        if advanced:
            input_tokens = self._parse_positive_int(input_tokens_str)
            output_tokens = self._parse_positive_int(output_tokens_str)
            if input_tokens is None or output_tokens is None:
                self.notify(
                    "Enter positive input and output token amounts",
                    severity="error",
                )
                return
            self.dismiss(
                (
                    0,
                    want_provider_str,
                    want_model_str,
                    True,
                    input_tokens,
                    output_tokens,
                )
            )
            return

        tokens = self._parse_positive_int(tokens_str)
        if tokens is None:
            self.notify("Enter a positive number of tokens", severity="error")
            return

        self.dismiss((tokens, want_provider_str, want_model_str, False, 0, 0))


class KeyScreen(Screen[str]):
    def __init__(self, provider: str) -> None:
        super().__init__()
        self.provider = provider

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static(f"Enter {self.provider.capitalize()} API Key", classes="title")
            yield Input(placeholder="API key", password=True, id="key-input")
            yield Button("Validate & Connect", id="validate-btn", variant="primary")
            yield Static("", id="key-status", classes="status-text")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        key = self.query_one("#key-input", Input).value
        if not key.strip():
            self.notify("Enter an API key", severity="error")
            return
        self.query_one("#key-status", Static).update("Validating...")
        self.query_one("#validate-btn", Button).disabled = True
        self.do_validate(key.strip())

    @work(exclusive=True)
    async def do_validate(self, key: str) -> None:
        valid, message = await validate_key(self.provider, key)
        status = self.query_one("#key-status", Static)
        btn = self.query_one("#validate-btn", Button)
        if valid:
            status.update("[green]Key valid![/]")
            await asyncio.sleep(0.5)
            self.dismiss(key)
        else:
            status.update(f"[red]{message}[/]")
            btn.disabled = False


def _make_snippet(provider: str, model: str, peer_url: str, temp_key: str) -> str:
    if provider == "openai":
        return f'''\
import requests

resp = requests.post(
    "{peer_url}/v1/chat/completions",
    headers={{"Authorization": "Bearer {temp_key}"}},
    json={{
        "model": "{model}",
        "messages": [{{"role": "user", "content": "What is the capital of France?"}}],
    }},
)
print(resp.json()["choices"][0]["message"]["content"])
'''
    elif provider == "anthropic":
        return f'''\
import requests

resp = requests.post(
    "{peer_url}/v1/messages",
    headers={{"x-api-key": "{temp_key}", "content-type": "application/json"}},
    json={{
        "model": "{model}",
        "max_tokens": 256,
        "messages": [{{"role": "user", "content": "What is the capital of France?"}}],
    }},
)
print(resp.json()["content"][0]["text"])
'''
    elif provider == "gemini":
        return f'''\
import requests

resp = requests.post(
    "{peer_url}/v1beta/models/{model}:generateContent",
    headers={{"x-goog-api-key": "{temp_key}"}},
    json={{
        "contents": [{{"parts": [{{"text": "What is the capital of France?"}}]}}],
    }},
)
print(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
'''
    return "# Unknown provider"


class StatusScreen(Screen[None]):
    BINDINGS = [("q", "app.quit", "Quit")]

    status_text: reactive[str] = reactive("Connecting...")
    tokens_served: reactive[int] = reactive(0)
    tokens_used: reactive[int] = reactive(0)
    input_tokens_served: reactive[int] = reactive(0)
    output_tokens_served: reactive[int] = reactive(0)
    input_tokens_used: reactive[int] = reactive(0)
    output_tokens_used: reactive[int] = reactive(0)
    tokens_serve_limit: reactive[int] = reactive(0)
    tokens_use_limit: reactive[int] = reactive(0)

    def __init__(self, config: ExchangeConfig) -> None:
        super().__init__()
        self.config = config
        self._pairing: PairingInfo | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="status-layout"):
            with Vertical(id="left-pane"):
                yield Static("TokenHub - Active", classes="title")
                yield Static(self.status_text, id="status", classes="status-text")
                yield DataTable(id="info-table")
                with Horizontal(id="copy-buttons"):
                    yield Button("Copy Peer URL", id="copy-url-btn", variant="primary")
                    yield Button("Copy Temp Key", id="copy-key-btn", variant="primary")
            with Vertical(id="right-pane"):
                yield Static("Quick Start", classes="title")
                yield TextArea(
                    "# Waiting for pairing...",
                    language="python",
                    theme="monokai",
                    read_only=True,
                    show_line_numbers=False,
                    id="code-snippet",
                )
                yield Button("Copy Code", id="copy-code-btn", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#info-table", DataTable)
        table.add_columns("Metric", "Value")
        table.add_rows(
            [
                ("Offering", f"{self.config.provider}/{self.config.model}"),
                ("Tokens offered", str(self.config.tokens_offered)),
                ("Wanting", f"{self.config.want_provider}/{self.config.want_model}"),
                ("Served / Limit", "0 / -"),
                ("Used / Limit", "0 / -"),
                ("Peer", "-"),
                ("Peer URL", "-"),
                ("Temp Key", "-"),
            ]
        )
        self.query_one("#copy-buttons", Horizontal).display = False
        self.query_one("#right-pane", Vertical).display = False
        self.connect_and_run()

    def _update_table(self) -> None:
        table = self.query_one("#info-table", DataTable)
        table.clear()
        peer_url = self._pairing.peer_url if self._pairing else "-"
        temp_key = self._pairing.temp_key if self._pairing else "-"
        rows: list[tuple[str, str]] = [
            ("Offering", f"{self.config.provider}/{self.config.model}"),
            ("Tokens offered", str(self.config.tokens_offered)),
            ("Wanting", f"{self.config.want_provider}/{self.config.want_model}"),
        ]
        if self._pairing and self._pairing.advanced:
            rows.extend(
                [
                    (
                        "Input Served / Limit",
                        f"{self.input_tokens_served} / {self._pairing.input_tokens_to_serve or '-'}",
                    ),
                    (
                        "Output Served / Limit",
                        f"{self.output_tokens_served} / {self._pairing.output_tokens_to_serve or '-'}",
                    ),
                    (
                        "Input Used / Limit",
                        f"{self.input_tokens_used} / {self._pairing.input_tokens_granted or '-'}",
                    ),
                    (
                        "Output Used / Limit",
                        f"{self.output_tokens_used} / {self._pairing.output_tokens_granted or '-'}",
                    ),
                ]
            )
        else:
            rows.extend(
                [
                    (
                        "Served / Limit",
                        f"{self.tokens_served} / {self.tokens_serve_limit or '-'}",
                    ),
                    (
                        "Used / Limit",
                        f"{self.tokens_used} / {self.tokens_use_limit or '-'}",
                    ),
                ]
            )
        rows.extend(
            [
                (
                    "Peer",
                    f"{self._pairing.peer_provider}/{self._pairing.peer_model}"
                    if self._pairing
                    else "-",
                ),
                ("Peer URL", peer_url),
                ("Temp Key", temp_key),
            ]
        )
        table.add_rows(rows)
        if self._pairing:
            self.query_one("#copy-buttons", Horizontal).display = True
            self.query_one("#right-pane", Vertical).display = True
            snippet = _make_snippet(
                self._pairing.peer_provider,
                self._pairing.peer_model,
                self._pairing.peer_url,
                self._pairing.temp_key,
            )
            code_area = self.query_one("#code-snippet", TextArea)
            code_area.load_text(snippet)

    def watch_status_text(self) -> None:
        try:
            self.query_one("#status", Static).update(self.status_text)
        except Exception:
            pass

    def watch_tokens_served(self) -> None:
        self._update_table()

    def watch_tokens_used(self) -> None:
        self._update_table()

    def watch_input_tokens_served(self) -> None:
        self._update_table()

    def watch_output_tokens_served(self) -> None:
        self._update_table()

    def watch_input_tokens_used(self) -> None:
        self._update_table()

    def watch_output_tokens_used(self) -> None:
        self._update_table()

    async def on_proxy_tokens_served(self, input_count: int, output_count: int) -> None:
        self.tokens_served += input_count + output_count
        self.input_tokens_served += input_count
        self.output_tokens_served += output_count
        if self._pairing and self._ws:
            try:
                await self._ws.send_json(
                    {
                        "type": "usage_report",
                        "offer_id": self._pairing.offer_id,
                        "tokens": input_count + output_count,
                        "input_tokens": input_count,
                        "output_tokens": output_count,
                    }
                )
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self._pairing:
            return
        if event.button.id == "copy-url-btn":
            self.app.copy_to_clipboard(self._pairing.peer_url)
            self.notify("Peer URL copied!")
        elif event.button.id == "copy-key-btn":
            self.app.copy_to_clipboard(self._pairing.temp_key)
            self.notify("Temp key copied!")
        elif event.button.id == "copy-code-btn":
            snippet = _make_snippet(
                self._pairing.peer_provider,
                self._pairing.peer_model,
                self._pairing.peer_url,
                self._pairing.temp_key,
            )
            self.app.copy_to_clipboard(snippet)
            self.notify("Code copied!")

    @work(exclusive=True)
    async def connect_and_run(self) -> None:
        from client.proxy import ProxyServer

        server_url = os.environ.get("TOKENHUB_SERVER", "ws://localhost:8080") + "/ws"

        proxy = ProxyServer(
            provider=self.config.provider,
            model=self.config.model,
            api_key=self.config.api_key,
            temp_key="",
            token_budget=0,
            input_budget=0,
            output_budget=0,
            on_tokens_served=self.on_proxy_tokens_served,
        )

        try:
            self.status_text = "Starting proxy and ngrok tunnel..."
            tunnel_url = await proxy.start("127.0.0.1", self.config.proxy_port)
            self.config.proxy_url = tunnel_url

            self.status_text = "Connecting to server..."
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(server_url) as ws:
                    self._ws = ws
                    await ws.send_json(self.config.register_message())

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)

                            if data["type"] == "ack":
                                self.status_text = "Registered. Waiting for match..."

                            elif data["type"] == "paired":
                                self._pairing = PairingInfo.from_message(data)
                                self.tokens_serve_limit = (
                                    self._pairing.tokens_to_serve
                                    or (
                                        self._pairing.input_tokens_to_serve
                                        + self._pairing.output_tokens_to_serve
                                    )
                                )
                                self.tokens_use_limit = (
                                    self._pairing.tokens_granted
                                    or (
                                        self._pairing.input_tokens_granted
                                        + self._pairing.output_tokens_granted
                                    )
                                )

                                proxy._temp_key = self._pairing.proxy_key
                                proxy._total_budget = self.tokens_serve_limit
                                proxy._input_budget = (
                                    self._pairing.input_tokens_to_serve
                                )
                                proxy._output_budget = (
                                    self._pairing.output_tokens_to_serve
                                )
                                proxy._advanced = self._pairing.advanced

                                self.status_text = (
                                    f"[green]Paired! Proxy: {tunnel_url}[/]"
                                )
                                self._update_table()

                            elif data["type"] == "error":
                                self.status_text = f"[red]Error: {data['message']}[/]"

                            elif data["type"] == "usage_update":
                                input_tokens = data.get("input_tokens", 0)
                                output_tokens = data.get("output_tokens", 0)
                                tokens = data.get(
                                    "tokens", input_tokens + output_tokens
                                )
                                self.tokens_used += tokens
                                self.input_tokens_used += input_tokens
                                self.output_tokens_used += output_tokens

                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break

            self.status_text = "Disconnected"
            self._ws = None
        except Exception as e:
            self.status_text = f"[red]Connection failed: {e}[/]"
        finally:
            await proxy.stop()


class TokenHubApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "TokenHub"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._provider: str = ""
        self._model: str = ""
        self._tokens: int = 0
        self._want_provider: str = ""
        self._want_model: str = ""
        self._advanced: bool = False
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def on_mount(self) -> None:
        self.push_screen(ProviderScreen(), callback=self.on_provider_selected)

    def on_provider_selected(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        self._provider, self._model = result
        self.push_screen(
            ExchangeScreen(self._provider, self._model),
            callback=self.on_exchange_configured,
        )

    def on_exchange_configured(
        self, result: tuple[int, str, str, bool, int, int] | None
    ) -> None:
        if result is None:
            return
        (
            self._tokens,
            self._want_provider,
            self._want_model,
            self._advanced,
            self._input_tokens,
            self._output_tokens,
        ) = result
        self.push_screen(KeyScreen(self._provider), callback=self.on_key_validated)

    def on_key_validated(self, api_key: str | None) -> None:
        if api_key is None:
            return
        config = ExchangeConfig(
            provider=self._provider,
            model=self._model,
            tokens_offered=(
                self._input_tokens + self._output_tokens
                if self._advanced
                else self._tokens
            ),
            want_provider=self._want_provider,
            want_model=self._want_model,
            api_key=api_key,
            input_tokens_offered=self._input_tokens if self._advanced else 0,
            output_tokens_offered=self._output_tokens if self._advanced else 0,
            advanced=self._advanced,
        )
        self.push_screen(StatusScreen(config))


def main():
    app = TokenHubApp()
    app.run()
