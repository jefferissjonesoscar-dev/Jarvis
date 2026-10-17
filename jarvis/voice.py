"""Jarvis's own voice: natural-sounding speech made by Microsoft's free online
voices (through the edge-tts package), so it sounds the same in any browser.

Needs internet. If edge-tts isn't installed or can't connect, the chat screen
falls back to the browser's built-in voices.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("jarvis.voice")

DEFAULT_VOICE = "en-GB-RyanNeural"

# Shown in the chat screen's voice menu, in this order.
VOICES = [
    ("en-GB-RyanNeural", "Ryan (British man)"),
    ("en-GB-ThomasNeural", "Thomas (British man)"),
    ("en-GB-SoniaNeural", "Sonia (British woman)"),
    ("en-GB-LibbyNeural", "Libby (British woman)"),
    ("en-US-AndrewNeural", "Andrew (American man)"),
    ("en-US-GuyNeural", "Guy (American man)"),
    ("en-US-AriaNeural", "Aria (American woman)"),
    ("en-AU-WilliamNeural", "William (Australian man)"),
]
_ALLOWED = {v for v, _ in VOICES}


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Return MP3 audio of `text` spoken in `voice`."""
    import edge_tts

    if voice not in _ALLOWED:
        voice = DEFAULT_VOICE

    async def _run() -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text[:3000], voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    data = asyncio.run(_run())
    if not data:
        raise RuntimeError("the voice service sent back no audio")
    return data
