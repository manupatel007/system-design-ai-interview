from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any

import av
import numpy as np
import websockets
from capture_readme_demos import (
    DevTools,
    _append_demo_turn,
    _browser_path,
    _browser_websocket,
    _caption,
    _free_port,
    _point_to,
    _stop_process,
    _wait_for,
    _wait_for_url,
)
from PIL import Image

from voice_interviewer.tts.kokoro import KokoroTTS
from voice_interviewer.tts.piper import PiperTTS

AUDIO_RATE = 48_000
FPS = 24
VIEWPORT_WIDTH = 1440
VIEWPORT_HEIGHT = 900
OUTPUT_WIDTH = 1120
OUTPUT_HEIGHT = 700


@dataclass(frozen=True)
class Scene:
    png: bytes
    audio: np.ndarray


class Voices:
    def __init__(self, root: Path, candidate_voice: str) -> None:
        self.interviewer = PiperTTS(
            model_path=root / ".models" / "piper" / "en_US-lessac-medium.onnx",
            config_path=root / ".models" / "piper" / "en_US-lessac-medium.onnx.json",
            speed=1.08,
        )
        self.candidate = KokoroTTS(
            model_path=root / ".models" / "kokoro" / "kokoro-v1.0.int8.onnx",
            voices_path=root / ".models" / "kokoro" / "voices-v1.0.bin",
            voice=candidate_voice,
            speed=1.08,
        )

    async def load(self) -> None:
        await self.interviewer.load()
        await self.candidate.load()

    async def synthesize(self, speaker: str, text: str) -> np.ndarray:
        backend = self.interviewer if speaker == "interviewer" else self.candidate
        output = await backend.synthesize(text)
        samples = np.frombuffer(output.pcm_s16le, dtype="<i2").astype(np.float32)
        if output.channels != 1:
            samples = samples.reshape(-1, output.channels).mean(axis=1)
        samples /= 32_768.0
        if output.sample_rate != AUDIO_RATE:
            source = np.arange(len(samples), dtype=np.float64)
            target_length = round(len(samples) * AUDIO_RATE / output.sample_rate)
            target = np.linspace(0, max(0, len(samples) - 1), target_length)
            samples = np.interp(target, source, samples).astype(np.float32)
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        if peak > 0:
            samples *= min(1.0, 0.9 / peak)
        fade_samples = min(round(AUDIO_RATE * 0.015), len(samples) // 2)
        if fade_samples:
            fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
            samples[:fade_samples] *= fade
            samples[-fade_samples:] *= fade[::-1]
        return np.clip(samples * 32_767, -32_768, 32_767).astype("<i2")


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(round(AUDIO_RATE * seconds), dtype="<i2")


def _with_breathing_room(audio: np.ndarray) -> np.ndarray:
    return np.concatenate((_silence(0.12), audio, _silence(0.38)))


async def _subtitle(devtools: DevTools, speaker: str, text: str) -> None:
    label = "AI INTERVIEWER" if speaker == "interviewer" else "CANDIDATE"
    accent = "#a78bfa" if speaker == "interviewer" else "#60a5fa"
    await devtools.evaluate(
        f"""
        (() => {{
          let subtitle = document.querySelector('#end-to-end-demo-subtitle');
          if (!subtitle) {{
            subtitle = document.createElement('div');
            subtitle.id = 'end-to-end-demo-subtitle';
            Object.assign(subtitle.style, {{
              position: 'fixed', left: '50%', bottom: '84px', transform: 'translateX(-50%)',
              zIndex: '100001', width: 'min(920px, 78vw)', padding: '12px 18px',
              color: '#f8fafc', background: 'rgba(2, 6, 23, .92)',
              border: '1px solid rgba(148, 163, 184, .42)', borderRadius: '14px',
              boxShadow: '0 16px 44px rgba(0,0,0,.5)',
              font: '500 17px/1.4 system-ui, sans-serif', pointerEvents: 'none'
            }});
            document.body.append(subtitle);
          }}
          subtitle.innerHTML = '';
          const label = document.createElement('strong');
          label.textContent = {json.dumps(label)};
          Object.assign(label.style, {{
            display: 'block', marginBottom: '3px', color: {json.dumps(accent)},
            font: '700 11px/1.2 system-ui, sans-serif', letterSpacing: '.12em'
          }});
          const copy = document.createElement('span');
          copy.textContent = {json.dumps(text)};
          subtitle.append(label, copy);
        }})()
        """
    )


async def _render_turn(
    devtools: DevTools,
    speaker: str,
    text: str,
    *,
    phase: str | None = None,
) -> None:
    await _caption(devtools, "100% LOCAL VOICE • CANVAS-AWARE INTERVIEW")
    await _subtitle(devtools, speaker, text)
    await devtools.evaluate(
        f"""
        (() => {{
          document.querySelector('#readme-demo-pointer')?.remove();
          const candidate = {json.dumps(speaker == "candidate")};
          const candidateCard = document.querySelector('#candidate-card');
          const interviewerCard = document.querySelector('#interviewer-card');
          candidateCard.classList.toggle('is-active', candidate);
          interviewerCard.classList.toggle('is-active', !candidate);
          const candidateState = document.querySelector('#candidate-state');
          const interviewerState = document.querySelector('#interviewer-state');
          candidateState.textContent = candidate ? 'Speaking' : 'Listening';
          interviewerState.textContent = candidate ? 'Listening' : 'Speaking';
          document.querySelector(candidate ? '#candidate' : '#interviewer').textContent =
            {json.dumps(text)};
          if ({json.dumps(phase)} !== null) {{
            document.querySelector('#interview-phase').textContent = {json.dumps(phase)};
          }}
          document.querySelector('#transcript-scroll').scrollTop =
            document.querySelector('#transcript-scroll').scrollHeight;
        }})()
        """
    )
    await asyncio.sleep(0.15)


async def _spoken_scene(
    scenes: list[Scene],
    devtools: DevTools,
    voices: Voices,
    speaker: str,
    text: str,
    *,
    append_transcript: bool = True,
    phase: str | None = None,
) -> None:
    if append_transcript:
        await _append_demo_turn(devtools, speaker, text)
    await _render_turn(devtools, speaker, text, phase=phase)
    audio = await voices.synthesize(speaker, text)
    scenes.append(Scene(await devtools.screenshot(), _with_breathing_room(audio)))


async def _action_scene(
    scenes: list[Scene],
    devtools: DevTools,
    label: str,
    selector: str,
) -> None:
    await _subtitle(devtools, "candidate", label)
    await _point_to(devtools, selector)
    scenes.append(Scene(await devtools.screenshot(), _silence(0.85)))


async def _read_interviewer_text(devtools: DevTools) -> str:
    text = await devtools.evaluate("document.querySelector('#interviewer').textContent.trim()")
    if not isinstance(text, str) or not text:
        raise RuntimeError("The UI did not expose an interviewer response")
    return text


async def _capture_dialogue(devtools: DevTools, voices: Voices) -> list[Scene]:
    scenes: list[Scene] = []
    await _wait_for(devtools, "document.readyState === 'complete'")
    await _wait_for(devtools, "window.__diagramSnapshot && document.querySelector('#connect')")
    await devtools.evaluate("document.querySelector('#connect').click()")
    await _wait_for(devtools, "document.querySelector('#status').textContent === 'Connected'")
    await _wait_for(
        devtools, "document.querySelectorAll('.transcript-entry.interviewer').length > 0"
    )
    await _wait_for(devtools, "!document.querySelector('#walk-through').disabled")

    opening = await _read_interviewer_text(devtools)
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        opening,
        append_transcript=False,
        phase="Requirements",
    )

    requirements = (
        "Users create short links and follow redirects. I'll assume one hundred million "
        "new links monthly, with ten times more reads than writes."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "candidate",
        requirements,
        phase="Requirements",
    )

    request_path = (
        "Good. Show me the synchronous request path, and tell me where the short code is resolved."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        request_path,
        phase="High-level design",
    )

    takeover_request = (
        "Clients enter through a load balancer, then reach a stateless URL service. "
        "Walk me through that baseline while I explain the trade-offs."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "candidate",
        takeover_request,
        phase="High-level design",
    )
    await _action_scene(
        scenes,
        devtools,
        "The candidate explicitly asks for Guided Takeover",
        "#walk-through",
    )
    await devtools.evaluate("document.querySelector('#walk-through').click()")
    await _wait_for(devtools, "!document.querySelector('#guided-takeover').hidden")
    await _wait_for(
        devtools, "document.querySelector('#guided-progress').textContent.includes('Step 1')"
    )
    await _wait_for(devtools, "!document.querySelector('#guided-continue').disabled")
    step_one = await _read_interviewer_text(devtools)
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        step_one,
        append_transcript=False,
        phase="Guided takeover",
    )

    continue_service = "That boundary makes sense. Continue to the stateless service layer."
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "candidate",
        continue_service,
        phase="Guided takeover",
    )
    await _action_scene(scenes, devtools, "Continue when the concept is clear", "#guided-continue")
    await devtools.evaluate("document.querySelector('#guided-continue').click()")
    await _wait_for(
        devtools, "document.querySelector('#guided-progress').textContent.includes('Step 2')"
    )
    await _wait_for(devtools, "!document.querySelector('#guided-continue').disabled")
    step_two = await _read_interviewer_text(devtools)
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        step_two,
        append_transcript=False,
        phase="Guided takeover",
    )

    continue_data = (
        "Now add the read cache and primary store. I want the database to remain "
        "the source of truth."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "candidate",
        continue_data,
        phase="Guided takeover",
    )
    await _action_scene(
        scenes, devtools, "Build the next bounded architecture step", "#guided-continue"
    )
    await devtools.evaluate("document.querySelector('#guided-continue').click()")
    await _wait_for(
        devtools, "document.querySelector('#guided-progress').textContent.includes('Step 3')"
    )
    await _wait_for(devtools, "!document.querySelector('#guided-continue').disabled")
    step_three = await _read_interviewer_text(devtools)
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        step_three,
        append_transcript=False,
        phase="Guided takeover",
    )

    failure_answer = (
        "On a cache miss, the service reads once and repopulates Redis with a TTL. "
        "If Redis fails, rate limits and request coalescing protect the database."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "candidate",
        failure_answer,
        phase="Deep dive",
    )

    await devtools.evaluate(
        """
        (() => {
          const nodes = window.__diagramSnapshot.assistantLayer.nodes
            .filter((node) => ['cache', 'database'].includes(node.role));
          window.dispatchEvent(new CustomEvent('diagram.feedback.show', {detail: {
            feedbackId: 'voice-demo-grounding', focus: true, durationMs: 30000,
            references: [{kind: 'strength', label: 'Cache failure path',
              objectIds: nodes.map((node) => node.id), displayIndex: 1}]
          }}));
        })()
        """
    )
    closing = (
        "Clear. Your explanation now matches these exact components. Next I would probe "
        "hot keys, sharding, and failure isolation."
    )
    await _spoken_scene(
        scenes,
        devtools,
        voices,
        "interviewer",
        closing,
        phase="Deep dive",
    )
    scenes.append(Scene(await devtools.screenshot(), _silence(1.2)))
    return scenes


