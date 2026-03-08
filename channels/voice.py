# -*- coding: utf-8 -*-
"""
ArcMind — Voice Processing Module
====================================
語音處理：STT (Whisper) + TTS (edge-tts)

STT: OpenAI Whisper API（透過 Codex token 或 API key）
TTS: edge-tts（免費微軟 TTS，無需 API key）
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("arcmind.channels.voice")

# ── Config ──────────────────────────────────────────────────────────────────

# TTS voice — 繁體中文女聲
DEFAULT_VOICE = os.getenv("TTS_VOICE", "zh-TW-HsiaoChenNeural")
# STT model
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
# Temp directory for audio files
_AUDIO_DIR = Path(tempfile.gettempdir()) / "arcmind_voice"
_AUDIO_DIR.mkdir(exist_ok=True)


# ── STT: Whisper ────────────────────────────────────────────────────────────

def _get_openai_client():
    """Get OpenAI client (via API key or Codex token)."""
    import openai

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        # Try Codex token
        try:
            from runtime.model_router import _read_codex_token
            api_key = _read_codex_token()
        except Exception:
            pass

    if not api_key:
        raise RuntimeError("No OpenAI API key or Codex token available for Whisper")

    return openai.OpenAI(api_key=api_key)


def convert_ogg_to_wav(ogg_path: str | Path) -> Path:
    """Convert .ogg to .wav using ffmpeg."""
    wav_path = _AUDIO_DIR / f"{Path(ogg_path).stem}.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(ogg_path), "-ar", "16000",
             "-ac", "1", "-f", "wav", str(wav_path)],
            capture_output=True, check=True, timeout=30,
        )
        return wav_path
    except subprocess.CalledProcessError as e:
        logger.error("[Voice] ffmpeg conversion failed: %s", e.stderr.decode()[:200])
        raise


def transcribe(audio_path: str | Path) -> str:
    """
    Transcribe audio file to text using OpenAI Whisper API.
    Supports: .ogg, .wav, .mp3, .m4a, .webm
    """
    path = Path(audio_path)

    # Convert .ogg to .wav if needed (Whisper API accepts .ogg but wav is more reliable)
    if path.suffix in (".ogg", ".oga"):
        path = convert_ogg_to_wav(path)

    try:
        client = _get_openai_client()
        with open(path, "rb") as f:
            result = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=f,
                language="zh",  # Hint: Chinese
            )
        text = result.text.strip()
        logger.info("[Voice] STT: '%s' (%d chars)", text[:60], len(text))
        return text

    except Exception as e:
        logger.error("[Voice] Whisper transcription failed: %s", e)
        raise


# ── TTS: edge-tts ───────────────────────────────────────────────────────────

async def synthesize_async(text: str, voice: str = "") -> Path:
    """
    Synthesize text to speech using edge-tts.
    Returns path to generated .mp3 file.
    """
    import edge_tts

    voice = voice or DEFAULT_VOICE
    output_path = _AUDIO_DIR / f"tts_{hash(text) & 0xFFFFFFFF:08x}.mp3"

    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
        logger.info("[Voice] TTS: %d chars → %s (%d bytes)",
                    len(text), voice, output_path.stat().st_size)
        return output_path

    except Exception as e:
        logger.error("[Voice] TTS synthesis failed: %s", e)
        raise


def synthesize(text: str, voice: str = "") -> Path:
    """Sync wrapper for synthesize_async."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # We're inside an async context, create a new loop in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, synthesize_async(text, voice))
            return future.result(timeout=30)
    else:
        return asyncio.run(synthesize_async(text, voice))


def convert_mp3_to_ogg(mp3_path: str | Path) -> Path:
    """Convert .mp3 to .ogg (opus) for Telegram voice messages."""
    ogg_path = _AUDIO_DIR / f"{Path(mp3_path).stem}.ogg"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_path),
             "-c:a", "libopus", "-b:a", "64k", str(ogg_path)],
            capture_output=True, check=True, timeout=30,
        )
        return ogg_path
    except subprocess.CalledProcessError as e:
        logger.error("[Voice] mp3→ogg conversion failed: %s", e.stderr.decode()[:200])
        raise


# ── Combined: Voice-to-Voice ────────────────────────────────────────────────

async def voice_to_text(ogg_path: str | Path) -> str:
    """Full pipeline: voice file → transcribed text."""
    return transcribe(ogg_path)


async def text_to_voice(text: str, voice: str = "") -> Path:
    """Full pipeline: text → voice .ogg file (Telegram compatible)."""
    # Truncate very long text for TTS
    if len(text) > 2000:
        text = text[:2000] + "... 以下內容過長，已省略。"

    # Strip markdown formatting for cleaner TTS
    import re
    clean = re.sub(r'\*\*|__|~~|`{1,3}', '', text)  # bold/italic/strikethrough/code
    clean = re.sub(r'^#{1,6}\s+', '', clean, flags=re.MULTILINE)  # headers
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)  # links
    clean = re.sub(r'^[-*]\s+', '', clean, flags=re.MULTILINE)  # bullet points
    clean = clean.strip()

    if not clean:
        clean = "處理完成。"

    mp3_path = await synthesize_async(clean, voice)
    ogg_path = convert_mp3_to_ogg(mp3_path)
    return ogg_path
