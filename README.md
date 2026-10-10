# live-en-zh-api

A local REST API that transcribes English speech and translates it to Chinese —
fully offline, running on Apple Silicon Metal GPU. Built to sit on your Mac Mini
(`clawns-mac-mini`, Tailscale IP `100.118.167.42`) and be called from your
MacBook over Tailscale during a live presentation.

**Pipeline**: audio (any format) → [Parakeet-MLX](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2)
(English ASR, Metal GPU) → [Argos Translate](https://github.com/argosopentech/argos-translate)
(English → Chinese, offline NMT) → JSON `{ "en": ..., "zh": ... }`.

Verified working end-to-end on this machine: ~6s of English speech processed
in 0.2–1.5s (model warmed up), both over `localhost` and over the Tailscale
IP.

## Setup (on the Mac Mini / server side)

```bash
git clone https://github.com/mekwins/live-en-zh-api.git
cd live-en-zh-api
./setup.sh
```

Run once to test:
```bash
source .venv/bin/activate
python server.py
```

Run persistently (survives reboot/logout, auto-restarts on crash):
```bash
./install_launchd.sh
```

Server listens on `0.0.0.0:8731` — reachable at:
- `http://127.0.0.1:8731` locally
- `http://100.118.167.42:8731` over your Tailscale tailnet (from any device on
  your tailnet, e.g. your MacBook, iPhone)

It is **not** exposed to the public internet — only devices joined to your
Tailscale network can reach it.

## API

### `GET /health`
```json
{"status": "ok", "model": "mlx-community/parakeet-tdt-0.6b-v2"}
```

### `POST /translate`
Multipart form upload, field name `audio`. Accepts any ffmpeg-readable audio
format (wav, m4a, mp3, caf, aiff...).

```bash
curl -F "audio=@clip.wav" http://100.118.167.42:8731/translate
```

Response:
```json
{
  "en": "We open safe access to the best AI models for about 500 engineers through our own gateway with our own security.",
  "zh": "我们通过我们自己的网关,为大约500名工程师安全地开放最佳AI模型.",
  "duration_s": 5.99,
  "processing_s": 0.21
}
```

## Recommended client-side chunking strategy

For a *live* presentation, don't stream raw audio continuously — chunk it:

1. Record ~3–6 second rolling audio segments on the MacBook (e.g. on a pause
   in speech, or on a fixed timer).
2. POST each segment to `/translate` as soon as it's captured.
3. Display the returned `zh` text, replacing/appending to the overlay.
4. Overlap segments slightly (e.g. last 0.5s of previous chunk) if you want to
   avoid clipping words at chunk boundaries — the server doesn't do
   cross-chunk merging, each request is independent.

This keeps latency low (sub-second processing time per chunk, once the model
is warm) while avoiding the complexity of a persistent streaming/WebSocket
connection. A WebSocket-based streaming variant is a natural v2 if the
chunked version proves too choppy in practice — not built here since it needs
your emulation/feedback on acceptable latency first.

## Known limitations

- Each chunk is translated independently — no cross-chunk context, so
  pronoun/reference resolution across sentence boundaries can suffer.
- Argos Translate quality is solid for plain spoken English but not
  LLM-grade; technical jargon or names may come through awkwardly.
- No authentication on the API — acceptable because it's Tailscale-only
  (not internet-exposed), but don't put this on a public IP as-is.
- `parakeet-tdt-0.6b-v2` is English-only (the model your `parakeet-mlx` CLI
  already uses) — this is intentional since your presentation is in English.

---

# Companion macOS overlay app — SPEC (not yet built)

You asked for a spec for a MacBook app that displays this translation as an
on-screen overlay during your presentation. Here it is; building a working
polished native app is a multi-day endeavor (mic capture, floating
window chrome, packaging/signing) so it's specified here rather than
one-shot-built blind — flag if you want it built next and I'll start on it.

## Goal

A small always-on-top, click-through overlay window on the MacBook that:
1. Captures microphone audio continuously while presenting.
2. Sends rolling ~4s chunks to `http://100.118.167.42:8731/translate` over Tailscale.
3. Displays the returned Chinese text in a large, readable font, floating
   over whatever else is on screen (e.g. your slides / Zoom / Keynote).

## Recommended architecture

**Platform**: native macOS app (SwiftUI) — lowest latency mic access, best
support for a borderless always-on-top transparent window, easiest
packaging as a single `.app` you launch by double-click.

(Alternative considered: Electron overlay — rejected because mic capture +
true click-through transparent overlay is more fragile and heavier than
needed for this use case.)

### Components

1. **`OverlayWindow`** (SwiftUI + `NSWindow` subclass)
   - `NSWindow.Level = .floating` (or `.screenSaver` for "always on top of
     everything including fullscreen apps")
   - `ignoresMouseEvents = true` so it doesn't block clicks on your slides
   - Transparent/semi-transparent background, large white/yellow text with a
     black outline or drop shadow for readability over any background
     (like video subtitle styling)
   - Positioned at bottom-center or top-center of the main screen, like a
     subtitle bar
   - Option to pick which screen (if presenting on an external display via
     the MacBook)

2. **`MicCapture`** (`AVAudioEngine`)
   - Tap the input node, buffer into ~4s rolling windows (configurable)
   - Simple energy-based or `AVAudioEngine` voice-activity gate: flush early
     on a pause >600ms, else force-flush at max window length, to keep
     latency low and avoid cutting mid-sentence as much as possible
     (same strategy as the `live_translate.py` CLI tool already built for
     the Chinese→English direction — mirror its `Segmenter` logic)
   - Encode each segment to WAV (16kHz mono) in memory

3. **`TranslationClient`**
   - `URLSession` multipart POST to `http://100.118.167.42:8731/translate`
   - Server URL configurable in a simple settings panel (in case the
     Tailscale IP changes, or you want to point at a different machine)
   - On response, push `zh` text to the overlay view via a published
     `@Published var currentText: String`
   - Timeout + retry: if a request takes >3s or fails (e.g. Tailscale
     blip), skip it and keep listening rather than blocking the pipeline
   - Health-check `/health` on launch; show a red/green status dot in a
     small menu-bar icon so you can see at a glance if the connection to
     the Mac Mini is alive

4. **Menu bar item** (`NSStatusItem`)
   - Start/Stop listening toggle
   - Connection status indicator (green = server reachable, red = not)
   - "Show/Hide overlay" toggle
   - Quit

### Data flow

```
Mic → AVAudioEngine tap → 4s rolling buffer (VAD-gated flush)
    → WAV encode → POST /translate (Tailscale) → { en, zh }
    → currentText updated → OverlayWindow text updates
```

### Packaging

- Standard Xcode project, `.app` bundle
- No App Store distribution needed — ad-hoc build + local-only launch is
  fine (you already have Apple Developer tooling via Xcode)
- Needs microphone usage description (`NSMicrophoneUsageDescription`) in
  Info.plist, and the user grants mic permission once on first launch

### Why this isn't built yet

A real native app needs an Xcode project, a provisioning/signing setup
specific to your Apple ID, and iteration on overlay look/feel and VAD tuning
that's much faster to do interactively on the actual MacBook than blind from
here. The server side (this repo) is fully built, tested, and ready to call
today via plain `curl` or any HTTP client (e.g. a Shortcuts automation, or a
quick Python/AppleScript script) as a stopgap while the native app gets
built.

**Fastest stopgap** (no app needed): a 20-line Python script using
`sounddevice` to record segments and call the API, printing the Chinese text
to the terminal — essentially the `live_translate.py` tool already built for
the other direction, pointed at this API instead of running the model
in-process. Ask if you want this as an immediate bridge while the native
overlay app is built.