def _scene_pixels(png: bytes) -> np.ndarray:
    with Image.open(BytesIO(png)) as image:
        frame = image.convert("RGB").resize(
            (OUTPUT_WIDTH, OUTPUT_HEIGHT),
            Image.Resampling.LANCZOS,
        )
    return np.asarray(frame)


def _encode_video(scenes: list[Scene], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(output), "w", options={"movflags": "+faststart"})
    video_stream = container.add_stream("libx264", rate=FPS)
    video_stream.width = OUTPUT_WIDTH
    video_stream.height = OUTPUT_HEIGHT
    video_stream.pix_fmt = "yuv420p"
    video_stream.options = {"crf": "24", "preset": "medium"}
    audio_stream = container.add_stream("aac", rate=AUDIO_RATE)
    audio_stream.layout = "mono"
    audio_stream.bit_rate = 96_000

    frame_index = 0
    for scene in scenes:
        pixels = _scene_pixels(scene.png)
        frame_count = max(1, round(len(scene.audio) * FPS / AUDIO_RATE))
        for _ in range(frame_count):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = frame_index
            frame.time_base = Fraction(1, FPS)
            frame_index += 1
            for packet in video_stream.encode(frame):
                container.mux(packet)
    for packet in video_stream.encode():
        container.mux(packet)

    audio = np.concatenate([scene.audio for scene in scenes])
    sample_offset = 0
    for start in range(0, len(audio), 1024):
        chunk = audio[start : start + 1024]
        frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = AUDIO_RATE
        frame.pts = sample_offset
        frame.time_base = Fraction(1, AUDIO_RATE)
        sample_offset += len(chunk)
        for packet in audio_stream.encode(frame):
            container.mux(packet)
    for packet in audio_stream.encode():
        container.mux(packet)
    container.close()


