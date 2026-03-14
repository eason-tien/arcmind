"""
Skill: pdf_skill
PDF 操作 — 文字提取/合併/拆分/資訊
需要: pip install PyMuPDF (fitz)
"""
from __future__ import annotations
import logging
from pathlib import Path
logger = logging.getLogger("arcmind.skill.pdf")

def _get_fitz():
    try:
        import fitz
        return fitz
    except ImportError:
        raise RuntimeError("需要安裝 PyMuPDF: pip install PyMuPDF")

def _extract_text(inputs: dict) -> dict:
    fitz = _get_fitz()
    pdf_path = inputs.get("pdf_path", "")
    pages = inputs.get("pages")  # None = all, or [0,1,2]
    if not pdf_path:
        return {"success": False, "error": "pdf_path 為必填"}
    doc = fitz.open(pdf_path)
    texts = []
    page_range = pages if pages else range(len(doc))
    for i in page_range:
        if 0 <= i < len(doc):
            texts.append({"page": i + 1, "text": doc[i].get_text()[:5000]})
    doc.close()
    return {"success": True, "pages": texts, "total_pages": len(doc), "count": len(texts)}

def _merge(inputs: dict) -> dict:
    fitz = _get_fitz()
    pdf_files = inputs.get("pdf_files", [])
    output = inputs.get("output", "/tmp/merged.pdf")
    if len(pdf_files) < 2:
        return {"success": False, "error": "至少需要 2 個 PDF 檔案"}
    result = fitz.open()
    for f in pdf_files:
        doc = fitz.open(f)
        result.insert_pdf(doc)
        doc.close()
    result.save(output)
    result.close()
    return {"success": True, "output": output, "total_pages": result.page_count if hasattr(result, 'page_count') else 0}

def _split(inputs: dict) -> dict:
    fitz = _get_fitz()
    pdf_path = inputs.get("pdf_path", "")
    output_dir = inputs.get("output_dir", "/tmp/pdf_split")
    page_ranges = inputs.get("page_ranges")  # [[0,2], [3,5]] or None for per-page
    if not pdf_path:
        return {"success": False, "error": "pdf_path 為必填"}
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    outputs = []
    if page_ranges:
        for i, (start, end) in enumerate(page_ranges):
            out = fitz.open()
            out.insert_pdf(doc, from_page=start, to_page=end)
            p = str(Path(output_dir) / f"part_{i+1}.pdf")
            out.save(p)
            out.close()
            outputs.append(p)
    else:
        for i in range(len(doc)):
            out = fitz.open()
            out.insert_pdf(doc, from_page=i, to_page=i)
            p = str(Path(output_dir) / f"page_{i+1}.pdf")
            out.save(p)
            out.close()
            outputs.append(p)
    doc.close()
    return {"success": True, "outputs": outputs, "count": len(outputs)}

def _info(inputs: dict) -> dict:
    fitz = _get_fitz()
    pdf_path = inputs.get("pdf_path", "")
    if not pdf_path:
        return {"success": False, "error": "pdf_path 為必填"}
    doc = fitz.open(pdf_path)
    meta = doc.metadata
    info = {"pages": len(doc), "metadata": meta, "size": Path(pdf_path).stat().st_size}
    doc.close()
    return {"success": True, **info}

def run(inputs: dict) -> dict:
    action = inputs.get("action", "extract_text")
    handlers = {"extract_text": _extract_text, "merge": _merge, "split": _split, "info": _info}
    h = handlers.get(action)
    if not h:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return h(inputs)
    except Exception as e:
        logger.error("[pdf] %s failed: %s", action, e)
        return {"success": False, "error": str(e)}
