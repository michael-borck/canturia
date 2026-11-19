"""Canturía CLI: `canturia "lyrics"`, `canturia describe "a topic"`,
`canturia serve`, and `canturia health`."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from typer.core import TyperGroup

from canturia import __version__
from canturia.config import (
    ConfigurationError,
    load_config,
    resolve_serve_settings,
    resolve_settings,
    save_example_config,
)
from canturia.core import (
    DURATION_MAX,
    DURATION_MIN,
    compare_lyrics,
    generate,
    health,
    lyricist_choices,
    save_song,
)
from canturia.core import lyrics as lyrics_only
from canturia.lyricists import LyricistError
from canturia.providers import AceStepError, OllamaError

console = Console()
err_console = Console(stderr=True, style="bold red")


class DefaultCommandGroup(TyperGroup):
    """Route bare invocations to `generate` so `canturia "lyrics"` works."""

    default_command = "generate"
    _root_tokens = {"-h", "--help", "-V", "--version"}

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and args[0] not in self._root_tokens:
            args = [self.default_command, *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=DefaultCommandGroup,
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"canturia {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """Canturía — words into a song, rendered by your own ACE-Step server."""
    del version


def _read_lyrics(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source).expanduser()
    if not path.exists():
        raise ValueError(f"Lyrics file not found: {source}")
    return path.read_text(encoding="utf-8")


def _apply_overrides(
    cfg: dict[str, Any],
    *,
    base_url: str | None,
    api_key: str | None,
    username: str | None,
    password: str | None,
    timeout: float | None,
) -> None:
    if base_url:
        cfg["base_url"] = base_url
    if api_key:
        cfg["api_key"] = api_key
    if username:
        cfg["username"] = username
    if password:
        cfg["password"] = password
    if timeout is not None:
        cfg["timeout"] = timeout


def _connection_options(
    *,
    base_url: str | None,
    api_key: str | None,
    username: str | None,
    password: str | None,
    config: str | None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Load config and apply the connection flags shared by commands."""
    cfg = load_config(config)
    _apply_overrides(
        cfg,
        base_url=base_url,
        api_key=api_key,
        username=username,
        password=password,
        timeout=timeout,
    )
    return cfg


def _run_generate(
    mode: str,
    text: str,
    *,
    genre: str | None,
    style: str | None,
    duration: float | None,
    out: str | None,
    config: str | None,
    base_url: str | None,
    api_key: str | None,
    username: str | None,
    password: str | None,
    timeout: float | None,
    lyricist: str | None = None,
) -> None:
    cfg = _connection_options(
        base_url=base_url,
        api_key=api_key,
        username=username,
        password=password,
        config=config,
        timeout=timeout,
    )
    settings = resolve_settings(cfg)

    with console.status("Submitting to ACE-Step…", spinner="dots") as status:
        generation = generate(
            mode,
            text,
            settings,
            genre=genre,
            style=style,
            duration=duration,
            lyricist=lyricist,
            on_progress=lambda message: status.update(f"Generating… {message}"),
        )

    for song in generation.songs:
        path, sidecar = save_song(generation, song, out)
        console.print(f"Saved: [bold green]{path}[/bold green]")
        console.print(f"  metadata: [dim]{sidecar}[/dim]")