def _write_poster(png: bytes, output: Path) -> None:
    with Image.open(BytesIO(png)) as image:
        poster = image.convert("RGB").resize(
            (OUTPUT_WIDTH, OUTPUT_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        poster.save(output, format="JPEG", quality=86, optimize=True)


async def _record(
    args: argparse.Namespace,
    root: Path,
    runtime: Path,
    output: Path,
    server_log: Any,
    browser_log: Any,
) -> None:
    voices = Voices(root, args.candidate_voice)
    await voices.load()
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
            scenes = await _capture_dialogue(devtools, voices)

        await asyncio.to_thread(_encode_video, scenes, output)
        poster_scene = scenes[-2] if len(scenes) > 1 else scenes[0]
        await asyncio.to_thread(
            _write_poster,
            poster_scene.png,
            output.with_name("end-to-end-voice-demo-poster.jpg"),
        )
    finally:
        if browser is not None:
            await _stop_process(browser)
        await _stop_process(server)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a locally voiced end-to-end interview demo"
    )
    parser.add_argument("--browser", help="Path to a Chromium-based browser executable")
    parser.add_argument("--candidate-voice", default="am_michael", help="Kokoro voice key")
    parser.add_argument(
        "--output",
        default="docs/assets/end-to-end-voice-demo.mp4",
        help="Repository-relative MP4 destination",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    runtime = root / ".runtime" / "end-to-end-demo"
    output = root / args.output
    shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True)
    with (
        (runtime / "server.log").open("w", encoding="utf-8") as server_log,
        (runtime / "browser.log").open("w", encoding="utf-8") as browser_log,
    ):
        asyncio.run(_record(args, root, runtime, output, server_log, browser_log))
    print(f"Created {output.relative_to(root)} ({output.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
