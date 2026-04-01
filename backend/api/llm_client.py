from __future__ import annotations

import time
from typing import Any

import requests


class LLMClientError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        temperature: float,
        timeout: int,
        max_retries: int,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))

    def get_response(self, messages: list[dict[str, str]]) -> str:
        if not self.url or not self.model:
            raise LLMClientError("API 配置不完整：缺少 URL 或 model")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.6 * attempt)

        raise LLMClientError(f"LLM 请求失败: {last_error}")
