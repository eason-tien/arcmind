"""
Skill: qrcode_skill
QR Code 生成/讀取
生成: 使用 qrcode 套件 (pip install qrcode[pil])
讀取: 使用 pyzbar (pip install pyzbar) 或 fallback 到 zxing-cpp
"""
from __future__ import annotations
import logging, time
from pathlib import Path
logger = logging.getLogger("arcmind.skill.qrcode")
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "qrcodes"

def _generate(inputs: dict) -> dict:
    data = inputs.get("data", "")
    if not data:
        return {"success": False, "error": "data 為必填"}
    try:
        import qrcode
    except ImportError:
        return {"success": False, "error": "需要安裝 qrcode: pip install qrcode[pil]"}
    size = int(inputs.get("size", 10))
    border = int(inputs.get("border", 4))
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"qr_{int(time.time())}.png"
    out_path = _OUTPUT_DIR / filename
    qr = qrcode.QRCode(version=1, box_size=size, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(str(out_path))
    return {"success": True, "path": str(out_path), "data": data[:200]}

def _read(inputs: dict) -> dict:
    image_path = inputs.get("image_path", "")
    if not image_path:
        return {"success": False, "error": "image_path 為必填"}
    if not Path(image_path).exists():
        return {"success": False, "error": f"檔案不存在: {image_path}"}
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
        img = Image.open(image_path)
        results = decode(img)
        decoded = [{"data": r.data.decode("utf-8", errors="replace"), "type": r.type} for r in results]
        return {"success": True, "results": decoded, "count": len(decoded)}
    except ImportError:
        return {"success": False, "error": "需要安裝: pip install pyzbar Pillow"}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "generate")
    handlers = {"generate": _generate, "read": _read}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[qrcode] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
