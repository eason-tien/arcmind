"""
Skill: hash_skill
雜湊/編碼/加密工具 — MD5, SHA, Base64, URL encode, JWT decode
"""
from __future__ import annotations
import base64, hashlib, hmac, json, logging, urllib.parse
logger = logging.getLogger("arcmind.skill.hash")

def _hash_text(inputs: dict) -> dict:
    text = inputs.get("text", "")
    algorithm = inputs.get("algorithm", "sha256")
    if not text:
        return {"success": False, "error": "text 為必填"}
    data = text.encode("utf-8")
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256,
             "sha512": hashlib.sha512, "sha3_256": hashlib.sha3_256}
    fn = algos.get(algorithm)
    if not fn:
        return {"success": False, "error": f"不支援: {algorithm}", "available": list(algos.keys())}
    return {"success": True, "hash": fn(data).hexdigest(), "algorithm": algorithm}

def _hash_file(inputs: dict) -> dict:
    from pathlib import Path
    file_path = inputs.get("file_path", "")
    algorithm = inputs.get("algorithm", "sha256")
    if not file_path or not Path(file_path).exists():
        return {"success": False, "error": "file_path 為必填且檔案必須存在"}
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return {"success": True, "hash": h.hexdigest(), "algorithm": algorithm, "file": file_path}

def _encode(inputs: dict) -> dict:
    text = inputs.get("text", "")
    encoding = inputs.get("encoding", "base64")
    if not text:
        return {"success": False, "error": "text 為必填"}
    if encoding == "base64":
        result = base64.b64encode(text.encode("utf-8")).decode()
    elif encoding == "base64url":
        result = base64.urlsafe_b64encode(text.encode("utf-8")).decode()
    elif encoding == "url":
        result = urllib.parse.quote(text)
    elif encoding == "hex":
        result = text.encode("utf-8").hex()
    else:
        return {"success": False, "error": f"不支援: {encoding}"}
    return {"success": True, "result": result, "encoding": encoding}

def _decode(inputs: dict) -> dict:
    text = inputs.get("text", "")
    encoding = inputs.get("encoding", "base64")
    if not text:
        return {"success": False, "error": "text 為必填"}
    try:
        if encoding == "base64":
            result = base64.b64decode(text).decode("utf-8", errors="replace")
        elif encoding == "base64url":
            result = base64.urlsafe_b64decode(text).decode("utf-8", errors="replace")
        elif encoding == "url":
            result = urllib.parse.unquote(text)
        elif encoding == "hex":
            result = bytes.fromhex(text).decode("utf-8", errors="replace")
        elif encoding == "jwt":
            parts = text.split(".")
            decoded = {}
            for i, name in enumerate(["header", "payload"]):
                if i < len(parts):
                    padded = parts[i] + "=" * (4 - len(parts[i]) % 4)
                    decoded[name] = json.loads(base64.urlsafe_b64decode(padded))
            return {"success": True, "result": decoded, "encoding": "jwt"}
        else:
            return {"success": False, "error": f"不支援: {encoding}"}
        return {"success": True, "result": result, "encoding": encoding}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _hmac_sign(inputs: dict) -> dict:
    text = inputs.get("text", "")
    key = inputs.get("key", "")
    algorithm = inputs.get("algorithm", "sha256")
    if not text or not key:
        return {"success": False, "error": "text 和 key 為必填"}
    h = hmac.new(key.encode("utf-8"), text.encode("utf-8"), algorithm)
    return {"success": True, "signature": h.hexdigest(), "algorithm": f"hmac-{algorithm}"}

def _uuid(inputs: dict) -> dict:
    import uuid
    version = int(inputs.get("version", 4))
    if version == 4:
        return {"success": True, "uuid": str(uuid.uuid4())}
    elif version == 1:
        return {"success": True, "uuid": str(uuid.uuid1())}
    return {"success": False, "error": f"不支援 UUID v{version}"}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "hash")
    handlers = {"hash": _hash_text, "hash_file": _hash_file, "encode": _encode,
                "decode": _decode, "hmac": _hmac_sign, "uuid": _uuid}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[hash] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
