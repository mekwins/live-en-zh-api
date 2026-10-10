#!/usr/bin/env python3
"""
live-en-zh-api: REST API for local English speech -> Chinese text translation.

Pipeline (fully local, Apple Silicon Metal GPU):
    audio bytes (wav/m4a/mp3/etc, any ffmpeg-readable format)
      -> Parakeet-MLX (English ASR, Metal GPU)
      -> Argos Translate (English -> Chinese, offline NMT)
      -> JSON response { "en": "...", "zh": "..." }

Designed to be called from a MacBook client (e.g. a presentation overlay app)
over a Tailscale VPN connection -- no public internet exposure needed.

Run:
    source .venv/bin/activate
    uvicorn server:app --host 0.0.0.0 --port 8731

The server binds 0.0.0.0 so it's reachable over the Tailscale interface
(100.118.167.42 on this machine) as well as localhost. It is NOT exposed to
the public internet -- only reachable from devices on your tailnet.
"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live-en-zh-api")

app = FastAPI(title="live-en-zh-api", version="1.0")

# Allow the overlay app (running locally on the MacBook, or over Tailscale)
# to call this from a WebView/Electron context if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Model loading (once, at startup)
# ---------------------------------------------------------------------------

_asr_model = None
_translator = None

PARAKEET_MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v2"


def get_asr_model():
    global _asr_model
    if _asr_model is None:
        log.info("Loading Parakeet-MLX model (%s)...", PARAKEET_MODEL_ID)
        from parakeet_mlx import from_pretrained

        t0 = time.time()
        _asr_model = from_pretrained(PARAKEET_MODEL_ID)
        log.info("Parakeet model loaded in %.1fs", time.time() - t0)
    return _asr_model


def get_translator():
    global _translator
    if _translator is None:
        log.info("Loading Argos Translate en->zh model...")
        import argostranslate.translate as at

        installed = at.get_installed_languages()
        en = next((l for l in installed if l.code == "en"), None)
        zh = next((l for l in installed if l.code == "zh"), None)
        if en is None or zh is None:
            raise RuntimeError(
                "Argos Translate en->zh model not installed. Run setup.sh first."
            )
        _translator = en.get_translation(zh)
        log.info("Translator ready.")
    return _translator


@app.on_event("startup")
def _warm_up() -> None:
    # Load models eagerly at startup so the first real request isn't slow.
    get_asr_model()
    get_translator()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def decode_audio_to_wav_array(raw_bytes: bytes, content_type: str | None) -> np.ndarray:
    """Accepts arbitrary audio bytes (wav, m4a, mp3, caf, etc) and returns
    a mono float32 numpy array at 16kHz, using ffmpeg as the universal decoder.
    """
    with tempfile.NamedTemporaryFile(suffix=".input", delete=True) as src, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as dst:
        src.write(raw_bytes)
        src.flush()

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", src.name,
            "-ar", "16000", "-ac", "1",
            dst.name,
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Could not decode audio (ffmpeg error): {proc.stderr.decode(errors='replace')[:500]}",
            )

        data, sr = sf.read(dst.name, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data


class TranslateResponse(BaseModel):
    en: str
    zh: str
    duration_s: float
    processing_s: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": PARAKEET_MODEL_ID}


@app.post("/translate", response_model=TranslateResponse)
async def translate(audio: UploadFile = File(...)) -> TranslateResponse:
    """
    Send an audio file (any common format: wav, m4a, mp3, caf...) as
    multipart/form-data field 'audio'. Returns the English transcript and
    its Chinese translation.

    Example:
        curl -F "audio=@clip.wav" http://100.118.167.42:8731/translate
    """
    t0 = time.time()
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio upload.")

    samples = decode_audio_to_wav_array(raw, audio.content_type)
    duration_s = len(samples) / 16000.0

    if duration_s < 0.2:
        raise HTTPException(status_code=400, detail="Audio too short (<0.2s).")

    model = get_asr_model()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        sf.write(tmp.name, samples, 16000)
        result = model.transcribe(tmp.name)

    en_text = result.text.strip()
    zh_text = ""
    if en_text:
        translator = get_translator()
        zh_text = translator.translate(en_text)

    processing_s = time.time() - t0
    log.info(
        "translate: %.2fs audio -> %.2fs processing | EN=%r ZH=%r",
        duration_s, processing_s, en_text, zh_text,
    )

    return TranslateResponse(en=en_text, zh=zh_text, duration_s=duration_s, processing_s=processing_s)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8731)
