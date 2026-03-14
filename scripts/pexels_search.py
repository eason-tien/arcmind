#!/usr/bin/env python3
"""
Pexels 图片/视频搜索工具
用法: python3 scripts/pexels_search.py <图片|视频> <关键词>
"""
import os
import sys
import requests

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
BASE_URL = "https://api.pexels.com/v1"

def search_images(query, per_page=5):
    """搜索图片"""
    headers = {"Authorization": PEXELS_API_KEY}
    resp = requests.get(f"{BASE_URL}/search", headers=headers, params={"query": query, "per_page": per_page})
    data = resp.json()
    results = []
    for photo in data.get("photos", []):
        results.append(f"- {photo['id']}: {photo['photographer']} | {photo['src']['tiny']}")
    return results

def search_videos(query, per_page=5):
    """搜索视频"""
    headers = {"Authorization": PEXELS_API_KEY}
    resp = requests.get(f"{BASE_URL}/videos/search", headers=headers, params={"query": query, "per_page": per_page})
    data = resp.json()
    results = []
    for video in data.get("videos", []):
        hd = video["video_files"][0]["link"] if video["video_files"] else "N/A"
        results.append(f"- {video['id']}: {video['user']['name']} | {hd}")
    return results

if __name__ == "__main__":
    if not PEXELS_API_KEY:
        print("❌ PEXELS_API_KEY 未设置")
        sys.exit(1)
    
    if len(sys.argv) < 3:
        print("用法: python3 pexels_search.py <图片|视频> <关键词>")
        sys.exit(1)
    
    type_, query = sys.argv[1], sys.argv[2]
    
    if type_ == "图片":
        results = search_images(query)
    elif type_ == "视频":
        results = search_videos(query)
    else:
        print("类型只能是: 图片 或 视频")
        sys.exit(1)
    
    for r in results:
        print(r)
