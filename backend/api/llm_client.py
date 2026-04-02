from __future__ import annotations

import time
from typing import Any

import requests

from backend.logging_manager import get_logger


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
        self.logger = get_logger("system")

    def get_response(self, messages: list[dict[str, str]]) -> str:
        if not self.url or not self.model:
            raise LLMClientError("API 配置不完整：缺少 URL 或 model")
        if self.timeout <= 0:
            raise LLMClientError("API 配置错误：timeout 必须大于 0")

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
                self.logger.debug(
                    "llm_request_started attempt=%s/%s url=%s model=%s timeout=%s",
                    attempt,
                    self.max_retries,
                    self.url,
                    self.model,
                    self.timeout,
                )
                response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices:
                    raise LLMClientError(f"LLM 响应结构异常：缺少 choices，响应={str(data)[:1000]}")

                first_choice = choices[0]
                if not isinstance(first_choice, dict):
                    raise LLMClientError(f"LLM 响应结构异常：choices[0] 非对象，响应={str(data)[:1000]}")

                message = first_choice.get("message")
                if not isinstance(message, dict):
                    raise LLMClientError(f"LLM 响应结构异常：缺少 message，响应={str(data)[:1000]}")

                content = message.get("content")
                if not isinstance(content, str):
                    raise LLMClientError(f"LLM 响应结构异常：缺少 content，响应={str(data)[:1000]}")

                self.logger.debug("llm_request_succeeded attempt=%s/%s", attempt, self.max_retries)
                return content
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "llm_request_failed attempt=%s/%s error=%s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(0.6 * attempt)

        self.logger.error("llm_request_exhausted retries=%s last_error=%s", self.max_retries, last_error)
        raise LLMClientError(f"LLM 请求失败: {last_error}")
