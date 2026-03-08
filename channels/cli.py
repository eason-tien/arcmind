# -*- coding: utf-8 -*-
"""
ArcMind Channels — CLI Channel
================================
本地終端互動模式，直連 Gateway。
用於開發測試和本地管理。

使用方式：
  python -m channels.cli
"""
from __future__ import annotations

import asyncio
import logging
import sys

from channels.base import Channel
from gateway.router import InboundMessage, OutboundMessage
from gateway.server import process_message

logger = logging.getLogger("arcmind.channels.cli")


class CLIChannel(Channel):
    """Interactive CLI channel for local development/management."""

    def __init__(self, user_id: str = "cli"):
        super().__init__(name="CLI", enabled=True)
        self.user_id = user_id
        self.session_id = f"cli_{user_id}"

    async def start(self) -> None:
        """Start interactive CLI loop."""
        self._running = True
        logger.info("[CLI] ArcMind CLI started. Type 'exit' to quit.")

        print("\n" + "=" * 50)
        print("  🧠 ArcMind CLI v0.3.0")
        print("  Type /help for commands, 'exit' to quit")
        print("=" * 50 + "\n")

        try:
            while self._running:
                try:
                    # Read input (run in executor to avoid blocking)
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("You > ")
                    )
                except EOFError:
                    break

                text = user_input.strip()
                if not text:
                    continue
                if text.lower() in ("exit", "quit", "q"):
                    print("👋 再見！")
                    break

                # Create InboundMessage
                msg = InboundMessage.from_cli(text, user_id=self.user_id)

                # Process through Gateway pipeline
                try:
                    response = await process_message(msg)
                    print(f"\n🧠 > {response.text}\n")
                except Exception as e:
                    print(f"\n⚠️ Error: {e}\n")

        except KeyboardInterrupt:
            print("\n👋 再見！")
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the CLI channel."""
        self._running = False

    async def send(self, message: OutboundMessage) -> bool:
        """Print response to terminal."""
        print(f"\n🧠 > {message.text}\n")
        return True


# ── Standalone runner ────────────────────────────────────────────────────────

async def run_cli():
    """Run CLI channel standalone."""
    # Initialize DB
    from db.schema import init_db
    init_db()

    cli = CLIChannel()
    await cli.start()


if __name__ == "__main__":
    asyncio.run(run_cli())
