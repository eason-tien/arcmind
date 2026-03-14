# -*- coding: utf-8 -*-
"""
Complexity Classifier — LLM-based with bracketed number categories.
Uses [1]/[2]/[3] format to avoid false matches in <think> reasoning.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("arcmind.complexity")

_NUM_TO_CAT = {"1": "simple", "2": "complex", "3": "progress_query"}


def classify_complexity(command: str, session_id: int = None,
                        model: str = None) -> str:
    """Classify task complexity. Returns: simple | complex | progress_query"""

    # Quick path: progress keywords
    try:
        cmd_lower = command.lower().strip()
        progress_words = [
            "进度", "怎么样", "完成", "到哪", "多久", "status", "progress",
            "几步", "做到哪", "好了吗", "做完", "搞定"
        ]
        if len(cmd_lower) < 20 and any(w in cmd_lower for w in progress_words):
            logger.info("[Complexity] Quick path: progress_query")
            return "progress_query"
    except Exception:
        pass

    # LLM classification
    try:
        from runtime.model_router import model_router

        resp = model_router.complete(
            prompt=(
                f"Request: {command}\n\n"
                "Which category?\n"
                "[1] Simple task (greeting, single command, Q&A, read file)\n"
                "[2] Complex task (multi-step: deploy app, setup environment, "
                "install and configure services, build project)\n"
                "[3] Progress inquiry\n\n"
                "Answer format: [number]"
            ),
            system="Reply ONLY with [1], [2], or [3]. Nothing else.",
            model=model,
            max_tokens=300,
            task_type="classify",
            budget="low",
        )

        raw = resp.content.strip()

        # Strategy 1: Find bracketed numbers [1], [2], [3]
        brackets = re.findall(r'\[([1-9])\]', raw)
        if brackets:
            digit = brackets[-1]  # Last bracketed number = final answer
            result = _NUM_TO_CAT.get(digit)
            if result:
                logger.info("[Complexity] %s → %s", command[:40], result)
                return result
            logger.warning("[Complexity] unexpected digit [%s], ignoring", digit)

        # Strategy 2: Find last standalone digit on its own line
        for line in reversed(raw.strip().split("\n")):
            clean = line.strip().rstrip(".")
            result = _NUM_TO_CAT.get(clean)
            if result:
                logger.info("[Complexity] %s → %s (line)", command[:40], result)
                return result

        # Strategy 3: Check for English category words after </think>
        after = re.sub(r'<think>[\s\S]*?</think>\s*', '', raw).strip().lower()
        if after:
            if "complex" in after:
                logger.info("[Complexity] %s → complex (word)", command[:40])
                return "complex"
            if "simple" in after:
                logger.info("[Complexity] %s → simple (word)", command[:40])
                return "simple"

        logger.warning("[Complexity] unexpected: '%s', default=simple", raw[:100])
        return "simple"
    except Exception as e:
        logger.warning("[Complexity] failed: %s, default=simple", e)
        return "simple"
