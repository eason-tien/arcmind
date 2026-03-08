# -*- coding: utf-8 -*-
"""
ArcMind — WebSocket Realtime Voice Channel
=============================================
WebSocket 語音端點：瀏覽器/App 透過 WebSocket 串流語音。

Protocol:
  Client → Server:
    - Binary frames: raw audio bytes (16kHz, 16-bit PCM or Opus)
    - Text frames:   JSON control messages {"action": "start/stop/config"}

  Server → Client:
    - Binary frames: TTS audio bytes (Opus)
    - Text frames:   JSON {"type": "transcript/response/error", ...}

Usage:
    ws://localhost:8100/ws/voice
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("arcmind.channels.voice_ws")

router = APIRouter()

_AUDIO_DIR = Path(tempfile.gettempdir()) / "arcmind_voice"
_AUDIO_DIR.mkdir(exist_ok=True)


class VoiceSession:
    """Manages a single WebSocket voice conversation session."""

    def __init__(self, ws: WebSocket, session_id: str):
        self.ws = ws
        self.session_id = session_id
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.voice_name = "zh-TW-HsiaoChenNeural"
        self._silence_timeout = 1.5  # seconds of silence = end of utterance

    async def send_json(self, data: dict) -> None:
        await self.ws.send_text(json.dumps(data, ensure_ascii=False))

    async def send_audio(self, audio_bytes: bytes) -> None:
        await self.ws.send_bytes(audio_bytes)

    async def handle_audio(self, data: bytes) -> None:
        """Accumulate audio data."""
        self.audio_buffer.extend(data)

    async def process_utterance(self) -> str | None:
        """Process accumulated audio → transcribe → respond → TTS."""
        if not self.audio_buffer:
            return None

        # Save buffer to temp file
        pcm_path = _AUDIO_DIR / f"ws_{self.session_id}_{int(time.time())}.wav"
        try:
            self._write_wav(pcm_path, bytes(self.audio_buffer))
            self.audio_buffer.clear()

            # STT
            from channels.voice import transcribe
            text = transcribe(str(pcm_path))
            if not text:
                await self.send_json({"type": "error", "message": "無法辨識語音"})
                return None

            # Send transcript
            await self.send_json({
                "type": "transcript",
                "text": text,
            })

            # Process through gateway
            from gateway.router import InboundMessage
            from gateway.server import process_message

            msg = InboundMessage(
                channel="websocket",
                user_id=f"ws_{self.session_id}",
                session_id=self.session_id,
                text=text,
                metadata={"source": "voice_ws"},
            )

            response = await process_message(msg)
            response_text = response.text

            # Send text response
            await self.send_json({
                "type": "response",
                "text": response_text,
            })

            # TTS → send audio
            try:
                from channels.voice import text_to_voice
                ogg_path = await text_to_voice(response_text, self.voice_name)
                audio_bytes = ogg_path.read_bytes()
                await self.send_audio(audio_bytes)
                await self.send_json({"type": "audio_end"})
            except Exception as e:
                logger.warning("[VoiceWS] TTS failed: %s", e)
                await self.send_json({"type": "tts_error", "message": str(e)})

            return text

        except Exception as e:
            logger.error("[VoiceWS] Processing error: %s", e)
            await self.send_json({"type": "error", "message": str(e)})
            return None
        finally:
            # Cleanup
            if pcm_path.exists():
                pcm_path.unlink(missing_ok=True)

    def _write_wav(self, path: Path, pcm_data: bytes) -> None:
        """Write PCM data as a WAV file."""
        import struct
        sample_rate = 16000
        bits_per_sample = 16
        channels = 1
        data_size = len(pcm_data)
        header_size = 44

        with open(path, "wb") as f:
            # RIFF header
            f.write(b"RIFF")
            f.write(struct.pack("<I", data_size + header_size - 8))
            f.write(b"WAVE")
            # fmt chunk
            f.write(b"fmt ")
            f.write(struct.pack("<I", 16))  # chunk size
            f.write(struct.pack("<H", 1))   # PCM format
            f.write(struct.pack("<H", channels))
            f.write(struct.pack("<I", sample_rate))
            f.write(struct.pack("<I", sample_rate * channels * bits_per_sample // 8))
            f.write(struct.pack("<H", channels * bits_per_sample // 8))
            f.write(struct.pack("<H", bits_per_sample))
            # data chunk
            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            f.write(pcm_data)


@router.websocket("/ws/voice")
async def voice_websocket(ws: WebSocket):
    """
    WebSocket endpoint for realtime voice conversation.

    Protocol:
    1. Client connects
    2. Client sends {"action": "start"} to begin recording
    3. Client sends binary audio frames (16kHz, 16-bit PCM)
    4. Client sends {"action": "stop"} to end utterance
    5. Server responds with transcript + response text + TTS audio
    6. Repeat from step 2
    """
    await ws.accept()
    session_id = f"voice_{int(time.time())}"
    session = VoiceSession(ws, session_id)

    logger.info("[VoiceWS] Client connected: %s", session_id)
    await session.send_json({
        "type": "connected",
        "session_id": session_id,
        "voice": session.voice_name,
    })

    try:
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Binary = audio data
            if "bytes" in message and message["bytes"]:
                await session.handle_audio(message["bytes"])
                continue

            # Text = control messages
            if "text" in message and message["text"]:
                try:
                    ctrl = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                action = ctrl.get("action", "")

                if action == "start":
                    session.audio_buffer.clear()
                    session.is_recording = True
                    await session.send_json({"type": "recording_started"})

                elif action == "stop":
                    session.is_recording = False
                    await session.send_json({"type": "processing"})
                    await session.process_utterance()

                elif action == "config":
                    if "voice" in ctrl:
                        session.voice_name = ctrl["voice"]
                    await session.send_json({
                        "type": "config_updated",
                        "voice": session.voice_name,
                    })

    except WebSocketDisconnect:
        logger.info("[VoiceWS] Client disconnected: %s", session_id)
    except Exception as e:
        logger.exception("[VoiceWS] Error: %s", e)
    finally:
        logger.info("[VoiceWS] Session ended: %s", session_id)
