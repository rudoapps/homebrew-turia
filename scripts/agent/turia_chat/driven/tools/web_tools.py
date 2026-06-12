"""Web tools: web_fetch."""

from __future__ import annotations

import re
from typing import Any, Dict

from .base import BaseToolExecutor, MAX_WEB_CONTENT


class WebToolExecutor(BaseToolExecutor):
    """Handles web-related operations."""

    async def web_fetch(self, inp: Dict[str, Any]) -> str:
        """Fetch a URL and return content as text/markdown."""
        import httpx

        url = inp.get("url", "")
        if not url:
            raise ValueError("Se requiere el parametro 'url'")

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "turia-agent/1.0"})
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "html" in content_type:
                    text = resp.text
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                else:
                    text = resp.text

                if len(text) > MAX_WEB_CONTENT:
                    text = text[:MAX_WEB_CONTENT] + "\n... [truncado]"
                return text
        except Exception as exc:
            return f"Error fetching {url}: {exc}"
