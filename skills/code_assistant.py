#!/usr/bin/env python3
"""
code_assistant - 代码开发助手 SKILL
代码生成、修复、优化、解释
Version: 1.0.0
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

class CodeAssistant:
    """代码开发助手"""
    
    SUPPORTED_LANGUAGES = {
        "python": "python",
        "bash": "bash", 
        "shell": "bash",
        "javascript": "node",
        "js": "node",
        "json": "python -m json.tool",
        "yaml": "python -m yaml",
    }
    
    def __init__(self):
        self.output_dir = Path("data/code_outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def run(self, action: str = "generate", **kwargs) -> Dict[str, Any]:
        """主运行入口"""
        handlers = {
            "generate": self.generate_code,
            "fix": self.fix_code,
            "optimize": self.optimize_code,
            "explain": self.explain_code,
            "execute": self.execute_code,
            "test": self.test_code,
        }
        
        if action not in handlers:
            return {"error": f"Unknown action: {action}", "available_actions": list(handlers.keys())}
        
        return handlers[action](kwargs)
    
    def generate_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """生成代码"""
        language = params.get("language", "python").lower()
        prompt = params.get("prompt", "")
        filename = params.get("filename", f"generated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self._get_extension(language)}")
        
        # 构建 prompt
        full_prompt = self._build_prompt(prompt, language, "generate")
        
        # 调用 Ollama 生成代码
        code = self._call_ollama(full_prompt, language)
        
        # 保存代码
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)
        
        # 尝试执行（如果支持）
        execute_result = None
        if language in ["python", "bash", "shell"]:
            execute_result = self._execute_code(code, language)
        
        return {
            "status": "success",
            "action": "generate",
            "language": language,
            "prompt": prompt,
            "code": code,
            "output_file": str(output_path),
            "executed": execute_result is not None,
            "execution_result": execute_result
        }
    
    def fix_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """修复代码"""
        code = params.get("code", "")
        error = params.get("error", "")
        language = params.get("language", "python").lower()
        
        # 构建修复 prompt
        fix_prompt = f"""修复以下 {language} 代码的错误:

原始代码:
```{language}
{code}
```

错误信息:
{error}

请修复错误并解释修复内容。"""
        
        fixed_code = self._call_ollama(fix_prompt, language)
        
        # 保存修复后的代码
        output_path = self.output_dir / f"fixed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self._get_extension(language)}"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
        
        return {
            "status": "success",
            "action": "fix",
            "original_code": code,
            "error": error,
            "fixed_code": fixed_code,
            "output_file": str(output_path)
        }
    
    def optimize_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """优化代码"""
        code = params.get("code", "")
        language = params.get("language", "python").lower()
        focus = params.get("focus", "performance")  # performance, readability, security
        
        optimize_prompt = f"""优化以下 {language} 代码, 专注于 {focus}:

原始代码:
```{language}
{code}
```

请提供优化后的代码并解释优化点。"""
        
        optimized_code = self._call_ollama(optimize_prompt, language)
        
        # 保存优化后的代码
        output_path = self.output_dir / f"optimized_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self._get_extension(language)}"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(optimized_code)
        
        return {
            "status": "success",
            "action": "optimize",
            "original_code": code,
            "focus": focus,
            "optimized_code": optimized_code,
            "output_file": str(output_path)
        }
    
    def explain_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """解释代码"""
        code = params.get("code", "")
        language = params.get("language", "python").lower()
        
        explain_prompt = f"""详细解释以下 {language} 代码:

```{language}
{code}
```

请包括:
1. 代码功能概述
2. 关键逻辑说明
3. 重要变量和函数
4. 潜在问题或注意事项"""
        
        explanation = self._call_ollama(explain_prompt, language)
        
        return {
            "status": "success",
            "action": "explain",
            "language": language,
            "code": code,
            "explanation": explanation
        }
    
    def execute_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行代码"""
        code = params.get("code", "")
        language = params.get("language", "python").lower()
        
        result = self._execute_code(code, language)
        
        return {
            "status": "success",
            "action": "execute",
            "language": language,
            "code": code,
            "result": result
        }
    
    def test_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """测试代码"""
        code = params.get("code", "")
        language = params.get("language", "python").lower()
        test_type = params.get("test_type", "syntax")  # syntax, unit, integration
        
        results = {}
        
        # 语法检查
        if test_type in ["syntax", "unit", "integration"]:
            results["syntax"] = self._check_syntax(code, language)
        
        # 执行测试
        if test_type in ["unit", "integration"]:
            results["execution"] = self._execute_code(code, language)
        
        return {
            "status": "success",
            "action": "test",
            "test_type": test_type,
            "results": results
        }
    
    def _build_prompt(self, prompt: str, language: str, action: str) -> str:
        """构建完整的 prompt"""
        templates = {
            "generate": f"用 {language} 编写代码: {prompt}\n\n只返回代码，不要解释。",
            "fix": f"修复以下 {language} 代码: {prompt}",
            "optimize": f"优化以下 {language} 代码: {prompt}",
            "explain": f"解释以下 {language} 代码: {prompt}",
        }
        return templates.get(action, prompt)
    
    def _call_ollama(self, prompt: str, language: str) -> str:
        """调用 Ollama 生成代码"""
        try:
            # 尝试本地 Ollama
            result = subprocess.run(
                ["ollama", "run", "qwen2.5-coder:14b", prompt],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            pass
        
        # 回退到 API
        return self._call_api(prompt, language)
    
    def _call_api(self, prompt: str, language: str) -> str:
        """调用 API (备用)"""
        # 这里可以接入其他 API
        return f"# 代码生成需要 Ollama 或 API\n# Prompt: {prompt[:100]}..."
    
    def _execute_code(self, code: str, language: str) -> Dict[str, Any]:
        """执行代码（含安全检查）"""
        try:
            # Safety check — reuse code_exec blocklist
            _BLOCKED_PATTERNS = [
                "os.system", "subprocess.Popen", "subprocess.call",
                "socket", "shutil.rmtree", "__import__",
                "open(", "eval(", "exec(",
                "importlib", "getattr(__builtins__",
            ]
            for pattern in _BLOCKED_PATTERNS:
                if pattern in code:
                    return {"error": f"Security: blocked pattern '{pattern}' in LLM-generated code"}

            if language in ["python"]:
                result = subprocess.run(
                    ["python3", "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            elif language in ["bash", "shell"]:
                result = subprocess.run(
                    ["bash", "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            else:
                return {"error": f"Unsupported language for execution: {language}"}
            
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "success": result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {"error": "Execution timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    def _check_syntax(self, code: str, language: str) -> Dict[str, Any]:
        """检查语法"""
        try:
            if language == "python":
                result = subprocess.run(
                    ["python3", "-m", "py_compile", "-c", code],
                    capture_output=True,
                    text=True
                )
                return {"valid": result.returncode == 0, "error": result.stderr if result.returncode != 0 else None}
            return {"valid": True, "note": "Syntax check not implemented for this language"}
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    def _get_extension(self, language: str) -> str:
        """获取文件扩展名"""
        extensions = {
            "python": "py",
            "bash": "sh",
            "shell": "sh",
            "javascript": "js",
        }
        return extensions.get(language, "txt")


def handler(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """SKILL 入口"""
    skill = CodeAssistant()
    action = inputs.get("action", "generate")
    params = {k: v for k, v in inputs.items() if k != "action"}
    return skill.run(action=action, **params)


if __name__ == "__main__":
    # 测试
    result = handler({"action": "generate", "language": "python", "prompt": "Hello World 程序"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
