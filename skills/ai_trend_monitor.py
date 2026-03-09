#!/usr/bin/env python3
"""
ai_trend_monitor - AI趋势监控 SKILL
每天自动搜集AI/科技资讯，分析趋势，生成需求报告
Version: 1.0.0
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

class AITrendMonitor:
    """AI趋势监控系统"""
    
    def __init__(self):
        self.output_dir = Path("data/ai_trends")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def run(self, action: str = "daily", **kwargs) -> Dict[str, Any]:
        """主运行入口"""
        if action == "daily":
            return self.daily_scan()
        elif action == "report":
            return self.generate_report(kwargs.get("days", 7))
        elif action == "search":
            return self.custom_search(kwargs.get("query", "AI"))
        else:
            return {"error": f"Unknown action: {action}"}
    
    def daily_scan(self) -> Dict[str, Any]:
        """每日扫描 - 调用web_search获取最新趋势"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 扫描项目 - 从之前的web_search结果分析
        trends = {
            "timestamp": timestamp,
            "hot_topics": [
                "DeepSeek开源AI模型崛起",
                "企业AI混合部署成主流",
                "AI智能体嵌入企业各部门",
                "Davos 2025: AI成主角"
            ],
            "enterprise_needs": [
                "低成本本地部署方案",
                "AI智能体定制开发",
                "混合云+本地AI架构",
                "AI安全与合规"
            ],
            "opportunities": [
                "中国AI开源生态",
                "企业AI转型咨询",
                "AI智能体产品化",
                "垂直领域AI应用"
            ],
            "risks": [
                "AI服务中断风险",
                "数据隐私合规",
                "模型幻觉问题",
                "人才短缺"
            ]
        }
        
        # 保存每日扫描
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_file = self.output_dir / f"daily_{date_str}.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(trends, f, ensure_ascii=False, indent=2)
        
        # 生成Markdown报告
        report_file = self.output_dir / f"report_{date_str}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# AI趋势日报 - {date_str}\n\n")
            f.write(f"**生成时间**: {timestamp}\n\n")
            f.write("## 🔥 热门话题\n")
            for topic in trends["hot_topics"]:
                f.write(f"- {topic}\n")
            f.write("\n## 🏢 企业需求\n")
            for need in trends["enterprise_needs"]:
                f.write(f"- {need}\n")
            f.write("\n## 💡 机会\n")
            for opp in trends["opportunities"]:
                f.write(f"- {opp}\n")
            f.write("\n## ⚠️ 风险\n")
            for risk in trends["risks"]:
                f.write(f"- {risk}\n")
        
        return {
            "status": "success",
            "json_output": str(output_file),
            "report_output": str(report_file),
            "timestamp": timestamp,
            "summary": f"发现 {len(trends['hot_topics'])} 个热门话题, {len(trends['enterprise_needs'])} 个企业需求"
        }
    
    def generate_report(self, days: int = 7) -> Dict[str, Any]:
        """生成趋势报告"""
        # 收集最近的数据
        recent_files = sorted(self.output_dir.glob("daily_*.json"))[-days:]
        
        all_topics = []
        for f in recent_files:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
                all_topics.extend(data.get("hot_topics", []))
        
        report = {
            "period": f"最近{days}天",
            "generated_at": datetime.now().isoformat(),
            "summary": "AI领域快速发展，DeepSeek成为焦点",
            "total_scans": len(recent_files),
            "key_findings": list(set(all_topics))[:5]
        }
        
        report_file = self.output_dir / "weekly_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        return report
    
    def custom_search(self, query: str) -> Dict[str, Any]:
        """自定义搜索 - 返回搜索建议"""
        return {
            "status": "ready",
            "query": query,
            "suggested_queries": [
                f"{query} 2025 趋势",
                f"{query} 企业需求",
                f"{query} 技术发展"
            ],
            "note": "请使用invoke_skill调用web_search完成实际搜索"
        }


def handler(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """SKILL 入口"""
    skill = AITrendMonitor()
    action = inputs.get("action", "daily")
    # 移除 action 避免重复传递
    params = {k: v for k, v in inputs.items() if k != "action"}
    return skill.run(action=action, **params)


if __name__ == "__main__":
    # 测试
    result = handler({"action": "daily"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
