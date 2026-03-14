# -*- coding: utf-8 -*-
"""
ArcMind Channels — Base Channel Abstraction
=============================================
所有通道的抽象基類。每個 Channel 負責：
1. 接收外部消息 → 轉為 InboundMessage
2. 接收 OutboundMessage → 送回外部平台

Channel 不直接處理消息邏輯——所有消息通過 Gateway 統一管道。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from gateway.router import InboundMessage, OutboundMessage

logger = logging.getLogger("arcmind.channels")


class Channel(ABC):
    """
    Abstract base class for all communication channels.

    Lifecycle:
      1. __init__()   — configure
      2. start()      — connect/listen
      3. send()       — deliver responses
      4. stop()       — disconnect/cleanup
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (connect, begin polling/listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel gracefully."""
        ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> bool:
        """
        Deliver a response message to the external platform.
        Returns True if delivery succeeded.
        """
        ...

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "running": self._running,
        }