def generate_cmd(
    text: str | None = typer.Argument(
        None,
        help="Lyrics to sing. Use [Verse]/[Chorus] tags for structure.",
        show_default=False,
    ),
    lyrics_file: str | None = typer.Option(
        None,
        "--lyrics-file",
        "-f",
        help="Read lyrics from a file ('-' for stdin).",
        show_default=False,
    ),
    genre: str | None = typer.Option(
        None,
        "--genre",
        "-g",
        help="Genre key (folk, pop, rock, indie, lofi, hiphop, …) or free text.",
        show_default=False,
    ),
    style: str | None = typer.Option(
        None,
        "--style",
        "-s",
        help="Extra style details, e.g. 'warm female vocals, fingerpicked guitar'.",
        show_default=False,
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        "-t",
        min=DURATION_MIN,
        max=DURATION_MAX,
        help=f"Length in seconds ({int(DURATION_MIN)}–{int(DURATION_MAX)}).",
        show_default=False,
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Output file (default: derived from the genre and words).",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Overall generation timeout in seconds.",
        show_default=False,
    ),
    init_config: bool = typer.Option(
        False, "--init-config", help="Write an example ./canturia.yaml and exit."
    ),
) -> None:
    """Turn lyrics into a song (the default command).

    Configure once in ~/.canturia.yaml (server URL and optional auth), then:

        canturia "[Verse]\\nMorning light...\\n[Chorus]\\nGrow a little every day" -g folk

    For a topic, use `canturia describe "a song about growing up by the sea"`.
    """
    try:
        if init_config:
            path = save_example_config()
            console.print(f"Wrote example config: [bold]{path}[/bold]")
            raise typer.Exit()

        if lyrics_file and text:
            err_console.print("Give lyrics or --lyrics-file, not both.")
            raise typer.Exit(code=2)
        source = _read_lyrics(lyrics_file) if lyrics_file else (text or "")
        if not source.strip():
            err_console.print(
                'Give me lyrics, e.g.: canturia "[Verse]\\nA line..." -g folk'
            )
            raise typer.Exit(code=2)

        _run_generate(
            "lyrics",
            source,
            genre=genre,
            style=style,
            duration=duration,
            out=out,
            config=config,
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            timeout=timeout,
        )
    except (ConfigurationError, AceStepError, OllamaError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


# Register the command under the name `generate` while keeping the function
# name usable in tests.
app.command(name="generate")(generate_cmd)


@app.command()
def describe(
    topic: str = typer.Argument(
        ...,
        help="A topic, theme, or sentence; ACE-Step writes the lyrics.",
    ),
    genre: str | None = typer.Option(
        None,
        "--genre",
        "-g",
        help="Genre key (folk, pop, rock, indie, lofi, hiphop, …) or free text.",
        show_default=False,
    ),
    style: str | None = typer.Option(
        None,
        "--style",
        "-s",
        help="Extra style details, e.g. 'warm female vocals, fingerpicked guitar'.",
        show_default=False,
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        "-t",
        min=DURATION_MIN,
        max=DURATION_MAX,
        help=f"Length in seconds ({int(DURATION_MIN)}–{int(DURATION_MAX)}).",
        show_default=False,
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Output file (default: derived from the genre and topic).",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Overall generation timeout in seconds.",
        show_default=False,
    ),
) -> None:
    """Raw experimental path: ACE-Step invents lyrics from a topic.

    The server must have `resident: true` (its 5Hz LM enabled). This path is a
    chaos knob: the same prompt can return a different duration or language.
    For the reliable topic path, use `canturia topic`.
    """
    try:
        console.print(
            "[yellow]Describe is best-effort: Canturía asks for English and "
            "the chosen length, but ACE-Step may ignore both. Use "
            "`canturia topic` or supply lyrics for guarantees.[/yellow]"
        )
        _run_generate(
            "describe",
            topic,
            genre=genre,
            style=style,
            duration=duration,
            out=out,
            config=config,
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            timeout=timeout,
        )
    except (ConfigurationError, AceStepError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


@app.command()
def topic(
    subject: str = typer.Argument(
        ...,
        help="A topic, theme, or sentence; the chosen lyricist writes the lyrics.",
    ),
    lyricist: str | None = typer.Option(
        None,
        "--lyricist",
        help="ollama | openai-compatible | acestep (default: config).",
        show_default=False,
    ),
    genre: str | None = typer.Option(
        None,
        "--genre",
        "-g",
        help="Genre key (folk, pop, rock, indie, lofi, hiphop, …) or free text.",
        show_default=False,
    ),
    style: str | None = typer.Option(
        None,
        "--style",
        "-s",
        help="Extra style details, e.g. 'warm female vocals, fingerpicked guitar'.",
        show_default=False,
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        "-t",
        min=DURATION_MIN,
        max=DURATION_MAX,
        help=f"Length in seconds ({int(DURATION_MIN)}–{int(DURATION_MAX)}).",
        show_default=False,
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Output file (default: derived from the genre and topic).",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Overall generation timeout in seconds.",
        show_default=False,
    ),
) -> None:
    """Write a song from a topic: a lyricist writes, ACE-Step sings.

    The default lyricist is Ollama; choose another with --lyricist. The lyrics
    go to ACE-Step with an exact duration and vocal language. For the raw,
    experimental "ACE-Step invents everything" path, use `canturia describe`.
    """
    try:
        _run_generate(
            "topic",
            subject,
            genre=genre,
            style=style,
            duration=duration,
            out=out,
            config=config,
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            timeout=timeout,
            lyricist=lyricist,
        )
    except (ConfigurationError, AceStepError, OllamaError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


@app.command()
def lyrics(
    topic: str = typer.Argument(
        ...,
        help="A topic, theme, or sentence to write lyrics about.",
    ),
    lyricist: str | None = typer.Option(
        None,
        "--lyricist",
        help="ollama | openai-compatible | acestep (default: config).",
        show_default=False,
    ),
    genre: str | None = typer.Option(
        None,
        "--genre",
        "-g",
        help="Genre key (folk, pop, rock, indie, lofi, hiphop, …) or free text.",
        show_default=False,
    ),
    style: str | None = typer.Option(
        None,
        "--style",
        "-s",
        help="Extra style details for the lyricist.",
        show_default=False,
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        "-t",
        min=DURATION_MIN,
        max=DURATION_MAX,
        help=f"Target length in seconds ({int(DURATION_MIN)}–{int(DURATION_MAX)}).",
        show_default=False,
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write the lyrics to a text file instead of only printing them.",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Overall generation timeout in seconds.",
        show_default=False,
    ),
) -> None:
    """Write lyrics only, without generating audio.

    Useful for comparing lyricists before committing to a generation:

        canturia lyrics "a birthday song for grandma" --lyricist ollama
        canturia lyrics "a birthday song for grandma" --lyricist openai-compatible
    """
    try:
        cfg = _connection_options(
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            config=config,
            timeout=timeout,
        )
        settings = resolve_settings(cfg)
        chosen_genre = genre or str(settings.get("genre") or "folk")
        chosen_style = (
            style if style is not None else str(settings.get("style") or "")
        )
        chosen_duration = (
            duration if duration is not None else settings.get("duration") or 30
        )
        result = lyrics_only(
            topic,
            settings,
            genre=chosen_genre,
            style=chosen_style,
            duration=chosen_duration,
            lyricist=lyricist,
        )
        header = f"{result.provider}"
        if result.model:
            header += f" · {result.model}"
        console.print(f"[dim]{header}[/dim]")
        console.print(result.lyrics)
        if out:
            target = Path(out).expanduser()
            if target.parent != Path("."):
                target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.lyrics + "\n", encoding="utf-8")
            console.print(f"Wrote: [bold green]{target}[/bold green]")
    except (ConfigurationError, AceStepError, OllamaError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


@app.command()
def compare(
    topic: str = typer.Argument(
        ...,
        help="A topic, theme, or sentence to write lyrics about.",
    ),
    with_: list[str] | None = typer.Option(
        None,
        "--with",
        "-w",
        help="Lyricist to compare; repeatable. Defaults to ollama and acestep.",
        show_default=False,
    ),
    genre: str | None = typer.Option(
        None,
        "--genre",
        "-g",
        help="Genre key (folk, pop, rock, indie, lofi, hiphop, …) or free text.",
        show_default=False,
    ),
    style: str | None = typer.Option(
        None,
        "--style",
        "-s",
        help="Extra style details for the lyricists.",
        show_default=False,
    ),
    duration: float | None = typer.Option(
        None,
        "--duration",
        "-t",
        min=DURATION_MIN,
        max=DURATION_MAX,
        help=f"Target length in seconds ({int(DURATION_MIN)}–{int(DURATION_MAX)}).",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
    timeout: float | None = typer.Option(
        None, "--timeout", help="Overall generation timeout in seconds.",
        show_default=False,
    ),
) -> None:
    """Write the same topic with several lyricists and print them side by side."""
    try:
        cfg = _connection_options(
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            config=config,
            timeout=timeout,
        )
        settings = resolve_settings(cfg)
        chosen_genre = genre or str(settings.get("genre") or "folk")
        chosen_style = (
            style if style is not None else str(settings.get("style") or "")
        )
        chosen_duration = (
            duration if duration is not None else settings.get("duration") or 30
        )
        names = with_ or ["ollama", "acestep"]
        results = compare_lyrics(
            topic,
            settings,
            names,
            genre=chosen_genre,
            style=chosen_style,
            duration=chosen_duration,
        )
        for result in results:
            title = result.provider
            if result.model:
                title += f" · {result.model}"
            console.rule(title)
            if result.error:
                console.print(f"[red]{result.error}[/red]")
            else:
                console.print(result.lyrics)
    except (ConfigurationError, AceStepError, OllamaError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


def health_cmd(
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    base_url: str | None = typer.Option(
        None, "--base-url", help="ACE-Step URL (overrides config).",
        show_default=False,
    ),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token for ACE-Step.",
        show_default=False,
    ),
    username: str | None = typer.Option(
        None, "--username", help="HTTP Basic username (reverse proxy).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None, "--password", help="HTTP Basic password (reverse proxy).",
        show_default=False,
    ),
) -> None:
    """Show the configured server's model and lyrics-writer status."""
    try:
        cfg = _connection_options(
            base_url=base_url,
            api_key=api_key,
            username=username,
            password=password,
            config=config,
        )
        settings = resolve_settings(cfg)
        data = health(settings)
        choices = lyricist_choices(settings)
        model = data.get("loaded_model") or "—"
        loaded = "loaded" if data.get("models_initialized") else "not loaded"
        selected = str(settings.get("lyricist") or "ollama")
        table = Table(show_header=False, box=None)
        table.add_row("Server", str(settings["base_url"]))
        table.add_row("Status", str(data.get("status") or "unknown"))
        table.add_row("Model", f"{model} ({loaded})")
        table.add_row("Default lyricist", selected)
        for choice in choices:
            status = "on" if choice["available"] else "off"
            detail = choice["model"] or choice["error"] or ""
            table.add_row(f"  {choice['label']}", f"{status} · {detail}")
        table.add_row(
            "ACE-Step LM",
            "on" if data.get("llm_initialized") else "off",
        )
        console.print(table)
        chosen = next(
            (choice for choice in choices if choice["name"] == selected), None
        )
        if chosen and not chosen["available"]:
            console.print(
                f"[yellow]The default lyricist ({selected}) is unavailable: "
                f"{chosen['error'] or 'not configured'}.[/yellow]"
            )
        if not data.get("llm_initialized"):
            console.print(
                "[yellow]ACE-Step's own LM is off; 'describe' and the "
                "ACE-Step lyricist are unavailable. Set resident: true in "
                "puente.yml to enable them.[/yellow]"
            )
    except (ConfigurationError, AceStepError, OllamaError, LyricistError, ValueError) as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None


app.command(name="health")(health_cmd)


@app.command()
def serve(
    host: str | None = typer.Option(
        None, "--host", help="Address to bind (127.0.0.1 = local only).",
        show_default=False,
    ),
    port: int | None = typer.Option(
        None, "--port", help="Port to listen on (default: 2268).",
        show_default=False,
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Shared password for the web UI; generated when binding non-locally.",
        show_default=False,
    ),
    out_dir: str | None = typer.Option(
        None, "--out-dir", help="Directory Save writes songs into.",
        show_default=False,
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", help="Config file (default: ./canturia.yaml).",
        show_default=False,
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't auto-open the browser."
    ),
    desktop: bool = typer.Option(
        False,
        "--desktop",
        help="Desktop sidecar mode: hide the web Lock button.",
    ),
) -> None:
    r"""Run the local web UI (needs: pip install 'canturia\[serve]')."""
    import threading
    import webbrowser

    try:
        import uvicorn

        from canturia.serve import create_app
    except ImportError:
        err_console.print(
            "The web UI needs extra dependencies: pip install 'canturia[serve]'"
        )
        raise typer.Exit(code=1) from None

    try:
        cfg = load_config(config)
        serve_cfg = resolve_serve_settings(cfg)
    except ConfigurationError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from None

    chosen_host = host or str(serve_cfg["host"])
    chosen_port = port or int(serve_cfg["port"])
    chosen_out = out_dir or str(serve_cfg["out_dir"])
    chosen_password = (
        password
        if password is not None
        else os.getenv("CANTURIA_SERVE_PASSWORD") or serve_cfg.get("password")
    )
    if chosen_password is not None and str(chosen_password).strip() == "":
        chosen_password = None

    local = chosen_host in ("127.0.0.1", "localhost", "::1")
    generated_password = False
    if not local and not chosen_password:
        chosen_password = secrets.token_urlsafe(12)
        generated_password = True
        console.print(f"Generated password: [bold]{chosen_password}[/bold]")

    application = create_app(
        cfg,
        password=str(chosen_password) if chosen_password else None,
        out_dir=Path(chosen_out).expanduser(),
        desktop=desktop,
    )

    url = f"http://{chosen_host}:{chosen_port}/"
    console.print(f"Canturía web UI: [bold green]{url}[/bold green]  (Ctrl+C to stop)")
    if generated_password:
        console.print(f"Password: [bold]{chosen_password}[/bold]")
    elif chosen_password:
        console.print("Password: set (not echoed).")
    if not no_browser and local:
        threading.Timer(0.8, webbrowser.open, args=[url]).start()

    uvicorn.run(application, host=chosen_host, port=chosen_port, log_level="warning")
