"""
ArcMind 瀏覽器自動化模組
使用 Playwright 驅動瀏覽器，結合 Claude Vision 理解頁面。
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any

from config.settings import settings
from db.schema import BrowserSession_, get_db

logger = logging.getLogger("arcmind.browser")

# Playwright import 延遲，避免未安裝時整個程式崩潰
try:
    from playwright.sync_api import sync_playwright, Browser, Page, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Browser module disabled.")


class BrowserError(Exception):
    pass


class BrowserSession:
    """
    一次瀏覽器 Session：
    - 開啟頁面
    - 執行動作序列
    - 截圖並可選用 Claude Vision 分析
    - 關閉並記錄
    """

    def __init__(self, task_id: int | None = None):
        if not PLAYWRIGHT_AVAILABLE:
            raise BrowserError("Playwright not available. Run: playwright install chromium")

        self.task_id = task_id
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._actions: list[dict] = []
        self._db_id: int | None = None
        self._started = False

    # ── 啟動 / 關閉 ──────────────────────────────────────────────────────────

    def start(self, url: str | None = None) -> "BrowserSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=settings.browser_headless
        )
        self._page = self._browser.new_page()
        self._page.set_default_timeout(settings.browser_timeout)
        self._started = True

        # DB record
        db = next(get_db())
        rec = BrowserSession_(
            task_id=self.task_id,
            url=url,
            status="active",
            actions="[]",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        self._db_id = rec.id

        if url:
            self.navigate(url)
        return self

    def close(self) -> None:
        if self._started:
            try:
                if self._page:
                    self._page.close()
                if self._browser:
                    self._browser.close()
                if self._pw:
                    self._pw.stop()
            except Exception as e:
                logger.warning("Error closing browser: %s", e)
            self._started = False

        self._update_db(status="closed")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ── 動作 ──────────────────────────────────────────────────────────────────

    def navigate(self, url: str) -> "BrowserSession":
        self._ensure_started()
        self._page.goto(url, wait_until="domcontentloaded")
        self._log_action("navigate", {"url": url})
        return self

    def click(self, selector: str) -> "BrowserSession":
        self._ensure_started()
        self._page.click(selector)
        self._log_action("click", {"selector": selector})
        return self

    def fill(self, selector: str, value: str) -> "BrowserSession":
        self._ensure_started()
        self._page.fill(selector, value)
        self._log_action("fill", {"selector": selector, "value": value})
        return self

    def press(self, key: str) -> "BrowserSession":
        self._ensure_started()
        self._page.keyboard.press(key)
        self._log_action("press", {"key": key})
        return self

    def wait_for(self, selector: str, timeout: int | None = None) -> "BrowserSession":
        self._ensure_started()
        self._page.wait_for_selector(selector, timeout=timeout or settings.browser_timeout)
        self._log_action("wait_for", {"selector": selector})
        return self

    def get_text(self, selector: str) -> str:
        self._ensure_started()
        return self._page.inner_text(selector)

    def get_html(self) -> str:
        self._ensure_started()
        return self._page.content()

    def screenshot_b64(self) -> str:
        """截圖並以 base64 回傳"""
        self._ensure_started()
        data = self._page.screenshot()
        return base64.b64encode(data).decode()

    def screenshot_save(self, path: str) -> None:
        self._ensure_started()
        self._page.screenshot(path=path)
        self._log_action("screenshot", {"path": path})

    def eval_js(self, expression: str) -> Any:
        self._ensure_started()
        return self._page.evaluate(expression)

    def current_url(self) -> str:
        self._ensure_started()
        return self._page.url

    def title(self) -> str:
        self._ensure_started()
        return self._page.title()

    # ── Vision 分析（整合 Model Router）─────────────────────────────────────

    def analyze_screenshot(self, question: str) -> str:
        """
        截圖 → Claude Vision → 回傳分析文字。
        需要 model_router 支援 vision。
        """
        from runtime.model_router import model_router

        b64 = self.screenshot_b64()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": question},
                ],
            }
        ]
        resp = model_router.complete(
            prompt="", messages=messages, task_type="browser_vision"
        )
        self._log_action("analyze_screenshot", {"question": question})
        return resp.content

    def find_element_by_description(self, description: str) -> str | None:
        """
        用 Claude Vision 找到符合描述的元素 CSS selector。
        """
        prompt = (
            f"Look at this screenshot. Find the element that matches: '{description}'.\n"
            "Reply with ONLY the CSS selector (e.g., '#submit-btn', '.login-form input[type=email]').\n"
            "If not found, reply with 'NOT_FOUND'."
        )
        result = self.analyze_screenshot(prompt)
        if "NOT_FOUND" in result.upper():
            return None
        return result.strip()

    # ── 內部 ──────────────────────────────────────────────────────────────────

    def _ensure_started(self):
        if not self._started:
            raise BrowserError("Browser session not started. Call start() first.")

    def _log_action(self, action_type: str, params: dict) -> None:
        entry = {
            "type": action_type,
            "params": params,
            "ts": datetime.utcnow().isoformat(),
        }
        self._actions.append(entry)
        self._update_db()

    def _update_db(self, status: str | None = None) -> None:
        if not self._db_id:
            return
        try:
            db = next(get_db())
            rec = db.query(BrowserSession_).filter_by(id=self._db_id).first()
            if rec:
                rec.actions = json.dumps(self._actions)
                if status:
                    rec.status = status
                    if status == "closed":
                        rec.closed_at = datetime.utcnow()
                db.commit()
        except Exception as e:
            logger.warning("Browser DB update failed: %s", e)


class BrowserManager:
    """BrowserSession 工廠，統一管理"""

    def new_session(self, url: str | None = None,
                    task_id: int | None = None) -> BrowserSession:
        if not PLAYWRIGHT_AVAILABLE:
            raise BrowserError("Playwright not available.")
        sess = BrowserSession(task_id=task_id)
        sess.start(url)
        return sess

    def is_available(self) -> bool:
        return PLAYWRIGHT_AVAILABLE


browser_manager = BrowserManager()
