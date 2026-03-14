# -*- coding: utf-8 -*-
"""
Enhanced Complexity Classifier — 4-way classification (V2 Phase 1)
====================================================================
Extends v0.8.0 3-way classifier to support project-level tasks.
Uses [1]/[2]/[3]/[4] format to avoid false matches in <think> reasoning.

Categories:
  [1] simple — greeting, single command, Q&A
  [2] complex — multi-step single task (no phases needed)
  [3] project — multi-phase initiative (needs project registry)
  [4] progress_query — checking task/project status
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("arcmind.project_classifier")

_NUM_TO_CAT = {
    "1": "simple",
    "2": "complex",
    "3": "project",
    "4": "progress_query",
}


_SIMPLE_PATTERNS = [
    # Greetings / casual chat — CEO handles directly
    "你好", "hello", "hi ", "hey", "嗨", "哈囉",
    "早安", "午安", "晚安", "早上好", "中午好", "下午好", "晚上好",
    "good morning", "good afternoon", "good evening", "good night",
    "谢谢", "thanks", "thank you", "bye", "再见", "ok", "好的", "收到",
    "是什么", "什么是", "who is", "what is", "how are",
    "帮助", "help", "你是谁", "介绍",
]


def _heuristic_complexity(command: str) -> str | None:
    """
    Rule-based fallback when LLM parse fails.
    Returns complexity or None (let LLM decide).

    V3: Aggressively route work to PM. CEO should only handle
    greetings, Q&A, and truly trivial single-action requests.
    """
    cmd = command.lower().strip()
    cmd_len = len(cmd)

    # ── Explicit simple: greetings, acknowledgements, Q&A ──
    if cmd_len < 10:
        return "simple"
    if any(p in cmd for p in _SIMPLE_PATTERNS):
        if cmd_len < 30:  # Short greeting/ack = simple
            return "simple"

    # Multi-step signal words → at least complex
    complex_signals = [
        "然后", "接着", "之后", "并且", "同时", "最后",
        "第一步", "第二步", "步骤", "先…再", "分析.*然后",
        "setup", "deploy", "install", "configure", "build",
        "create.*and", "implement", "设计", "开发", "搭建",
        "升级", "重构", "迁移", "部署", "安装并配置",
        "修复", "优化", "调试", "测试",  # V3: added action-oriented words
        "fix", "debug", "optimize", "refactor",
    ]
    complex_count = sum(1 for s in complex_signals if s in cmd)

    # Project signal words → project
    project_signals = [
        "系统", "平台", "项目", "架构", "方案", "全面",
        "完整的", "从零", "包含.*和.*和", "监控.*告警.*仪表板",
        "project", "system", "platform", "infrastructure",
        "phase", "milestone", "阶段", "里程碑",
    ]
    project_count = sum(1 for s in project_signals if s in cmd)

    # Action verbs — any work beyond Q&A
    action_verbs = re.findall(
        r'(?:写|改|查|建|装|跑|测|扫|审|分析|生成|创建|实现|修改|检查|运行|执行|搜索|'
        r'修复|优化|调试|部署|安装|配置|编写|实作|撰写|开发|设计|'
        r'write|fix|create|run|test|scan|audit|analyze|generate|implement|modify|check|'
        r'deploy|install|configure|build|debug|optimize|refactor|develop|setup)',
        cmd
    )

    # ── Decision logic (V3: lowered thresholds — PM does the work) ──

    # P1-3: 排除純問句（以問號或問句詞結尾，且無複合動作）
    _is_question_only = (
        (cmd.rstrip().endswith(('？', '?')) or
         re.search(r'(什么|如何|怎么|嗎|吗|哪个|what|how|which|why|is )$', cmd.rstrip().rstrip('？?'), re.I))
        and complex_count == 0
        and project_count == 0
        and len(action_verbs) <= 1
    )
    if _is_question_only:
        return None  # 交給 LLM 判斷（通常是 simple）

    if project_count >= 2 or (complex_count >= 1 and project_count >= 1):
        return "project"
    if complex_count >= 2 or len(action_verbs) >= 2 or cmd_len > 80:
        return "complex"
    # V3: Single signal word OR single action verb = complex (PM handles)
    if complex_count >= 1 or len(action_verbs) >= 1:
        return "complex"

    return None  # Not confident — let LLM decide


def classify_complexity(command: str, session_id: int = None,
                        model: str = None) -> str:
    """Classify task complexity. Returns: simple | complex | project | progress_query"""

    # Quick path: progress keywords (short text only)
    try:
        cmd_lower = command.lower().strip()
        # ROOT-1: 排除對話續接意圖（这些不是進度查詢）
        _conversation_intents = [
            "继续", "讨论", "下一步", "接下来", "然后呢", "怎么做",
            "做什么", "该怎么", "建议", "推荐", "帮我", "请",
            "continue", "next", "what should", "let's", "discuss",
        ]
        _is_conversation = any(w in cmd_lower for w in _conversation_intents)

        progress_words = [
            "进度", "完成了吗", "到哪了", "多久了", "status", "progress",
            "做到哪", "好了吗", "做完了", "搞定了", "项目进度", "项目状态",
            "任务状态", "执行状态",
        ]
        if (len(cmd_lower) < 20
                and any(w in cmd_lower for w in progress_words)
                and not _is_conversation):
            _audit_classify(command, "progress_query", "quick_path")
            return "progress_query"
    except Exception:
        pass

    # LLM classification
    llm_result = None
    try:
        from runtime.model_router import model_router

        resp = model_router.complete(
            prompt=(
                f"Request: {command}\n\n"
                "Which category?\n"
                "[1] Simple — single-turn: greeting, Q&A, one command, "
                "read/check something, answer a question, "
                "knowledge inquiry (“什么是XX” “XX是什么” “how does X work”)\n"
                "[2] Complex — needs 2+ steps or tools: write code + test, "
                "search + summarize, fix bug + verify, analyze + report, "
                "any task requiring planning or multiple actions\n"
                "[3] Project — multi-phase initiative: build system, "
                "create application, setup infra, anything with "
                "multiple deliverables or milestones\n"
                "[4] Progress inquiry — ONLY when explicitly asking about "
                "status/progress of existing tasks (e.g. '进度怎样' '完成了吗' "
                "'status?'). NOT for continuing discussion or asking what to do next.\n\n"
                "KEY DISTINCTIONS:\n"
                "- '什么是MCP' '解釋A2A协议' 'how does X work' → [1] (knowledge Q&A)\n"
                "- '研究并分析X' '寫一個報告' '分析+審計' → [2] (multi-step task)\n"
                "- '继续讨论' '下一步做什么' '接下来怎么做' → [1] (conversation, NOT [4])\n\n"
                "Answer: [number]"
            ),
            system="Reply ONLY with [1], [2], [3], or [4]. Nothing else.",
            model=model,
            max_tokens=300,
            task_type="classify",
            budget="low",
        )

        raw = resp.content.strip()

        # Strategy 1: Find bracketed numbers [1]-[4]
        brackets = re.findall(r'\[([1-9])\]', raw)
        if brackets:
            digit = brackets[-1]  # Last bracketed number = final answer
            llm_result = _NUM_TO_CAT.get(digit)

        # Strategy 2: Find last standalone digit on its own line
        if not llm_result:
            for line in reversed(raw.strip().split("\n")):
                clean = line.strip().rstrip(".")
                r = _NUM_TO_CAT.get(clean)
                if r:
                    llm_result = r
                    break

        # Strategy 3: Check for English category words after </think>
        if not llm_result:
            after = re.sub(r'<think>[\s\S]*?</think>\s*', '', raw).strip().lower()
            if after:
                for word, cat in [("project", "project"), ("complex", "complex"),
                                  ("progress", "progress_query"), ("simple", "simple")]:
                    if word in after:
                        llm_result = cat
                        break

    except Exception as e:
        logger.warning("[ProjectClassifier] LLM failed: %s", e)

    # Heuristic fallback (only used when LLM fails)
    heuristic = _heuristic_complexity(command)

    # Final decision: trust LLM as primary intelligence
    if llm_result:
        # P1-3: 當 heuristic=complex 但 LLM=simple 時，若命令含動作動詞則信任 heuristic
        if llm_result == "simple" and heuristic == "complex":
            action_check = re.findall(
                r'(?:写|改|查|建|装|跑|测|扫|審|分析|生成|创建|实现|修改|检查|运行|执行|搜索|'
                r'修复|优化|调试|部署|安装|配置|编写|实作|撰写|开发|设计|'
                r'write|fix|create|run|test|scan|audit|analyze|generate|implement|modify|'
                r'deploy|install|configure|build|debug|optimize|refactor|develop|setup)',
                command.lower()
            )
            if action_check:
                final = "complex"
                _audit_classify(command, final, f"heuristic_override(llm=simple)")
                return final
        final = llm_result
        _audit_classify(command, final, f"llm(heur={heuristic})")
    elif heuristic:
        final = heuristic
        _audit_classify(command, final, "heuristic_fallback")
    else:
        # Both failed — default to simple, let CEO handle and decide
        final = "simple"
        _audit_classify(command, final, "default_simple")

    return final


def _audit_classify(command: str, result: str, method: str) -> None:
    """Log classification decision for observability."""
    logger.info("[ProjectClassifier] '%s' → %s [%s]", command[:60], result, method)
    try:
        from runtime.audit_events import audit_events
        audit_events.record(
            event_type="complexity_classification",
            source="project_classifier",
            summary=f"{result} ({method}): {command[:100]}",
            severity="info",
            details={"command": command[:300], "result": result, "method": method},
        )
    except Exception:
        pass
