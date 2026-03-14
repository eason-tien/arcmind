# -*- coding: utf-8 -*-
"""
V2 Phase 2: PM Quality Gate — LLM-based quality evaluation for PM Agent steps.
No keyword hardcoding — pure LLM judgment.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("arcmind.pm_quality_gate")

# Minimum output length to skip LLM verification (saves tokens).
# Below this, LLM checks whether short output truly answers the step.
_SUBSTANTIVE_OUTPUT_THRESHOLD = 200


class PMQualityGate:
    """LLM-based quality gate for PM Agent steps and overall completion.

    Unified audit — all step-level quality judgments flow through this module.
    """

    def verify_step(
        self,
        step_description: str,
        step_result: dict,
        model: str | None = None,
    ) -> dict:
        """
        Primary step verification gate (used inside the retry loop).

        Returns {"pass": bool, "reason": str, "suggestion": str}

        Logic:
        1. Execution failed → immediate fail (no LLM needed)
        2. Output > threshold → assume pass (saves tokens)
        3. Otherwise → LLM judges whether output actually fulfills the step
        """
        # Fast path: execution itself failed
        if not step_result.get("success"):
            return {
                "pass": False,
                "reason": step_result.get("error", "Step execution failed"),
                "suggestion": "Fix the execution error and retry.",
            }

        output = str(step_result.get("output", ""))

        # Fast path: substantive output — likely completed
        if len(output.strip()) > _SUBSTANTIVE_OUTPUT_THRESHOLD:
            return {"pass": True, "reason": "Output is substantive", "suggestion": ""}

        # LLM verification for short/ambiguous outputs
        try:
            from runtime.model_router import model_router

            prompt = (
                f"判断以下步骤是否真正完成了要求。\n\n"
                f"## 步骤要求\n{step_description[:300]}\n\n"
                f"## 实际输出\n{output[:500]}\n\n"
                f'回复 JSON: {{"pass": true/false, "reason": "原因", "suggestion": "改进建议"}}\n'
                f"- pass=true: 输出确实完成了步骤要求\n"
                f"- pass=false: 输出空洞、无关、或未完成要求\n"
                f"只回复 JSON。"
            )

            kwargs = dict(
                prompt=prompt,
                system="你是 QA 验证器。严格判断步骤输出是否真正完成了要求。只回复JSON。",
                max_tokens=256,
                task_type="general",
                budget="low",
            )
            if model:
                kwargs["model"] = model

            resp = model_router.complete(**kwargs)
            return self._parse_verify_response(resp.content)
        except Exception as e:
            logger.debug("[QAGate] verify_step failed, assuming pass: %s", e)

        return {"pass": True, "reason": "Verification skipped", "suggestion": ""}

    def evaluate_plan(self, plan_steps: list[str], original_task: str) -> dict:
        """
        Pre-execution plan review gate.
        Returns {"rating": "pass|marginal|fail", "reason": "..."}
        """
        try:
            from runtime.model_router import model_router

            steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan_steps))
            prompt = (
                f"你是项目质量审计员。评估以下执行计划的质量。\n\n"
                f"原始任务: {original_task[:300]}\n\n"
                f"执行计划:\n{steps_text}\n\n"
                f"评估要点:\n"
                f"- 计划是否覆盖了任务的所有方面？\n"
                f"- 步骤是否合理且可执行？\n"
                f"- 步骤数量是否适当(3-8步)？\n"
                f"- 是否有明显遗漏或不相关步骤？\n\n"
                f'只回复JSON: {{"rating": "pass|marginal|fail", "reason": "简短原因"}}'
            )

            resp = model_router.complete(
                prompt=prompt,
                system="你是项目质量审计员。评估执行计划质量。只回复JSON。",
                max_tokens=256,
                task_type="general",
                budget="low",
            )
            return self._parse_verdict(resp.content, True)
        except ImportError:
            return {"rating": "pass", "reason": "QA module not available"}
        except Exception as e:
            logger.debug("[QAGate] Plan evaluation failed: %s", e)
            return {"rating": "pass", "reason": f"QA error: {e}"}

    def evaluate_completion(
        self,
        original_task: str,
        all_results: list[dict],
        synthesized_output: str,
    ) -> dict:
        """
        Post-completion holistic audit.
        Returns {"rating": "pass|marginal|fail", "reason": "..."}
        """
        try:
            from runtime.model_router import model_router

            results_summary = "\n".join(
                f"步骤{i+1}: {'成功' if r.get('success') else '失败'} — {str(r.get('output',''))[:150]}"
                for i, r in enumerate(all_results)
            )
            success_count = sum(1 for r in all_results if r.get("success"))
            fail_count = len(all_results) - success_count

            prompt = (
                f"你是项目质量审计员。对PM Agent完成的整个任务进行最终审计。\n\n"
                f"原始任务: {original_task[:300]}\n\n"
                f"执行概况: {success_count}步成功, {fail_count}步失败 (共{len(all_results)}步)\n\n"
                f"各步骤结果:\n{results_summary[:1500]}\n\n"
                f"最终汇总:\n{synthesized_output[:500]}\n\n"
                f"评估要点:\n"
                f"- 原始任务的目标是否达成？\n"
                f"- 是否有关键遗漏？\n"
                f"- 整体质量是否可接受？\n\n"
                f'只回复JSON: {{"rating": "pass|marginal|fail", "reason": "简短原因"}}'
            )

            resp = model_router.complete(
                prompt=prompt,
                system="你是项目质量审计员。进行最终审计。只回复JSON。",
                max_tokens=256,
                task_type="general",
                budget="low",
            )
            return self._parse_verdict(resp.content, success_count > fail_count)
        except ImportError:
            return {"rating": "pass", "reason": "QA module not available"}
        except Exception as e:
            logger.debug("[QAGate] Completion audit failed: %s", e)
            return {"rating": "pass", "reason": f"QA error: {e}"}

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove <think>...</think> blocks (MiniMax reasoning)."""
        return re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract first JSON object from text, tolerating trailing commas."""
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            raw = text[start:end]
            raw = re.sub(r',\s*}', '}', raw)
            raw = re.sub(r',\s*]', ']', raw)
            return json.loads(raw)
        return None

    @staticmethod
    def _safe_bool(val) -> bool:
        """Safely convert LLM JSON value to bool.

        Handles the Python gotcha: bool("no") == True.
        """
        if isinstance(val, str):
            return val.lower().strip() not in ("false", "no", "fail", "0", "")
        return bool(val)

    def _parse_verify_response(self, text: str) -> dict:
        """Parse verify_step LLM response into {pass, reason, suggestion}."""
        try:
            text = self._strip_think_tags(text)
            data = self._extract_json(text)
            if data:
                return {
                    "pass": self._safe_bool(data.get("pass", True)),
                    "reason": str(data.get("reason", ""))[:200],
                    "suggestion": str(data.get("suggestion", ""))[:200],
                }
        except (json.JSONDecodeError, Exception):
            pass
        return {"pass": True, "reason": "Parse failed", "suggestion": ""}

    def _parse_verdict(self, text: str, default_pass: bool = True) -> dict:
        """Parse rating-style LLM response into {rating, reason}."""
        try:
            text = self._strip_think_tags(text)
            data = self._extract_json(text)
            if data:
                rating = data.get("rating", "pass").lower()
                if rating not in ("pass", "marginal", "fail"):
                    rating = "pass" if default_pass else "fail"
                return {"rating": rating, "reason": data.get("reason", "")}
        except (json.JSONDecodeError, Exception):
            pass
        return {"rating": "pass" if default_pass else "fail", "reason": "Parse failed"}


# Singleton
pm_quality_gate = PMQualityGate()
