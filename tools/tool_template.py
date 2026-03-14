#!/usr/bin/env python3
"""
ArcMind 工具脚板模板
用于快速创建可被ArcMind调用的工具脚本

使用方式:
    python3 tools/tool_template.py --action <action> --params <params>
"""

import argparse
import json
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ArcMindTool:
    """ArcMind 工具基类"""
    
    def __init__(self):
        self.name = "tool_template"
        self.description = "工具描述"
        self.version = "1.0.0"
    
    def execute(self, **kwargs):
        """执行工具主逻辑"""
        raise NotImplementedError("子类必须实现 execute 方法")
    
    def validate_params(self, **kwargs):
        """验证参数"""
        return True
    
    def get_result(self):
        """返回标准结果格式"""
        return {
            "status": "success",
            "tool": self.name,
            "version": self.version,
            "data": None,
            "message": ""
        }


class ToolImplementation(ArcMindTool):
    """实际工具实现"""
    
    def __init__(self):
        super().__init__()
        self.name = "example_tool"
        self.description = "示例工具 - 用于演示"
    
    def execute(self, **kwargs):
        """执行工具逻辑"""
        action = kwargs.get("action", "default")
        params = kwargs.get("params", {})
        
        # 根据action执行不同操作
        if action == "create":
            return self._create(params)
        elif action == "list":
            return self._list(params)
        elif action == "delete":
            return self._delete(params)
        else:
            return self._default(params)
    
    def _create(self, params):
        """创建操作"""
        name = params.get("name", "unnamed")
        result = self.get_result()
        result["data"] = {"created": name, "id": id(name)}
        result["message"] = f"成功创建: {name}"
        return result
    
    def _list(self, params):
        """列表操作"""
        result = self.get_result()
        result["data"] = {"items": ["item1", "item2", "item3"]}
        result["message"] = "成功获取列表"
        return result
    
    def _delete(self, params):
        """删除操作"""
        name = params.get("name", "")
        result = self.get_result()
        result["data"] = {"deleted": name}
        result["message"] = f"成功删除: {name}"
        return result
    
    def _default(self, params):
        """默认操作"""
        result = self.get_result()
        result["data"] = {"params": params}
        result["message"] = "执行默认操作"
        return result


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="ArcMind 工具脚板"
    )
    parser.add_argument(
        "--action", 
        type=str, 
        default="default",
        help="操作类型: create, list, delete, default"
    )
    parser.add_argument(
        "--params", 
        type=str, 
        default="{}",
        help="JSON格式参数"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="json",
        choices=["json", "text"],
        help="输出格式"
    )
    
    args = parser.parse_args()
    
    # 解析参数
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError:
        params = {}
    
    # 执行工具
    tool = ToolImplementation()
    result = tool.execute(action=args.action, params=params)
    
    # 输出结果
    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("message", ""))
    
    # 返回状态码
    if result.get("status") == "success":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
