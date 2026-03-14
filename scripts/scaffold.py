#!/usr/bin/env python3
"""
ArcMind 基础脚板 (Scaffold Template)
用于快速创建新的 Agent/Worker 脚本

使用方法:
    python3 scripts/scaffold.py --name my_agent --type agent
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


class ScaffoldGenerator:
    """脚板生成器"""
    
    TEMPLATES = {
        'agent': '''#!/usr/bin/env python3
"""
{name} Agent
由 ArcMind 脚板自动生成
创建时间: {timestamp}
"""

import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class {class_name}:
    """Agent 主类"""
    
    def __init__(self):
        self.name = "{name}"
        logger.info(f"初始化 {{self.name}}")
    
    def run(self, input_data):
        """执行主逻辑"""
        logger.info(f"处理输入: {{input_data}}")
        # TODO: 实现你的逻辑
        return {{"status": "success", "result": input_data}}
    
    def cleanup(self):
        """清理资源"""
        logger.info("清理资源")


def main():
    agent = {class_name}()
    try:
        result = agent.run("default input")
        print(result)
    finally:
        agent.cleanup()


if __name__ == '__main__':
    main()
''',
        'skill': '''#!/usr/bin/env python3
"""
{name} Skill
由 ArcMind 脚板自动生成
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SKILL_NAME = "{name}"
SKILL_VERSION = "1.0.0"


def execute(params: dict) -> dict:
    """Skill 执行入口"""
    logger.info(f"执行 {{SKILL_NAME}} with params: {{params}}")
    
    # TODO: 实现你的 skill 逻辑
    return {{
        "status": "success",
        "skill": SKILL_NAME,
        "version": SKILL_VERSION,
        "result": params
    }}


def get_manifest():
    """返回 Skill 元数据"""
    return {{
        "name": SKILL_NAME,
        "version": SKILL_VERSION,
        "description": "{description}",
        "parameters": {{}}
    }}


if __name__ == '__main__':
    result = execute({{"test": True}})
    print(result)
''',
        'tool': '''#!/usr/bin/env python3
"""
{name} Tool
由 ArcMind 脚板自动生成
"""

import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def {func_name}(**kwargs) -> dict:
    """
    Tool 函数
    
    Args:
        **kwargs: 输入参数
    
    Returns:
        dict: 执行结果
    """
    logger.info(f"调用 {func_name} with: {{kwargs}}")
    
    # TODO: 实现你的工具逻辑
    return {{
        "status": "success",
        "data": kwargs
    }}


# 导出函数映射
TOOL_FUNCTIONS = {{
    "{func_name}": {func_name}
}}


if __name__ == '__main__':
    result = {func_name}(test=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))
'''
    }
    
    def __init__(self, name: str, template_type: str = 'agent'):
        self.name = name
        self.template_type = template_type
        self.class_name = ''.join(word.capitalize() for word in name.split('_'))
        self.func_name = name.replace('-', '_')
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def generate(self) -> str:
        """生成脚板代码"""
        template = self.TEMPLATES.get(self.template_type, self.TEMPLATES['agent'])
        
        return template.format(
            name=self.name,
            class_name=self.class_name,
            func_name=self.func_name,
            timestamp=self.timestamp,
            description=f"{self.name} description"
        )
    
    def save(self, output_dir: str = None) -> Path:
        """保存脚板文件"""
        if output_dir is None:
            output_dir = PROJECT_ROOT / 'skills'
        
        output_path = Path(output_dir) / f"{self.name}.py"
        
        # 如果文件已存在，询问是否覆盖
        if output_path.exists():
            logger.warning(f"文件已存在: {output_path}")
            # 备份
            backup_path = output_path.with_suffix('.py.bak')
            output_path.rename(backup_path)
            logger.info(f"已备份到: {backup_path}")
        
        content = self.generate()
        output_path.write_text(content, encoding='utf-8')
        
        # 设置执行权限
        os.chmod(output_path, 0o755)
        
        logger.info(f"脚板已创建: {output_path}")
        return output_path


def main():
    parser = argparse.ArgumentParser(description='ArcMind 脚板生成器')
    parser.add_argument('--name', '-n', required=True, help='名称 (如: my_agent)')
    parser.add_argument('--type', '-t', choices=['agent', 'skill', 'tool'], 
                        default='agent', help='模板类型')
    parser.add_argument('--output', '-o', help='输出目录')
    parser.add_argument('--dry-run', action='store_true', help='仅预览不创建')
    
    args = parser.parse_args()
    
    generator = ScaffoldGenerator(args.name, args.type)
    
    if args.dry_run:
        print("=== 生成的代码预览 ===")
        print(generator.generate())
        return 0
    
    output_path = generator.save(args.output)
    print(f"\n✅ 脚板创建成功!")
    print(f"   路径: {output_path}")
    print(f"   类型: {args.type}")
    print(f"\n下一步: 编辑 {output_path} 实现你的逻辑")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
