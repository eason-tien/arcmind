# -*- coding: utf-8 -*-
"""
ArcMind — Capability Selector (P1-1)
======================================
語義優先的能力選擇器，替代關鍵字驅動的 _CAPABILITY_KEYWORDS。

職責：
  1. 管理工具和 Agent 能力的 embedding 索引
  2. 根據用戶意圖做語義匹配，返回 top-K 候選
  3. 可選：用本地 LLM (qwen3:4b/8b) 做 rerank

架構：
  User Intent → nomic-embed-text → cosine similarity → top-K candidates

索引來源：
  - 工具描述（from ToolRegistry）
  - Agent 能力描述（from AgentRegistry）
  - 自定義能力描述（手動 + 自動）
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("arcmind.capability_selector")

# ── 資料結構 ────────────────────────────────────────────────────────────────

@dataclass
class CapabilityEntry:
    """一個能力候選項的索引條目。"""
    id: str                             # 唯一 ID，如 "tool:web_search" 或 "agent:code"
    kind: str                           # "tool" | "agent" | "skill"
    name: str                           # 顯示名稱
    description: str                    # 語義描述（用於 embedding）
    embedding: list[float] = field(default_factory=list, repr=False)
    metadata: dict = field(default_factory=dict)


@dataclass
class SelectionResult:
    """Capability Selector 的返回結果。"""
    entry: CapabilityEntry
    score: float                        # cosine similarity score
    rank: int = 0


# ── Capability Selector ────────────────────────────────────────────────────

class CapabilitySelector:
    """
    語義優先的能力選擇器。
    用 nomic-embed-text 做 embedding，cosine similarity 做匹配。
    """

    def __init__(self):
        self._index: list[CapabilityEntry] = []
        self._lock = threading.Lock()
        self._initialized = False
        self._last_refresh = 0.0
        self._refresh_interval = 1800.0  # 30 分鐘重新索引（工具列表變動頻率極低）

    # ── 索引建構 ──────────────────────────────────────────────────────────

    def _ensure_initialized(self):
        """延遲初始化：首次查詢時建構索引。"""
        now = time.monotonic()
        if self._initialized and (now - self._last_refresh) < self._refresh_interval:
            return
        with self._lock:
            if self._initialized and (now - self._last_refresh) < self._refresh_interval:
                return
            self._build_index()
            self._initialized = True
            self._last_refresh = now

    # ── 雙語描述增強（nomic-embed-text 主要是英文模型）──────────────────
    _TOOL_BILINGUAL: dict[str, str] = {
        "web_search": "搜尋 搜索 search 查找 新聞 news 最新 latest 網路查詢 google",
        "run_command": "執行命令 shell terminal 終端 命令列 bash command 系統操作",
        "read_file": "讀檔案 read file 查看 view 檔案內容 文件",
        "write_file": "寫檔案 write file 建立檔案 create 寫入 儲存",
        "python_eval": "Python 執行 程式碼 code eval 計算 script 腳本",
        "memory_query": "記憶 memory 回憶 recall 查詢歷史 knowledge",
        "delegate_task": "委派 delegate 分配任務 assign task 交辦",
        "plan_task": "規劃 plan 計畫 策略 分解任務 breakdown",
        "execute_plan": "執行計畫 execute plan 開始工作 run plan pipeline",
        "list_agents": "列出 agents 員工 team 團隊 roster",
        "add_agent": "新增 agent 聘僱 hire 加入團隊 recruit",
        "remove_agent": "移除 agent 解僱 fire 刪除 remove",
        "agent_handoff": "交接 handoff transfer 轉交 移交",
        "send_webhook": "通知 webhook notify 外部通知 alert",
        "read_url_content": "讀取網頁 read URL 爬取 scrape 網頁內容 webpage",
        "harness_create": "自動化 automation harness 執行流程 workflow",
    }

    _CAP_BILINGUAL: dict[str, str] = {
        "coding": "寫程式 code 程式碼 編程 Python JavaScript 實作 implement function class",
        "debugging": "除錯 debug fix bug error 修復 修正 traceback exception",
        "code_review": "審查 review 優化 refactor 重構 改善程式碼",
        "web_search": "搜尋 search 搜索 查找 google news 新聞 最新",
        "research": "研究 research 調研 了解 什麼是 探索 分析",
        "analysis": "分析 analyze data 數據 統計 報告 report",
        "testing": "測試 test QA 驗證 verify unit test 回歸",
        "deployment": "部署 deploy CI/CD docker kubernetes 發布",
        "monitoring": "監控 monitor alert 告警 日誌 log",
        "security": "安全 security 漏洞 vulnerability 滲透 audit",
        "frontend": "前端 frontend React Vue CSS HTML UI 組件 頁面",
        "design": "設計 design UX 原型 prototype wireframe",
        "verification": "驗證 verify check confirm 確認 檢查",
    }

    def _build_index(self):
        """建構完整的能力 embedding 索引（含雙語增強）。"""
        entries: list[CapabilityEntry] = []

        # 1. 從 ToolRegistry 收集工具描述（加入雙語增強）
        try:
            from runtime.tool_loop import tool_registry
            for schema in tool_registry.get_schemas():
                name = schema["name"]
                desc = schema.get("description", name)
                # 加入雙語關鍵字增強
                bilingual = self._TOOL_BILINGUAL.get(name, "")
                full_desc = f"Tool: {name} — {desc}"
                if bilingual:
                    full_desc += f" | {bilingual}"
                entries.append(CapabilityEntry(
                    id=f"tool:{name}",
                    kind="tool",
                    name=name,
                    description=full_desc,
                    metadata={"tool_name": name},
                ))
        except Exception as e:
            logger.warning("[CapSel] Failed to load tool schemas: %s", e)

        # 2. 從 AgentRegistry 收集 Agent 能力（加入雙語增強）
        try:
            from runtime.agent_registry import agent_registry
            for agent in agent_registry.list_enabled():
                if agent.id == "main":
                    continue  # CEO 不參與委派匹配
                # 每個 agent 的每個 capability 建一個條目
                for cap in agent.capabilities:
                    bilingual = self._CAP_BILINGUAL.get(cap, "")
                    cap_desc = f"Agent: {agent.name} — {agent.description}. Capability: {cap}"
                    if bilingual:
                        cap_desc += f" | {bilingual}"
                    entries.append(CapabilityEntry(
                        id=f"agent:{agent.id}:{cap}",
                        kind="agent",
                        name=f"{agent.name} ({cap})",
                        description=cap_desc,
                        metadata={
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "capability": cap,
                            "model": agent.default_model,
                        },
                    ))
                # 也為整個 agent 建一個整合條目
                cap_str = ", ".join(agent.capabilities) if agent.capabilities else "general"
                entries.append(CapabilityEntry(
                    id=f"agent:{agent.id}",
                    kind="agent",
                    name=agent.name,
                    description=f"Agent: {agent.name} — {agent.description}. Specializes in: {cap_str}",
                    metadata={
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "capability": cap_str,
                        "model": agent.default_model,
                    },
                ))
        except Exception as e:
            logger.warning("[CapSel] Failed to load agent registry: %s", e)

        # 3. 從 SkillManager 收集已註冊技能
        try:
            from runtime.skill_manager import skill_manager
            for skill_name in skill_manager.list_skills():
                info = skill_manager.get_info(skill_name)
                desc = info.get("description", skill_name) if info else skill_name
                entries.append(CapabilityEntry(
                    id=f"skill:{skill_name}",
                    kind="skill",
                    name=skill_name,
                    description=f"Skill: {skill_name} — {desc}",
                    metadata={"skill_name": skill_name},
                ))
        except Exception as e:
            logger.debug("[CapSel] Failed to load skills: %s", e)

        if not entries:
            logger.warning("[CapSel] No entries to index!")
            self._index = []
            return

        # 4. 批量 embedding
        try:
            from memory.embedding import get_adapter
            adapter = get_adapter()
            texts = [e.description for e in entries]
            embeddings = adapter.embed(texts)
            for entry, emb in zip(entries, embeddings):
                entry.embedding = emb
            # 過濾掉 embedding 失敗的條目
            entries = [e for e in entries if e.embedding]
            logger.info("[CapSel] Indexed %d entries (%d tools + agents + skills)",
                        len(entries), sum(1 for e in entries if e.kind == "tool"))
        except Exception as e:
            logger.warning("[CapSel] Embedding failed, index will be empty: %s", e)
            entries = []

        self._index = entries

    def refresh(self):
        """強制重新建構索引。"""
        with self._lock:
            self._build_index()
            self._last_refresh = time.monotonic()

    # ── 語義查詢 ──────────────────────────────────────────────────────────

    def select_tools(self, intent: str, top_k: int = 5,
                     min_score: float = 0.15) -> list[SelectionResult]:
        """
        根據用戶意圖，語義匹配 top-K 工具。
        返回按相關性排序的 SelectionResult 列表。
        """
        self._ensure_initialized()
        return self._query(intent, kind_filter="tool", top_k=top_k, min_score=min_score)

    def select_agents(self, intent: str, top_k: int = 3,
                      min_score: float = 0.20) -> list[SelectionResult]:
        """
        根據用戶意圖，語義匹配最佳 Agent。
        返回按相關性排序的 SelectionResult 列表。
        """
        self._ensure_initialized()
        return self._query(intent, kind_filter="agent", top_k=top_k, min_score=min_score)

    def select_all(self, intent: str, top_k: int = 10,
                   min_score: float = 0.15) -> list[SelectionResult]:
        """
        不分類型，語義匹配所有能力。
        """
        self._ensure_initialized()
        return self._query(intent, kind_filter=None, top_k=top_k, min_score=min_score)

    def _query(self, intent: str, kind_filter: str | None = None,
               top_k: int = 5, min_score: float = 0.15) -> list[SelectionResult]:
        """
        核心混合查詢：embedding + 關鍵字雙軌並行。
        nomic-embed-text 英文精度高但中文弱，所以對中文查詢需要關鍵字補強。
        """
        if not self._index:
            return []

        # ── 1. Embedding 查詢（使用 embed_one 走快取，避免重複 embed 同一意圖）──
        embed_results: dict[str, SelectionResult] = {}  # id → result
        try:
            from memory.embedding import get_adapter, cosine_similarity
            adapter = get_adapter()
            intent_vec = adapter.embed_one(intent) if hasattr(adapter, 'embed_one') else (adapter.embed([intent]) or [[]])[0]
            if intent_vec:
                for entry in self._index:
                    if kind_filter and entry.kind != kind_filter:
                        continue
                    if not entry.embedding:
                        continue
                    score = cosine_similarity(intent_vec, entry.embedding)
                    if score >= min_score:
                        embed_results[entry.id] = SelectionResult(entry=entry, score=score)
        except Exception as e:
            logger.debug("[CapSel] Embedding query failed: %s", e)

        # ── 2. 關鍵字查詢（補強中文精度）──
        kw_results = self._keyword_fallback(intent, kind_filter, top_k * 2)

        # ── 3. 合併：取每個 entry 的最高分 ──
        merged: dict[str, SelectionResult] = {}
        for r in embed_results.values():
            merged[r.entry.id] = r
        for r in kw_results:
            if r.entry.id in merged:
                # 取兩者最高分
                if r.score > merged[r.entry.id].score:
                    merged[r.entry.id] = r
            else:
                merged[r.entry.id] = r

        results = list(merged.values())

        # 排序
        results.sort(key=lambda r: r.score, reverse=True)

        # 去重（同一 agent 只保留最高分的 capability）
        if kind_filter == "agent":
            seen_agents = set()
            deduped = []
            for r in results:
                agent_id = r.entry.metadata.get("agent_id", r.entry.id)
                if agent_id not in seen_agents:
                    deduped.append(r)
                    seen_agents.add(agent_id)
            results = deduped

        # Top-K + 排名
        results = results[:top_k]
        for i, r in enumerate(results):
            r.rank = i + 1

        if results:
            logger.info("[CapSel] Query '%s' → %d matches (top: %s %.3f)",
                        intent[:40], len(results),
                        results[0].entry.name, results[0].score)

        return results

    # ── 關鍵字 Fallback ──────────────────────────────────────────────────

    def _keyword_fallback(self, intent: str, kind_filter: str | None,
                          top_k: int) -> list[SelectionResult]:
        """
        當 embedding 不可用時的關鍵字回退。
        比原始的 _CAPABILITY_KEYWORDS 更智能：直接匹配工具/Agent 描述中的關鍵字。

        改進：支持中文 n-gram 匹配（中文無空格分詞，需要字元級子串比對）。
        """
        intent_lower = intent.lower()
        results = []

        # 預先分詞：英文用 split()，中文用 2/3-gram 滑窗
        intent_words = set(intent_lower.split())
        intent_ngrams = self._extract_cjk_ngrams(intent_lower, min_n=2, max_n=4)

        for entry in self._index:
            if kind_filter and entry.kind != kind_filter:
                continue
            desc_lower = entry.description.lower()
            name_lower = entry.name.lower()

            # 英文詞匹配（空格分割）
            desc_words = set(desc_lower.split()) | set(name_lower.split())
            word_overlap = intent_words & desc_words
            word_score = len(word_overlap) / max(len(intent_words), 1) if word_overlap else 0.0

            # 中文 n-gram 子串匹配
            ngram_score = 0.0
            if intent_ngrams:
                desc_text = desc_lower + " " + name_lower
                matches = sum(1 for ng in intent_ngrams if ng in desc_text)
                ngram_score = matches / max(len(intent_ngrams), 1)

            # 取兩者最高分
            score = max(word_score, ngram_score)
            if score > 0:
                results.append(SelectionResult(entry=entry, score=min(score, 1.0)))

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]
        for i, r in enumerate(results):
            r.rank = i + 1
        return results

    @staticmethod
    def _extract_cjk_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> set[str]:
        """
        從文本中提取 CJK（中日韓）字元的 n-gram。
        僅對 CJK 字元序列生成 n-gram，英文部分由 split() 處理。
        """
        import unicodedata
        ngrams: set[str] = set()
        cjk_buffer: list[str] = []

        def flush_buffer():
            if len(cjk_buffer) >= min_n:
                s = "".join(cjk_buffer)
                for n in range(min_n, min(max_n + 1, len(s) + 1)):
                    for i in range(len(s) - n + 1):
                        ngrams.add(s[i:i + n])

        for ch in text:
            # CJK Unified Ideographs range (basic)
            if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
                cjk_buffer.append(ch)
            else:
                flush_buffer()
                cjk_buffer = []
        flush_buffer()
        return ngrams

    # ── 工具名稱列表（for tool_loop 篩選）────────────────────────────────

    def get_relevant_tool_names(self, intent: str, top_k: int = 7) -> list[str]:
        """
        返回與意圖最相關的工具名稱列表。
        用於 tool_loop.py 的語義篩選。

        始終包含基礎工具以確保基本功能。
        """
        # 基礎工具：任何任務都可能需要的核心工具
        base_tools = {"run_command", "read_file", "write_file"}

        results = self.select_tools(intent, top_k=top_k)
        tool_names = [r.entry.metadata.get("tool_name", r.entry.name) for r in results]

        # 合併基礎工具（不超過 top_k + 3）
        combined = list(dict.fromkeys(tool_names + list(base_tools)))
        return combined

    def get_best_agent(self, intent: str) -> Optional[dict]:
        """
        返回最佳 Agent 匹配結果，用於替代 delegator 的關鍵字路由。
        返回 None 表示 CEO 自己處理。
        """
        results = self.select_agents(intent, top_k=1, min_score=0.30)
        if not results:
            return None

        best = results[0]
        return {
            "agent_id": best.entry.metadata.get("agent_id"),
            "agent_name": best.entry.metadata.get("agent_name"),
            "capability": best.entry.metadata.get("capability"),
            "model": best.entry.metadata.get("model"),
            "confidence": best.score,
        }


# ── Singleton ──
capability_selector = CapabilitySelector()
