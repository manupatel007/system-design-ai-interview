from __future__ import annotations

import argparse
import hashlib
import os
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / ".models"
CACHE_ROOT = PROJECT_ROOT / ".cache"

SILERO_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/"
    "76e3dc408eb2a5c655c34e230d2d5459b4439daa/"
    "src/silero_vad/data/silero_vad.onnx"
)
SILERO_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
SAMPLE_URL = (
    "https://raw.githubusercontent.com/ggml-org/whisper.cpp/"
    "1fe009caeda75f69bc864d6370b10674e45a92bd/samples/jfk.wav"
)
SAMPLE_SHA256 = "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _sha256(destination) == expected_sha256:
        print(f"ready: {destination.relative_to(PROJECT_ROOT)}")
        return
    temporary = destination.with_suffix(destination.suffix + ".download")
    urllib.request.urlretrieve(url, temporary)
    actual_sha256 = _sha256(temporary)
    if actual_sha256 != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {destination.name}: {actual_sha256}"
        )
    temporary.replace(destination)
    print(f"downloaded: {destination.relative_to(PROJECT_ROOT)}")


def download_silero() -> None:
    _download(
        SILERO_URL,
        MODEL_ROOT / "silero-vad" / "silero_vad.onnx",
        SILERO_SHA256,
    )


def download_whisper() -> None:
    from huggingface_hub import snapshot_download

    destination = MODEL_ROOT / "faster-whisper-base.en"
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="Systran/faster-whisper-base.en",
        local_dir=destination,
        cache_dir=CACHE_ROOT / "huggingface" / "hub",
    )
    print(f"ready: {destination.relative_to(PROJECT_ROOT)}")


def download_sample() -> None:
    _download(
        SAMPLE_URL,
        CACHE_ROOT / "test-assets" / "jfk.wav",
        SAMPLE_SHA256,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download local voice models to F drive")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--silero", action="store_true")
    parser.add_argument("--whisper", action="store_true")
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    selected = args.all or not (args.silero or args.whisper or args.sample)
    os.environ.setdefault("HF_HOME", str(CACHE_ROOT / "huggingface"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_ROOT / "huggingface" / "hub"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    if selected or args.silero:
        download_silero()
    if selected or args.whisper:
        download_whisper()
    if selected or args.sample:
        download_sample()


if __name__ == "__main__":
    main()
