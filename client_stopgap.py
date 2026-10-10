#!/usr/bin/env python3
"""
client_stopgap.py — quick bridge while the native macOS overlay app isn't built yet.

Run this ON YOUR MACBOOK (not the Mac Mini). It captures your microphone,
chunks it like live_translate.py does, and POSTs each chunk to the
live-en-zh-api server running on the Mac Mini over Tailscale — printing the
Chinese translation to the terminal live.

Setup (on the MacBook):
    python3 -m venv .venv
    source .venv/bin/activate
    pip install sounddevice numpy requests soundfile

Usage:
    python client_stopgap.py                              # uses default server URL below
    python client_stopgap.py --server http://100.118.167.42:8731
    python client_stopgap.py --list-devices
    python client_stopgap.py --device 2
"""

from __future__ import annotations

import argparse
import io
import queue
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np
import requests
import soundfile as sf

SAMPLE_RATE = 16_000
BLOCK_MS = 30
BLOCK_SAMPLES = int(SAMPLE_RATE * BLOCK_MS / 1000)

DEFAULT_SERVER = "http://100.118.167.42:8731"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mic -> live-en-zh-api client (stopgap bridge).")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--device", type=int, default=None)
    p.add_argument("--server", type=str, default=DEFAULT_SERVER)
    p.add_argument("--silence-ms", type=int, default=600)
    p.add_argument("--min-chunk-s", type=float, default=1.0)
    p.add_argument("--max-chunk-s", type=float, default=6.0)
    p.add_argument("--energy-threshold", type=float, default=0.012)
    return p.parse_args()


def list_devices() -> None:
    import sounddevice as sd

    print("Available audio input devices:\n")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            print(f"  [{idx}] {dev['name']} — {dev['max_input_channels']}ch")


@dataclass
class Segmenter:
    silence_blocks: int
    min_chunk_samples: int
    max_chunk_samples: int
    energy_threshold: float

    def __post_init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._silence_run = 0
        self._in_speech = False

    def push(self, block: np.ndarray):
        rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
        is_speech = rms >= self.energy_threshold

        if is_speech:
            self._buffer.append(block)
            self._silence_run = 0
            self._in_speech = True
        elif self._in_speech:
            self._buffer.append(block)
            self._silence_run += 1

        total = sum(len(b) for b in self._buffer)
        flush = (self._in_speech and self._silence_run >= self.silence_blocks) or total >= self.max_chunk_samples

        if flush and self._buffer:
            seg = np.concatenate(self._buffer)
            self._buffer = []
            self._silence_run = 0
            self._in_speech = False
            if len(seg) >= self.min_chunk_samples:
                return seg
        return None


def main() -> None:
    args = parse_args()
    if args.list_devices:
        list_devices()
        return

    import sounddevice as sd

    try:
        r = requests.get(f"{args.server}/health", timeout=3)
        print(f"Server health: {r.json()}")
    except Exception as exc:
        print(f"WARNING: could not reach server at {args.server}/health ({exc}). Continuing anyway...")

    seg = Segmenter(
        silence_blocks=max(1, int(args.silence_ms / BLOCK_MS)),
        min_chunk_samples=int(args.min_chunk_s * SAMPLE_RATE),
        max_chunk_samples=int(args.max_chunk_s * SAMPLE_RATE),
        energy_threshold=args.energy_threshold,
    )

    q: "queue.Queue[np.ndarray]" = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[audio status] {status}", file=sys.stderr)
        q.put(indata[:, 0].copy())

    stream_kwargs = dict(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK_SAMPLES, callback=callback)
    if args.device is not None:
        stream_kwargs["device"] = args.device

    stop_event = threading.Event()

    def worker():
        while not stop_event.is_set():
            try:
                block = q.get(timeout=0.5)
            except queue.Empty:
                continue
            segment = seg.push(block)
            if segment is None:
                continue

            buf = io.BytesIO()
            sf.write(buf, segment, SAMPLE_RATE, format="WAV")
            buf.seek(0)

            ts = time.strftime("%H:%M:%S")
            try:
                resp = requests.post(
                    f"{args.server}/translate",
                    files={"audio": ("chunk.wav", buf, "audio/wav")},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data["en"]:
                    print(f"[{ts}] EN: {data['en']}")
                    print(f"[{ts}] ZH: {data['zh']}\n")
            except Exception as exc:
                print(f"[{ts}] request error: {exc}", file=sys.stderr)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    print(f"Listening (server: {args.server})... Ctrl+C to stop.\n")
    try:
        with sd.InputStream(**stream_kwargs):
            while True:
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop_event.set()
        t.join(timeout=2)


if __name__ == "__main__":
    main()
