"""
Skill: archive_skill
壓縮/解壓 — zip, tar, gzip, bz2
"""
from __future__ import annotations
import logging, os, shutil, tarfile, zipfile
from pathlib import Path
logger = logging.getLogger("arcmind.skill.archive")

def _compress(inputs: dict) -> dict:
    source = inputs.get("source", "")
    output = inputs.get("output", "")
    fmt = inputs.get("format", "zip")  # zip | tar | tar.gz | tar.bz2
    if not source:
        return {"success": False, "error": "source 為必填"}
    src = Path(source).expanduser()
    if not src.exists():
        return {"success": False, "error": f"來源不存在: {source}"}
    if not output:
        output = str(src) + (".zip" if fmt == "zip" else f".{fmt}")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(src.parent))
            else:
                zf.write(src, src.name)
    elif fmt.startswith("tar"):
        mode = "w:gz" if "gz" in fmt else "w:bz2" if "bz2" in fmt else "w"
        with tarfile.open(str(out), mode) as tf:
            tf.add(str(src), arcname=src.name)
    else:
        return {"success": False, "error": f"不支援格式: {fmt}"}
    return {"success": True, "output": str(out), "size": out.stat().st_size, "format": fmt}

def _extract(inputs: dict) -> dict:
    archive = inputs.get("archive", "")
    dest = inputs.get("destination", "")
    if not archive:
        return {"success": False, "error": "archive 為必填"}
    arc = Path(archive).expanduser()
    if not arc.exists():
        return {"success": False, "error": f"檔案不存在: {archive}"}
    if not dest:
        dest = str(arc.parent / arc.stem)
    Path(dest).mkdir(parents=True, exist_ok=True)
    if arc.suffix == ".zip":
        with zipfile.ZipFile(str(arc), "r") as zf:
            zf.extractall(dest)
            names = zf.namelist()
    elif arc.suffix in (".tar", ".gz", ".bz2", ".xz", ".tgz"):
        with tarfile.open(str(arc), "r:*") as tf:
            tf.extractall(dest)
            names = tf.getnames()
    else:
        return {"success": False, "error": f"不支援格式: {arc.suffix}"}
    return {"success": True, "destination": dest, "files_count": len(names)}

def _list_contents(inputs: dict) -> dict:
    archive = inputs.get("archive", "")
    if not archive:
        return {"success": False, "error": "archive 為必填"}
    arc = Path(archive).expanduser()
    if not arc.exists():
        return {"success": False, "error": f"檔案不存在: {archive}"}
    files = []
    if arc.suffix == ".zip":
        with zipfile.ZipFile(str(arc), "r") as zf:
            for info in zf.infolist():
                files.append({"name": info.filename, "size": info.file_size, "compressed": info.compress_size})
    elif arc.suffix in (".tar", ".gz", ".bz2", ".xz", ".tgz"):
        with tarfile.open(str(arc), "r:*") as tf:
            for m in tf.getmembers():
                files.append({"name": m.name, "size": m.size, "is_dir": m.isdir()})
    return {"success": True, "files": files[:100], "count": len(files)}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "compress")
    handlers = {"compress": _compress, "extract": _extract, "list": _list_contents}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[archive] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
