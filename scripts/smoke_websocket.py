from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from websockets.asyncio.client import connect


async def run(base_url: str) -> None:
    session_id = f"smoke-{uuid.uuid4()}"
    async with connect(
        f"{base_url.rstrip('/')}/ws/interview/{session_id}", proxy=None
    ) as socket:
        ready = json.loads(await socket.recv())
        if ready.get("type") != "session.ready":
            raise RuntimeError(f"Unexpected first event: {ready}")
        await socket.send(
            json.dumps(
                {
                    "type": "session.configure",
                    "payload": {
                        "problem": "Design a URL shortener",
                        "glossary": ["Redis", "PostgreSQL", "base62"],
                    },
                }
            )
        )
        configured = json.loads(await socket.recv())
        if configured.get("type") != "session.configured":
            raise RuntimeError(f"Unexpected configuration event: {configured}")
        await socket.send(bytes(512 * 2))
        await socket.send(json.dumps({"type": "audio.flush", "payload": {}}))
        print(
            json.dumps(
                {
                    "ready": ready["payload"],
                    "configured": True,
                    "silenceFrameAccepted": True,
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the realtime WebSocket")
    parser.add_argument("url", nargs="?", default="ws://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
