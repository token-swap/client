from __future__ import annotations

import asyncio
import json
import os

import aiohttp
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static
from textual import work

from client.api import validate_key
from client.models import PROVIDERS, ExchangeConfig, PairingInfo


class ProviderScreen(Screen):
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
        self.dismiss((provider, model))


class ExchangeScreen(Screen):
    def __init__(self, provider: str, model: str) -> None:
        super().__init__()
        self.provider = provider
        self.model = model

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static(f"Offering: {self.provider}/{self.model}", classes="title")
            yield Static("Tokens to share")
            yield Input(placeholder="e.g. 1000", id="tokens-input", type="integer")
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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "want-provider-select" and event.value != Select.BLANK:
            provider = str(event.value)
            models = PROVIDERS.get(provider, [])
            model_select = self.query_one("#want-model-select", Select)
            model_select.set_options([(m, m) for m in models])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        tokens_str = self.query_one("#tokens-input", Input).value
        want_provider = self.query_one("#want-provider-select", Select).value
        want_model = self.query_one("#want-model-select", Select).value

        if not tokens_str or int(tokens_str) <= 0:
            self.notify("Enter a positive number of tokens", severity="error")
            return
        if want_provider == Select.BLANK or want_model == Select.BLANK:
            self.notify("Select wanted provider and model", severity="error")
            return

        self.dismiss((int(tokens_str), want_provider, want_model))


class KeyScreen(Screen):
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


class StatusScreen(Screen):
    BINDINGS = [("q", "app.quit", "Quit")]

    status_text: reactive[str] = reactive("Connecting...")
    tokens_served: reactive[int] = reactive(0)
    tokens_used: reactive[int] = reactive(0)
    tokens_serve_limit: reactive[int] = reactive(0)
    tokens_use_limit: reactive[int] = reactive(0)

    def __init__(self, config: ExchangeConfig) -> None:
        super().__init__()
        self.config = config
        self._pairing: PairingInfo | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static("TokenHub - Active", classes="title")
            yield Static(self.status_text, id="status", classes="status-text")
            yield DataTable(id="info-table")
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
            ]
        )
        self.connect_and_run()

    def _update_table(self) -> None:
        table = self.query_one("#info-table", DataTable)
        table.clear()
        table.add_rows(
            [
                ("Offering", f"{self.config.provider}/{self.config.model}"),
                ("Tokens offered", str(self.config.tokens_offered)),
                ("Wanting", f"{self.config.want_provider}/{self.config.want_model}"),
                (
                    "Served / Limit",
                    f"{self.tokens_served} / {self.tokens_serve_limit or '-'}",
                ),
                (
                    "Used / Limit",
                    f"{self.tokens_used} / {self.tokens_use_limit or '-'}",
                ),
                (
                    "Peer",
                    f"{self._pairing.peer_provider}/{self._pairing.peer_model}"
                    if self._pairing
                    else "-",
                ),
            ]
        )

    def watch_status_text(self) -> None:
        try:
            self.query_one("#status", Static).update(self.status_text)
        except Exception:
            pass

    def watch_tokens_served(self) -> None:
        self._update_table()

    def watch_tokens_used(self) -> None:
        self._update_table()

    async def on_proxy_tokens_used(self, count: int) -> None:
        self.tokens_served += count

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
            on_tokens_used=self.on_proxy_tokens_used,
        )

        try:
            self.status_text = "Starting proxy and ngrok tunnel..."
            tunnel_url = await proxy.start("127.0.0.1", self.config.proxy_port)
            self.config.proxy_url = tunnel_url

            self.status_text = "Connecting to server..."
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(server_url) as ws:
                    await ws.send_json(self.config.register_message())

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)

                            if data["type"] == "ack":
                                self.status_text = "Registered. Waiting for match..."

                            elif data["type"] == "paired":
                                self._pairing = PairingInfo.from_message(data)
                                self.tokens_serve_limit = self._pairing.tokens_to_serve
                                self.tokens_use_limit = self._pairing.tokens_granted

                                proxy._temp_key = self._pairing.temp_key
                                proxy._budget = self._pairing.tokens_to_serve

                                self.status_text = (
                                    f"[green]Paired! Proxy: {tunnel_url}[/]"
                                )
                                self._update_table()

                            elif data["type"] == "error":
                                self.status_text = f"[red]Error: {data['message']}[/]"

                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break

            self.status_text = "Disconnected"
        except Exception as e:
            self.status_text = f"[red]Connection failed: {e}[/]"
        finally:
            await proxy.stop()


class TokenHubApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "TokenHub"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._provider: str = ""
        self._model: str = ""

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

    def on_exchange_configured(self, result: tuple[int, str, str] | None) -> None:
        if result is None:
            return
        self._tokens, self._want_provider, self._want_model = result
        self.push_screen(KeyScreen(self._provider), callback=self.on_key_validated)

    def on_key_validated(self, api_key: str | None) -> None:
        if api_key is None:
            return
        config = ExchangeConfig(
            provider=self._provider,
            model=self._model,
            tokens_offered=self._tokens,
            want_provider=self._want_provider,
            want_model=self._want_model,
            api_key=api_key,
        )
        self.push_screen(StatusScreen(config))


def main():
    app = TokenHubApp()
    app.run()
