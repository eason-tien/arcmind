#!/usr/bin/env python3
"""
agent_builder - 多步骤智能体工作流构建器
帮助用户快速创建和管理 AI Agent 任务链
Version: 1.0.0
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# 数据存储路径
DATA_DIR = Path("data/agent_builder")
AGENTS_FILE = DATA_DIR / "agents.json"
WORKFLOWS_FILE = DATA_DIR / "workflows.json"
EXECUTIONS_FILE = DATA_DIR / "executions.json"

class AgentBuilder:
    """多步骤智能体工作流构建器"""
    
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_files()
    
    def _ensure_files(self):
        """确保数据文件存在"""
        for f in [AGENTS_FILE, WORKFLOWS_FILE, EXECUTIONS_FILE]:
            if not f.exists():
                f.write_text("[]", encoding="utf-8")
    
    def _read_json(self, filepath: Path) -> List:
        """读取 JSON 文件"""
        try:
            return json.loads(filepath.read_text(encoding="utf-8"))
        except:
            return []
    
    def _write_json(self, filepath: Path, data: List):
        """写入 JSON 文件"""
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    def run(self, action: str = "list_agents", **kwargs) -> Dict[str, Any]:
        """主运行入口"""
        handlers = {
            "create_agent": self.create_agent,
            "create_workflow": self.create_workflow,
            "execute_workflow": self.execute_workflow,
            "add_step": self.add_step,
            "list_agents": self.list_agents,
            "list_workflows": self.list_workflows,
            "get_status": self.get_status,
            "list_executions": self.list_executions,
        }
        
        if action not in handlers:
            return {
                "error": f"Unknown action: {action}",
                "available_actions": list(handlers.keys())
            }
        
        return handlers[action](kwargs)
    
    def create_agent(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建新 Agent"""
        name = params.get("name", "")
        description = params.get("description", "")
        capabilities = params.get("capabilities", [])
        model = params.get("model", "ollama:qwen3:8b")
        
        if not name:
            return {"error": "Agent name is required"}
        
        agents = self._read_json(AGENTS_FILE)
        
        # 检查是否已存在
        for agent in agents:
            if agent.get("name") == name:
                return {"error": f"Agent '{name}' already exists"}
        
        new_agent = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "model": model,
            "created_at": datetime.now().isoformat(),
            "status": "active"
        }
        
        agents.append(new_agent)
        self._write_json(AGENTS_FILE, agents)
        
        return {
            "status": "success",
            "action": "create_agent",
            "agent": new_agent
        }
    
    def create_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建工作流"""
        name = params.get("name", "")
        description = params.get("description", "")
        agent_id = params.get("agent_id", "")
        
        if not name:
            return {"error": "Workflow name is required"}
        
        workflows = self._read_json(WORKFLOWS_FILE)
        
        # 检查是否已存在
        for wf in workflows:
            if wf.get("name") == name:
                return {"error": f"Workflow '{name}' already exists"}
        
        new_workflow = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "agent_id": agent_id,
            "steps": [],
            "created_at": datetime.now().isoformat(),
            "status": "draft"
        }
        
        workflows.append(new_workflow)
        self._write_json(WORKFLOWS_FILE, workflows)
        
        return {
            "status": "success",
            "action": "create_workflow",
            "workflow": new_workflow
        }
    
    def add_step(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加步骤到工作流"""
        workflow_id = params.get("workflow_id", "")
        step_name = params.get("step_name", "")
        step_type = params.get("step_type", "task")  # task, condition, parallel, loop
        step_config = params.get("step_config", {})
        
        if not workflow_id or not step_name:
            return {"error": "workflow_id and step_name are required"}
        
        workflows = self._read_json(WORKFLOWS_FILE)
        
        # 找到工作流
        workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                workflow = wf
                break
        
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}
        
        new_step = {
            "id": str(uuid.uuid4())[:8],
            "name": step_name,
            "type": step_type,
            "config": step_config,
            "created_at": datetime.now().isoformat()
        }
        
        workflow["steps"].append(new_step)
        self._write_json(WORKFLOWS_FILE, workflows)
        
        return {
            "status": "success",
            "action": "add_step",
            "workflow": workflow,
            "step": new_step
        }
    
    def execute_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行工作流"""
        workflow_id = params.get("workflow_id", "")
        inputs = params.get("inputs", {})
        
        if not workflow_id:
            return {"error": "workflow_id is required"}
        
        workflows = self._read_json(WORKFLOWS_FILE)
        
        # 找到工作流
        workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                workflow = wf
                break
        
        if not workflow:
            return {"error": f"Workflow '{workflow_id}' not found"}
        
        if not workflow.get("steps"):
            return {"error": "Workflow has no steps"}
        
        # 创建执行记录
        execution = {
            "id": str(uuid.uuid4())[:8],
            "workflow_id": workflow_id,
            "workflow_name": workflow.get("name"),
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "steps_results": [],
            "inputs": inputs,
            "outputs": {}
        }
        
        executions = self._read_json(EXECUTIONS_FILE)
        executions.append(execution)
        self._write_json(EXECUTIONS_FILE, executions)
        
        # 执行每个步骤
        current_outputs = inputs.copy()
        
        for i, step in enumerate(workflow["steps"]):
            step_result = self._execute_step(step, current_outputs)
            
            execution["steps_results"].append({
                "step_id": step.get("id"),
                "step_name": step.get("name"),
                "status": "completed" if step_result.get("success") else "failed",
                "result": step_result
            })
            
            if step_result.get("success"):
                # 将输出传递给下一步
                current_outputs.update(step_result.get("output", {}))
            else:
                execution["status"] = "failed"
                execution["error"] = step_result.get("error", "Step failed")
                break
            
            # 更新执行状态
            if i == len(workflow["steps"]) - 1:
                execution["status"] = "completed"
        
        execution["end_time"] = datetime.now().isoformat()
        execution["outputs"] = current_outputs
        
        # 更新执行记录
        for i, ex in enumerate(executions):
            if ex.get("id") == execution["id"]:
                executions[i] = execution
                break
        
        self._write_json(EXECUTIONS_FILE, executions)
        
        return {
            "status": "success",
            "action": "execute_workflow",
            "execution": execution
        }
    
    def _execute_step(self, step: Dict[str, Any], inputs: Dict) -> Dict[str, Any]:
        """执行单个步骤"""
        step_type = step.get("type", "task")
        step_config = step.get("config", {})
        
        try:
            if step_type == "task":
                # 执行任务
                task_type = step_config.get("task_type", "web_search")
                task_inputs = step_config.get("inputs", {})
                
                # 合并输入
                merged_inputs = {**inputs, **task_inputs}
                
                # 这里可以调用其他 SKILL
                return {
                    "success": True,
                    "step_type": "task",
                    "output": {"result": f"Executed {task_type} with inputs: {merged_inputs}"}
                }
            
            elif step_type == "condition":
                # 条件分支
                condition = step_config.get("condition", "")
                true_branch = step_config.get("true_branch", {})
                false_branch = step_config.get("false_branch", {})
                
                # 简单的条件评估
                result = eval(condition, {"inputs": inputs}) if condition else True
                
                return {
                    "success": True,
                    "step_type": "condition",
                    "output": {"branch": "true" if result else "false"}
                }
            
            elif step_type == "parallel":
                # 并行执行
                return {
                    "success": True,
                    "step_type": "parallel",
                    "output": {"note": "Parallel execution simulated"}
                }
            
            elif step_type == "loop":
                # 循环
                return {
                    "success": True,
                    "step_type": "loop",
                    "output": {"iterations": step_config.get("iterations", 1)}
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown step type: {step_type}"
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_agents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有 Agent"""
        agents = self._read_json(AGENTS_FILE)
        
        return {
            "status": "success",
            "action": "list_agents",
            "count": len(agents),
            "agents": agents
        }
    
    def list_workflows(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有工作流"""
        workflows = self._read_json(WORKFLOWS_FILE)
        
        # 简化返回
        for wf in workflows:
            wf.pop("steps", None)
        
        return {
            "status": "success",
            "action": "list_workflows",
            "count": len(workflows),
            "workflows": workflows
        }
    
    def get_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取执行状态"""
        execution_id = params.get("execution_id", "")
        
        if not execution_id:
            return {"error": "execution_id is required"}
        
        executions = self._read_json(EXECUTIONS_FILE)
        
        for ex in executions:
            if ex.get("id") == execution_id:
                return {
                    "status": "success",
                    "action": "get_status",
                    "execution": ex
                }
        
        return {"error": f"Execution '{execution_id}' not found"}
    
    def list_executions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有执行记录"""
        executions = self._read_json(EXECUTIONS_FILE)
        
        # 简化返回
        for ex in executions:
            ex.pop("steps_results", None)
            ex.pop("outputs", None)
        
        return {
            "status": "success",
            "action": "list_executions",
            "count": len(executions),
            "executions": executions[-10:]  # 最近10条
        }


def handler(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """SKILL 入口"""
    skill = AgentBuilder()
    action = inputs.get("action", "list_agents")
    params = {k: v for k, v in inputs.items() if k != "action"}
    return skill.run(action=action, **params)


if __name__ == "__main__":
    # 测试
    result = handler({"action": "list_agents"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
