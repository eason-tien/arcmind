"""
Skill: ocr_skill
OCR 文字辨識 — macOS Vision / Tesseract fallback
"""
from __future__ import annotations
import logging, platform, subprocess, tempfile
from pathlib import Path
logger = logging.getLogger("arcmind.skill.ocr")

def _ocr_macos(image_path: str, lang: str = "") -> str:
    """Use macOS Vision framework via Swift script."""
    script = '''
import Cocoa
import Vision
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url),
      let tiffData = image.tiffRepresentation,
      let cgImage = NSBitmapImageRep(data: tiffData)?.cgImage else {
    print("ERROR: Cannot load image")
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hant", "zh-Hans", "en", "ja", "ko"]
let handler = VNImageRequestHandler(cgImage: cgImage)
try handler.perform([request])
guard let observations = request.results else { exit(0) }
for observation in observations {
    if let candidate = observation.topCandidates(1).first {
        print(candidate.string)
    }
}
'''
    with tempfile.NamedTemporaryFile(suffix=".swift", mode="w", delete=False) as f:
        f.write(script)
        swift_path = f.name
    try:
        r = subprocess.run(["swift", swift_path, image_path], capture_output=True, timeout=30)
        return r.stdout.decode("utf-8", errors="replace").strip()
    finally:
        Path(swift_path).unlink(missing_ok=True)

def _ocr_tesseract(image_path: str, lang: str = "eng+chi_tra") -> str:
    """Use Tesseract OCR."""
    r = subprocess.run(["tesseract", image_path, "stdout", "-l", lang],
                      capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"Tesseract 失敗: {r.stderr.decode()[:500]}")
    return r.stdout.decode("utf-8", errors="replace").strip()

def _recognize(inputs: dict) -> dict:
    image_path = inputs.get("image_path", "")
    lang = inputs.get("lang", "")
    engine = inputs.get("engine", "auto")
    if not image_path:
        return {"success": False, "error": "image_path 為必填"}
    if not Path(image_path).exists():
        return {"success": False, "error": f"檔案不存在: {image_path}"}
    text = ""
    used_engine = ""
    if engine == "auto":
        if platform.system() == "Darwin":
            try:
                text = _ocr_macos(image_path, lang)
                used_engine = "macos_vision"
            except Exception as e:
                logger.warning("[ocr] macOS Vision failed, trying Tesseract: %s", e)
                try:
                    text = _ocr_tesseract(image_path, lang or "eng+chi_tra")
                    used_engine = "tesseract"
                except Exception:
                    return {"success": False, "error": "macOS Vision 和 Tesseract 都失敗"}
        else:
            try:
                text = _ocr_tesseract(image_path, lang or "eng+chi_tra")
                used_engine = "tesseract"
            except FileNotFoundError:
                return {"success": False, "error": "需要安裝 Tesseract: brew install tesseract"}
    elif engine == "vision":
        text = _ocr_macos(image_path, lang)
        used_engine = "macos_vision"
    elif engine == "tesseract":
        text = _ocr_tesseract(image_path, lang or "eng+chi_tra")
        used_engine = "tesseract"
    lines = [l for l in text.split("\n") if l.strip()]
    return {"success": True, "text": text, "lines": lines, "line_count": len(lines),
            "char_count": len(text), "engine": used_engine}

def _batch_ocr(inputs: dict) -> dict:
    image_paths = inputs.get("image_paths", [])
    if not image_paths:
        return {"success": False, "error": "image_paths 為必填 (list)"}
    results = []
    for p in image_paths[:20]:
        r = _recognize({"image_path": p, "lang": inputs.get("lang", ""), "engine": inputs.get("engine", "auto")})
        results.append({"path": p, "text": r.get("text", "")[:2000], "success": r.get("success", False)})
    return {"success": True, "results": results, "count": len(results)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "recognize")
    handlers = {"recognize": _recognize, "batch": _batch_ocr}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[ocr] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
