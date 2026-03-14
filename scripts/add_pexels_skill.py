#!/usr/bin/env python3
import yaml

# 读取现有 manifest
with open('/Users/eason/Code/arcmind/skills/__manifest__.yaml', 'r') as f:
    manifest = yaml.safe_load(f)

# 添加 pexels_skill
pexels_skill = {
    'name': 'pexels_skill',
    'module': 'pexels_skill.py',
    'handler': 'run',
    'version': '1.0',
    'description': 'Pexels 免费素材API — 获取高质量图片和视频素材',
    'permissions': ['network'],
    'tags': ['pexels', 'image', 'video', 'stock', 'media', '素材'],
    'governor_required': False,
    'inputs': [
        {'name': 'action', 'type': 'string', 'required': False, 'default': 'search', 'description': 'search (搜索素材) | list_curated (列出精选) | get_photo (获取单张) | get_video (获取单个视频)'},
        {'name': 'query', 'type': 'string', 'required': False, 'description': '搜索关键词'},
        {'name': 'per_page', 'type': 'int', 'required': False, 'default': 5, 'description': '返回数量'},
        {'name': 'orientation', 'type': 'string', 'required': False, 'description': '图片方向: landscape/portrait/square'},
        {'name': 'size', 'type': 'string', 'required': False, 'description': '图片大小: large/medium/small'},
        {'name': 'media_id', 'type': 'int', 'required': False, 'description': '素材ID'},
    ],
    'outputs': [
        {'name': 'success', 'type': 'bool'},
        {'name': 'photos', 'type': 'list'},
        {'name': 'videos', 'type': 'list'},
        {'name': 'total_results', 'type': 'int'},
    ]
}

manifest['skills'].append(pexels_skill)

# 写回
with open('/Users/eason/Code/arcmind/skills/__manifest__.yaml', 'w') as f:
    yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False)

print("✅ pexels_skill 已注册到 manifest")
