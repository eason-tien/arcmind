"""
Skill: marp_skill
Marp (Markdown Presentation Ecosystem) — Markdown → PPT/PDF/HTML 簡報

使用 @marp-team/marp-cli (via npx)
安裝: npm install -g @marp-team/marp-cli  或直接用 npx

支援輸出: HTML, PDF, PPTX, PNG, JPEG
內建主題: default, gaia, uncover
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.marp")

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "presentations"
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "marp_templates"


def _find_marp() -> str:
    """Find marp CLI executable."""
    # Check if globally installed
    for cmd in ["marp", "npx"]:
        try:
            subprocess.run([cmd, "--version"] if cmd == "marp" else [cmd, "@marp-team/marp-cli", "--version"],
                          capture_output=True, timeout=15)
            return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("Marp CLI 未安裝。請執行: npm install -g @marp-team/marp-cli")


def _run_marp(args: list[str], timeout: int = 120) -> tuple[bool, str, str]:
    """Run marp CLI command."""
    cmd_base = _find_marp()
    if cmd_base == "npx":
        cmd = ["npx", "-y", "@marp-team/marp-cli"] + args
    else:
        cmd = ["marp"] + args

    logger.info("[marp] Running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    stdout = r.stdout.decode("utf-8", errors="replace").strip()
    stderr = r.stderr.decode("utf-8", errors="replace").strip()
    return r.returncode == 0, stdout, stderr


def _generate_markdown(inputs: dict) -> str:
    """Generate Marp-compatible Markdown from inputs."""
    title = inputs.get("title", "Presentation")
    theme = inputs.get("theme", "default")  # default | gaia | uncover
    paginate = inputs.get("paginate", True)
    slides = inputs.get("slides", [])
    header = inputs.get("header", "")
    footer = inputs.get("footer", "")
    background_color = inputs.get("background_color", "")
    custom_css = inputs.get("custom_css", "")

    # Build front-matter
    frontmatter_lines = [
        "---",
        "marp: true",
        f"theme: {theme}",
    ]
    if paginate:
        frontmatter_lines.append("paginate: true")
    if header:
        frontmatter_lines.append(f"header: '{header}'")
    if footer:
        frontmatter_lines.append(f"footer: '{footer}'")
    if background_color:
        frontmatter_lines.append(f"backgroundColor: '{background_color}'")

    # Custom style
    if custom_css:
        frontmatter_lines.append("style: |")
        for css_line in custom_css.split("\n"):
            frontmatter_lines.append(f"  {css_line}")

    frontmatter_lines.append("---")

    parts = ["\n".join(frontmatter_lines)]

    if slides:
        for i, slide in enumerate(slides):
            if i > 0:
                parts.append("\n---\n")

            slide_parts = []

            # Per-slide directives
            directives = []
            if slide.get("class"):
                directives.append(f"<!-- _class: {slide['class']} -->")
            if slide.get("backgroundColor"):
                directives.append(f"<!-- _backgroundColor: {slide['backgroundColor']} -->")
            if slide.get("backgroundImage"):
                directives.append(f"<!-- _backgroundImage: url('{slide['backgroundImage']}') -->")
            if slide.get("color"):
                directives.append(f"<!-- _color: {slide['color']} -->")

            if directives:
                slide_parts.append("\n".join(directives))

            # Slide content
            if slide.get("title"):
                level = slide.get("heading_level", 1 if i == 0 else 2)
                slide_parts.append(f"{'#' * level} {slide['title']}")

            if slide.get("subtitle"):
                slide_parts.append(f"### {slide['subtitle']}")

            if slide.get("content"):
                slide_parts.append(slide["content"])

            if slide.get("bullets"):
                for bullet in slide["bullets"]:
                    slide_parts.append(f"- {bullet}")

            if slide.get("image"):
                alt = slide.get("image_alt", "")
                img = slide["image"]
                # Marp image sizing
                width = slide.get("image_width", "")
                if width:
                    slide_parts.append(f"![{alt} w:{width}]({img})")
                else:
                    slide_parts.append(f"![{alt}]({img})")

            if slide.get("code"):
                lang = slide.get("code_lang", "")
                slide_parts.append(f"```{lang}\n{slide['code']}\n```")

            if slide.get("table"):
                table = slide["table"]
                if table.get("headers") and table.get("rows"):
                    headers = table["headers"]
                    slide_parts.append("| " + " | ".join(headers) + " |")
                    slide_parts.append("| " + " | ".join(["---"] * len(headers)) + " |")
                    for row in table["rows"]:
                        slide_parts.append("| " + " | ".join(str(c) for c in row) + " |")

            if slide.get("notes"):
                slide_parts.append(f"\n<!-- {slide['notes']} -->")

            parts.append("\n\n".join(slide_parts))
    else:
        # Use raw markdown content
        raw = inputs.get("markdown", "")
        if raw:
            parts.append(f"\n{raw}")
        else:
            parts.append(f"\n# {title}\n\nCreated with ArcMind + Marp")

    return "\n".join(parts)


def _create_presentation(inputs: dict) -> dict:
    """Create a presentation from Markdown."""
    output_format = inputs.get("format", "pptx")  # html | pdf | pptx | png | jpeg
    markdown = inputs.get("markdown", "")
    theme = inputs.get("theme", "default")
    output_path = inputs.get("output", "")

    # Generate Markdown if slides provided
    if inputs.get("slides") or not markdown:
        markdown = _generate_markdown(inputs)

    # Ensure front-matter has marp: true
    if "marp: true" not in markdown:
        markdown = "---\nmarp: true\n---\n\n" + markdown

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write temp markdown file
    md_filename = f"presentation_{int(time.time())}.md"
    md_path = _OUTPUT_DIR / md_filename

    md_path.write_text(markdown, encoding="utf-8")

    # Determine output path
    ext_map = {"html": ".html", "pdf": ".pdf", "pptx": ".pptx", "png": ".png", "jpeg": ".jpg"}
    ext = ext_map.get(output_format, ".html")

    if not output_path:
        output_path = str(_OUTPUT_DIR / f"presentation_{int(time.time())}{ext}")

    # Build marp command
    args = [str(md_path), "-o", output_path]

    if output_format == "pdf":
        args.append("--pdf")
    elif output_format == "pptx":
        args.append("--pptx")
    elif output_format == "png":
        args.extend(["--images", "png"])
    elif output_format == "jpeg":
        args.extend(["--images", "jpeg"])

    # Additional options
    if inputs.get("allow_local_files"):
        args.append("--allow-local-files")

    ok, stdout, stderr = _run_marp(args)

    if not ok:
        return {"success": False, "error": stderr or stdout, "markdown_path": str(md_path)}

    return {
        "success": True,
        "output": output_path,
        "format": output_format,
        "markdown_path": str(md_path),
        "markdown_preview": markdown[:500],
        "slide_count": markdown.count("---") - 1,  # Subtract front-matter
    }


def _convert_file(inputs: dict) -> dict:
    """Convert an existing Markdown file to a presentation."""
    input_path = inputs.get("input_path", "")
    output_format = inputs.get("format", "pptx")
    output_path = inputs.get("output", "")

    if not input_path:
        return {"success": False, "error": "input_path 為必填"}
    if not Path(input_path).exists():
        return {"success": False, "error": f"檔案不存在: {input_path}"}

    # Read and ensure marp: true
    content = Path(input_path).read_text(encoding="utf-8")
    if "marp: true" not in content:
        # Add marp front-matter
        temp_path = _OUTPUT_DIR / f"temp_{int(time.time())}.md"
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        temp_path.write_text("---\nmarp: true\n---\n\n" + content, encoding="utf-8")
        input_path = str(temp_path)

    ext_map = {"html": ".html", "pdf": ".pdf", "pptx": ".pptx"}
    ext = ext_map.get(output_format, ".html")
    if not output_path:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(_OUTPUT_DIR / f"{Path(input_path).stem}{ext}")

    args = [input_path, "-o", output_path]
    if output_format == "pdf":
        args.append("--pdf")
    elif output_format == "pptx":
        args.append("--pptx")
    if inputs.get("allow_local_files"):
        args.append("--allow-local-files")

    ok, stdout, stderr = _run_marp(args)
    if not ok:
        return {"success": False, "error": stderr or stdout}

    return {"success": True, "output": output_path, "format": output_format}


def _list_themes(inputs: dict) -> dict:
    """List available Marp themes."""
    builtin = [
        {"name": "default", "description": "乾淨的預設主題，白色背景/深色文字"},
        {"name": "gaia", "description": "色彩豐富的主題，支援 lead/invert class"},
        {"name": "uncover", "description": "極簡風格，大字體，適合演說"},
    ]
    # Check for custom themes
    custom = []
    if _TEMPLATE_DIR.exists():
        for css_file in _TEMPLATE_DIR.glob("*.css"):
            custom.append({"name": css_file.stem, "path": str(css_file), "type": "custom"})
    return {"success": True, "builtin_themes": builtin, "custom_themes": custom}


def _preview(inputs: dict) -> dict:
    """Start Marp preview server for a Markdown file."""
    input_path = inputs.get("input_path", "")
    port = int(inputs.get("port", 8080))

    if not input_path:
        return {"success": False, "error": "input_path 為必填"}

    # Start server in background
    cmd_base = _find_marp()
    if cmd_base == "npx":
        cmd = ["npx", "-y", "@marp-team/marp-cli", "-s", input_path, "--port", str(port)]
    else:
        cmd = ["marp", "-s", input_path, "--port", str(port)]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    return {
        "success": True,
        "pid": proc.pid,
        "url": f"http://localhost:{port}",
        "message": f"Marp 預覽伺服器已啟動 (PID: {proc.pid})",
    }


def _save_template(inputs: dict) -> dict:
    """Save a custom CSS theme template."""
    name = inputs.get("name", "")
    css = inputs.get("css", "")
    if not name or not css:
        return {"success": False, "error": "name 和 css 為必填"}
    _TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _TEMPLATE_DIR / f"{name}.css"
    path.write_text(css, encoding="utf-8")
    return {"success": True, "path": str(path), "name": name}


def run(inputs: dict) -> dict:
    """
    Marp presentation skill entry point.

    inputs:
      action: create | convert | list_themes | preview | save_template
      format: html | pdf | pptx | png | jpeg (預設 pptx)
      theme: default | gaia | uncover | <custom>
      slides: list of slide objects (structured input)
      markdown: str (raw Marp markdown)
    """
    action = inputs.get("action", "create")
    handlers = {
        "create": _create_presentation,
        "convert": _convert_file,
        "list_themes": _list_themes,
        "preview": _preview,
        "save_template": _save_template,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}",
                "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[marp] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
