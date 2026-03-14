"""
Skill: image_gen
圖片生成技能 — 文字生成圖片

支援後端:
1. OpenAI DALL-E 3 (OPENAI_API_KEY)
2. Stability AI (STABILITY_API_KEY)
3. 本地 ComfyUI (COMFYUI_URL, 預設 http://127.0.0.1:8188)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.image_gen")

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "generated_images"


def _generate_dalle(inputs: dict) -> dict:
    """Generate image using OpenAI DALL-E 3."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未設定")

    try:
        import httpx
    except ImportError:
        raise RuntimeError("需要安裝 httpx: pip install httpx")

    prompt = inputs.get("prompt", "")
    size = inputs.get("size", "1024x1024")
    quality = inputs.get("quality", "standard")
    style = inputs.get("style", "vivid")

    resp = httpx.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": quality,
            "style": style,
            "response_format": "url",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    image_url = data["data"][0]["url"]
    revised_prompt = data["data"][0].get("revised_prompt", prompt)

    # Download image
    img_resp = httpx.get(image_url, timeout=30)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"dalle_{int(time.time())}.png"
    out_path = _OUTPUT_DIR / filename
    out_path.write_bytes(img_resp.content)

    return {
        "success": True,
        "backend": "dall-e-3",
        "image_url": image_url,
        "local_path": str(out_path),
        "revised_prompt": revised_prompt,
        "size": size,
    }


def _generate_stability(inputs: dict) -> dict:
    """Generate image using Stability AI."""
    api_key = os.environ.get("STABILITY_API_KEY", "")
    if not api_key:
        raise RuntimeError("STABILITY_API_KEY 未設定")

    try:
        import httpx
    except ImportError:
        raise RuntimeError("需要安裝 httpx: pip install httpx")

    prompt = inputs.get("prompt", "")
    width = int(inputs.get("width", 1024))
    height = int(inputs.get("height", 1024))
    style_preset = inputs.get("style_preset", "")

    body = {
        "text_prompts": [{"text": prompt, "weight": 1}],
        "cfg_scale": 7,
        "width": width,
        "height": height,
        "samples": 1,
        "steps": 30,
    }
    if style_preset:
        body["style_preset"] = style_preset

    negative = inputs.get("negative_prompt", "")
    if negative:
        body["text_prompts"].append({"text": negative, "weight": -1})

    resp = httpx.post(
        "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    import base64
    img_data = base64.b64decode(data["artifacts"][0]["base64"])

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"stability_{int(time.time())}.png"
    out_path = _OUTPUT_DIR / filename
    out_path.write_bytes(img_data)

    return {
        "success": True,
        "backend": "stability-ai",
        "local_path": str(out_path),
        "seed": data["artifacts"][0].get("seed"),
        "size": f"{width}x{height}",
    }


def _generate_comfyui(inputs: dict) -> dict:
    """Generate image using local ComfyUI."""
    base_url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

    try:
        import httpx
    except ImportError:
        raise RuntimeError("需要安裝 httpx: pip install httpx")

    prompt_text = inputs.get("prompt", "")
    negative = inputs.get("negative_prompt", "")
    width = int(inputs.get("width", 1024))
    height = int(inputs.get("height", 1024))
    steps = int(inputs.get("steps", 20))

    # Simple txt2img workflow
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(time.time()),
                "steps": steps,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "bad quality", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "arcmind", "images": ["8", 0]}},
    }

    # Queue the prompt
    resp = httpx.post(
        f"{base_url}/prompt",
        json={"prompt": workflow},
        timeout=10,
    )
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    # Poll for completion
    for _ in range(60):
        time.sleep(2)
        hist = httpx.get(f"{base_url}/history/{prompt_id}", timeout=10).json()
        if prompt_id in hist:
            outputs = hist[prompt_id].get("outputs", {})
            for node_id, output in outputs.items():
                images = output.get("images", [])
                if images:
                    img_info = images[0]
                    img_url = f"{base_url}/view?filename={img_info['filename']}&subfolder={img_info.get('subfolder', '')}&type={img_info.get('type', 'output')}"

                    # Download
                    img_resp = httpx.get(img_url, timeout=15)
                    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    filename = f"comfyui_{int(time.time())}.png"
                    out_path = _OUTPUT_DIR / filename
                    out_path.write_bytes(img_resp.content)

                    return {
                        "success": True,
                        "backend": "comfyui",
                        "local_path": str(out_path),
                        "prompt_id": prompt_id,
                        "size": f"{width}x{height}",
                    }
            break

    return {"success": False, "error": "ComfyUI 生成超時", "prompt_id": prompt_id}


def _generate(inputs: dict) -> dict:
    """Auto-select backend and generate image."""
    backend = inputs.get("backend", "auto")

    if backend == "dalle" or (backend == "auto" and os.environ.get("OPENAI_API_KEY")):
        return _generate_dalle(inputs)
    elif backend == "stability" or (backend == "auto" and os.environ.get("STABILITY_API_KEY")):
        return _generate_stability(inputs)
    elif backend == "comfyui":
        return _generate_comfyui(inputs)
    elif backend == "auto":
        # Try ComfyUI as local fallback
        try:
            import httpx
            resp = httpx.get(os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188") + "/system_stats", timeout=3)
            if resp.status_code == 200:
                return _generate_comfyui(inputs)
        except Exception:
            pass
        return {"success": False, "error": "沒有可用的圖片生成後端。需要 OPENAI_API_KEY、STABILITY_API_KEY 或本地 ComfyUI。"}
    else:
        return {"success": False, "error": f"未知 backend: {backend}. 可選: dalle, stability, comfyui, auto"}


def _list_images(inputs: dict) -> dict:
    """List generated images."""
    max_results = int(inputs.get("max_results", 20))

    if not _OUTPUT_DIR.exists():
        return {"success": True, "images": [], "count": 0}

    images = []
    for f in sorted(_OUTPUT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        images.append({
            "path": str(f),
            "name": f.name,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime,
        })
        if len(images) >= max_results:
            break

    return {"success": True, "images": images, "count": len(images)}


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Image generation skill entry point.

    inputs:
      action: generate | list_images
      backend: "dalle" | "stability" | "comfyui" | "auto" (預設 auto)
      prompt: str (生成時必填)
      negative_prompt: str (可選)
      size: str (dalle: "1024x1024", "1792x1024", "1024x1792")
      width/height: int (stability/comfyui)
      quality: str (dalle: "standard" | "hd")
      style: str (dalle: "vivid" | "natural")
      style_preset: str (stability: "3d-model", "analog-film", etc.)
    """
    action = inputs.get("action", "generate")

    if action == "list_images":
        return _list_images(inputs)
    elif action == "generate":
        prompt = inputs.get("prompt", "")
        if not prompt:
            return {"success": False, "error": "prompt 為必填"}
        try:
            return _generate(inputs)
        except Exception as e:
            logger.error("[image_gen] generation failed: %s", e)
            return {"success": False, "error": str(e)}
    else:
        return {
            "success": False,
            "error": f"未知 action: {action}",
            "available_actions": ["generate", "list_images"],
        }
