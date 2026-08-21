from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import socket
import sys
import time
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import websockets
from PIL import Image

VIEWPORT_WIDTH = 1440
VIEWPORT_HEIGHT = 900
OUTPUT_WIDTH = 1120


@dataclass(frozen=True)
class Frame:
    png: bytes
    duration_ms: int


class DevTools:
    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self._identifier = 0

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._identifier += 1
        identifier = self._identifier
        await self.websocket.send(
            json.dumps({"id": identifier, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(await self.websocket.recv())
            if message.get("id") != identifier:
                continue
            if "error" in message:
                raise RuntimeError(f"DevTools {method} failed: {message['error']}")
            return message.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        response = await self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        result = response.get("result", {})
        if result.get("subtype") == "error":
            raise RuntimeError(result.get("description", "Browser evaluation failed"))
        return result.get("value")

    async def screenshot(self) -> bytes:
        response = await self.call(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        )
        return base64.b64decode(response["data"])


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _browser_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Browser executable does not exist: {path}")

    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for command in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "chromium"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(Path(resolved))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Install Microsoft Edge/Chrome or pass --browser PATH")


def _wait_for_url(url: str, timeout_seconds: float = 20) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}")


def _browser_websocket(port: int, timeout_seconds: float = 20) -> str:
    deadline = time.monotonic() + timeout_seconds
    endpoint = f"http://127.0.0.1:{port}/json/list"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1) as response:
                targets = json.load(response)
            pages = [target for target in targets if target.get("type") == "page"]
            if pages:
                return str(pages[0]["webSocketDebuggerUrl"])
        except (OSError, KeyError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise TimeoutError("Timed out waiting for the browser debugging endpoint")


async def _wait_for(
    devtools: DevTools,
    expression: str,
    *,
    timeout_seconds: float = 15,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if await devtools.evaluate(f"Boolean({expression})"):
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Browser condition did not become true: {expression}")


async def _caption(devtools: DevTools, text: str) -> None:
    encoded = json.dumps(text)
    await devtools.evaluate(
        f"""
        (() => {{
          let caption = document.querySelector('#readme-demo-caption');
          if (!caption) {{
            caption = document.createElement('div');
            caption.id = 'readme-demo-caption';
            Object.assign(caption.style, {{
              position: 'fixed', top: '18px', left: '50%', transform: 'translateX(-50%)',
              zIndex: '99999', padding: '10px 18px', borderRadius: '999px',
              color: '#f8fafc', background: 'rgba(15, 23, 42, .92)',
              border: '1px solid rgba(167, 139, 250, .65)',
              boxShadow: '0 12px 35px rgba(0,0,0,.35)',
              font: '600 16px/1.2 system-ui, sans-serif', pointerEvents: 'none'
            }});
            document.body.append(caption);
          }}
          caption.textContent = {encoded};
        }})()
        """
    )


async def _point_to(devtools: DevTools, selector: str) -> None:
    encoded = json.dumps(selector)
    await devtools.evaluate(
        f"""
        (() => {{
          const target = document.querySelector({encoded});
          if (!target) throw new Error('Missing pointer target: ' + {encoded});
          let pointer = document.querySelector('#readme-demo-pointer');
          if (!pointer) {{
            pointer = document.createElement('div');
            pointer.id = 'readme-demo-pointer';
            pointer.innerHTML = `<svg width="34" height="42" viewBox="0 0 34 42" aria-hidden="true">
              <path d="M3 2 L30 24 L18 26 L24 39 L17 41 L11 28 L3 36 Z"
                fill="#fff" stroke="#111827" stroke-width="2" stroke-linejoin="round"/>
            </svg>`;
            Object.assign(pointer.style, {{
              position: 'fixed', zIndex: '100000', width: '34px', height: '42px',
              filter: 'drop-shadow(0 4px 5px rgba(0,0,0,.5))', pointerEvents: 'none',
              transition: 'left .35s ease, top .35s ease'
            }});
            document.body.append(pointer);
          }}
          const bounds = target.getBoundingClientRect();
          pointer.style.left = `${{Math.round(bounds.left + bounds.width * .55)}}px`;
          pointer.style.top = `${{Math.round(bounds.top + bounds.height * .5)}}px`;
        }})()
        """
    )
    await asyncio.sleep(0.4)


async def _append_demo_turn(devtools: DevTools, speaker: str, message: str) -> None:
    await devtools.evaluate(
        f"""
        (() => {{
          const feed = document.querySelector('#transcript-feed');
          document.querySelector('#transcript-empty').hidden = true;
          const entry = document.createElement('article');
          entry.className = 'transcript-entry ' + {json.dumps(speaker)};
          const header = document.createElement('header');
          const name = document.createElement('span');
          name.className = 'transcript-speaker';
          name.textContent = {json.dumps("You" if speaker == "candidate" else "AI interviewer")};
          const time = document.createElement('time');
          time.className = 'transcript-time';
          time.textContent = 'now';
          const copy = document.createElement('p');
          copy.textContent = {json.dumps(message)};
          header.append(name, time);
          entry.append(header, copy);
          feed.append(entry);
          document.querySelector('#transcript-scroll').scrollTop =
            document.querySelector('#transcript-scroll').scrollHeight;
        }})()
        """
    )


async def _add_frame(
    clips: dict[str, list[Frame]],
    clip: str,
    devtools: DevTools,
    duration_ms: int,
) -> None:
    clips.setdefault(clip, []).append(Frame(await devtools.screenshot(), duration_ms))


async def _capture_frames(devtools: DevTools) -> dict[str, list[Frame]]:
    clips: dict[str, list[Frame]] = {}
    await _wait_for(devtools, "document.readyState === 'complete'")
    await _wait_for(devtools, "window.__diagramSnapshot && document.querySelector('#connect')")

    await _caption(devtools, "Start a realistic system-design interview")
    await _point_to(devtools, "#connect")
    await _add_frame(clips, "interview-loop", devtools, 1100)
    await devtools.evaluate("document.querySelector('#connect').click()")
    await asyncio.sleep(0.25)
    await _add_frame(clips, "interview-loop", devtools, 450)
    await _wait_for(devtools, "document.querySelector('#status').textContent === 'Connected'")
    await _caption(devtools, "The interviewer opens with a focused question")
    await _add_frame(clips, "interview-loop", devtools, 650)
    await _wait_for(
        devtools, "document.querySelectorAll('.transcript-entry.interviewer').length > 0"
    )
    await _wait_for(devtools, "!document.querySelector('#walk-through').disabled")
    await _add_frame(clips, "interview-loop", devtools, 1900)

    await _append_demo_turn(devtools, "candidate", "Can you show me what I should draw next?")
    await _caption(devtools, "Ask for help; review the proposal before it touches your design")
    proposal = {
        "kind": "scoped",
        "title": "Make the request path explicit",
        "summary": "Add a gateway boundary and label the synchronous flow.",
        "nodes": [
            {"id": "demo-client", "label": "Web / Mobile Clients", "role": "client", "layer": 0},
            {
                "id": "demo-gateway",
                "label": "API Gateway",
                "role": "load_balancer",
                "layer": 1,
            },
            {"id": "demo-service", "label": "URL Service", "role": "service", "layer": 2},
        ],
        "edges": [
            {
                "id": "demo-client-gateway",
                "sourceId": "demo-client",
                "targetId": "demo-gateway",
                "label": "HTTPS",
            },
            {
                "id": "demo-gateway-service",
                "sourceId": "demo-gateway",
                "targetId": "demo-service",
                "label": "route",
            },
        ],
    }
    await devtools.evaluate(
        "window.dispatchEvent(new CustomEvent('diagram.proposal.show', {detail: "
        + json.dumps(
            {
                "proposal": proposal,
                "anchorObjectIds": [],
                "proposalId": "readme-scoped-help",
                "autoAccept": False,
            }
        )
        + "}))"
    )
    await asyncio.sleep(0.15)
    await _add_frame(clips, "canvas-help", devtools, 350)
    await asyncio.sleep(0.5)
    await _wait_for(devtools, "document.querySelector('.ai-preview-button')")
    await _point_to(devtools, ".ai-preview-button")
    await _add_frame(clips, "canvas-help", devtools, 1200)
    await devtools.evaluate("document.querySelector('.ai-preview-button').click()")
    await _caption(devtools, "Keep, reject, edit, or undo—candidate work stays separate")
    await asyncio.sleep(0.35)
    await _add_frame(clips, "canvas-help", devtools, 1800)

    await devtools.evaluate("window.dispatchEvent(new Event('diagram.clear'))")
    await _wait_for(devtools, "window.__diagramSnapshot.nodes.length === 0")
    await _caption(devtools, "Guided Takeover explains the architecture one bounded step at a time")
    await _point_to(devtools, "#walk-through")
    await _add_frame(clips, "guided-takeover", devtools, 900)
    await devtools.evaluate("document.querySelector('#walk-through').click()")
    await _wait_for(devtools, "!document.querySelector('#guided-takeover').hidden")
    await _wait_for(
        devtools, "document.querySelector('#guided-progress').textContent.includes('Step 1')"
    )
    await _wait_for(devtools, "!document.querySelector('#guided-continue').disabled")
    await _add_frame(clips, "guided-takeover", devtools, 1600)

    for expected_step in (2, 3):
        await _point_to(devtools, "#guided-continue")
        await _add_frame(clips, "guided-takeover", devtools, 500)
        await devtools.evaluate("document.querySelector('#guided-continue').click()")
        progress_condition = (
            "document.querySelector('#guided-progress').textContent.includes('Step "
            + str(expected_step)
            + "')"
        )
        await _wait_for(devtools, progress_condition)
        await _wait_for(devtools, "!document.querySelector('#guided-continue').disabled")
        await _add_frame(clips, "guided-takeover", devtools, 1500)

    return clips


def _write_gif(frames: list[Frame], output: Path) -> None:
    images: list[Image.Image] = []
    target_height = round(VIEWPORT_HEIGHT * OUTPUT_WIDTH / VIEWPORT_WIDTH)
    for frame in frames:
        with Image.open(BytesIO(frame.png)) as image:
            images.append(
                image.convert("RGB").resize(
                    (OUTPUT_WIDTH, target_height),
                    Image.Resampling.LANCZOS,
                )
            )

    thumbnail_width = max(1, OUTPUT_WIDTH // 5)
    thumbnail_height = max(1, target_height // 5)
    palette_source = Image.new("RGB", (thumbnail_width, thumbnail_height * len(images)))
    for index, image in enumerate(images):
        palette_source.paste(
            image.resize((thumbnail_width, thumbnail_height), Image.Resampling.BILINEAR),
            (0, index * thumbnail_height),
        )
    palette = palette_source.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    indexed = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]

    output.parent.mkdir(parents=True, exist_ok=True)
    indexed[0].save(
        output,
        save_all=True,
        append_images=indexed[1:],
        duration=[frame.duration_ms for frame in frames],
        loop=0,
        optimize=True,
        disposal=2,
    )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


async def _record(
    args: argparse.Namespace,
    root: Path,
    runtime: Path,
    output: Path,
    server_log: Any,
    browser_log: Any,
) -> None:
    app_port = _free_port()
    debug_port = _free_port()
    app_url = f"http://127.0.0.1:{app_port}"
    server = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from voice_interviewer.cli import main; main()",
        "serve",
        "--mock",
        "--host",
        "127.0.0.1",
        "--port",
        str(app_port),
        cwd=root,
        stdout=server_log,
        stderr=asyncio.subprocess.STDOUT,
    )
    browser: asyncio.subprocess.Process | None = None
    try:
        await asyncio.to_thread(_wait_for_url, f"{app_url}/health")
        browser_path = await asyncio.to_thread(_browser_path, args.browser)
        browser = await asyncio.create_subprocess_exec(
            str(browser_path),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={runtime / 'browser-profile'}",
            f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
            app_url,
            cwd=root,
            stdout=browser_log,
            stderr=asyncio.subprocess.STDOUT,
        )
        websocket_url = await asyncio.to_thread(_browser_websocket, debug_port)
        async with websockets.connect(websocket_url, max_size=None) as websocket:
            devtools = DevTools(websocket)
            await devtools.call("Page.enable")
            await devtools.call("Runtime.enable")
            await devtools.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": VIEWPORT_WIDTH,
                    "height": VIEWPORT_HEIGHT,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            clips = await _capture_frames(devtools)

        for name, frames in clips.items():
            destination = output / f"{name}.gif"
            await asyncio.to_thread(_write_gif, frames, destination)
            size_bytes = await asyncio.to_thread(lambda path=destination: path.stat().st_size)
            print(f"Created {destination.relative_to(root)} ({size_bytes / 1_048_576:.1f} MB)")
    finally:
        if browser is not None:
            await _stop_process(browser)
        await _stop_process(server)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture README GIFs from the real local UI")
    parser.add_argument("--browser", help="Path to a Chromium-based browser executable")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    runtime = root / ".runtime" / "readme-capture"
    output = root / "docs" / "assets"
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True)
    with (
        (runtime / "server.log").open("w", encoding="utf-8") as server_log,
        (runtime / "browser.log").open("w", encoding="utf-8") as browser_log,
    ):
        asyncio.run(_record(args, root, runtime, output, server_log, browser_log))


if __name__ == "__main__":
    main()
