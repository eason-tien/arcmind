#!/usr/bin/env python3
"""
Pexels 免费素材API Skill
用于获取高质量图片和视频素材

API文档: https://www.pexels.com/api/documentation/
"""

import os
import json
import requests
from typing import Dict, Any, Optional, List

PEXELS_API_KEY = os.getenv('PEXELS_API_KEY')
BASE_URL = 'https://api.pexels.com/v1'

def run(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pexels Skill 主入口
    
    Args:
        inputs: 包含 action, query, per_page, orientation, size, media_id 等参数
    
    Returns:
        包含 success, photos/videos, total_results 等字段的字典
    """
    if not PEXELS_API_KEY:
        return {
            'success': False,
            'error': 'PEXELS_API_KEY 未设置，请先配置环境变量'
        }
    
    action = inputs.get('action', 'search')
    
    try:
        if action == 'search':
            return search_photos(inputs)
        elif action == 'list_curated':
            return list_curated(inputs)
        elif action == 'get_photo':
            return get_photo(inputs)
        elif action == 'get_video':
            return get_video(inputs)
        else:
            return {
                'success': False,
                'error': f'未知 action: {action}'
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def search_photos(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """搜索图片"""
    query = inputs.get('query', '')
    per_page = inputs.get('per_page', 5)
    orientation = inputs.get('orientation')  # landscape, portrait, square
    size = inputs.get('size')  # large, medium, small
    
    params = {
        'query': query,
        'per_page': per_page,
    }
    if orientation:
        params['orientation'] = orientation
    if size:
        params['size'] = size
    
    headers = {'Authorization': PEXELS_API_KEY}
    response = requests.get(f'{BASE_URL}/search', params=params, headers=headers)
    data = response.json()
    
    photos = []
    for photo in data.get('photos', []):
        photos.append({
            'id': photo['id'],
            'width': photo['width'],
            'height': photo['height'],
            'url': photo['url'],
            'photographer': photo['photographer'],
            'photographer_url': photo['photographer_url'],
            'src': photo['src'],  # 包含各种尺寸的URL
        })
    
    return {
        'success': True,
        'photos': photos,
        'total_results': data.get('total_results', 0),
        'page': data.get('page', 1),
        'per_page': data.get('per_page', per_page),
    }


def list_curated(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """获取精选图片列表"""
    per_page = inputs.get('per_page', 5)
    page = inputs.get('page', 1)
    
    params = {
        'per_page': per_page,
        'page': page,
    }
    
    headers = {'Authorization': PEXELS_API_KEY}
    response = requests.get(f'{BASE_URL}/curated', params=params, headers=headers)
    data = response.json()
    
    photos = []
    for photo in data.get('photos', []):
        photos.append({
            'id': photo['id'],
            'width': photo['width'],
            'height': photo['height'],
            'url': photo['url'],
            'photographer': photo['photographer'],
            'src': photo['src'],
        })
    
    return {
        'success': True,
        'photos': photos,
        'total_results': data.get('total_results', 0),
        'next_page': data.get('next_page'),
    }


def get_photo(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """获取单张图片详情"""
    media_id = inputs.get('media_id')
    
    if not media_id:
        return {
            'success': False,
            'error': 'media_id 不能为空'
        }
    
    headers = {'Authorization': PEXELS_API_KEY}
    response = requests.get(f'{BASE_URL}/photos/{media_id}', headers=headers)
    
    if response.status_code == 404:
        return {
            'success': False,
            'error': '图片不存在'
        }
    
    photo = response.json()
    
    return {
        'success': True,
        'photo': {
            'id': photo['id'],
            'width': photo['width'],
            'height': photo['height'],
            'url': photo['url'],
            'photographer': photo['photographer'],
            'photographer_url': photo['photographer_url'],
            'src': photo['src'],
            'alt': photo.get('alt', ''),
        }
    }


def get_video(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """获取单个视频详情"""
    media_id = inputs.get('media_id')
    
    if not media_id:
        return {
            'success': False,
            'error': 'media_id 不能为空'
        }
    
    headers = {'Authorization': PEXELS_API_KEY}
    response = requests.get(f'{BASE_URL}/videos/{media_id}', headers=headers)
    
    if response.status_code == 404:
        return {
            'success': False,
            'error': '视频不存在'
        }
    
    video = response.json()
    
    # 简化视频信息
    video_files = []
    for f in video.get('video_files', []):
        video_files.append({
            'id': f['id'],
            'quality': f['quality'],
            'file_type': f['file_type'],
            'width': f['width'],
            'height': f['height'],
            'link': f['link'],
        })
    
    return {
        'success': True,
        'video': {
            'id': video['id'],
            'width': video['width'],
            'height': video['height'],
            'duration': video['duration'],
            'url': video['url'],
            'user': video['user'],
            'video_files': video_files,
            'image': video.get('image'),
        }
    }


if __name__ == '__main__':
    # 测试
    test_inputs = {
        'action': 'search',
        'query': 'nature',
        'per_page': 3,
    }
    result = run(test_inputs)
    print(json.dumps(result, indent=2, ensure_ascii=False))
