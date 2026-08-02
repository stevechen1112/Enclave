"""
Phase 1 — Gateway Resilience

Timeout、Retry、Circuit Breaker。
確保下游故障不拖垮 Gateway。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"           # 正常
    OPEN = "open"               # 熔斷
    HALF_OPEN = "half_open"     # 半開（探測中）


@dataclass
class CircuitBreaker:
    """
    簡單 Circuit Breaker。

    狀態轉換：
      CLOSED → OPEN：failure_count >= threshold
      OPEN → HALF_OPEN：timeout 後自動進入
      HALF_OPEN → CLOSED：探測成功
      HALF_OPEN → OPEN：探測失敗
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0  # 秒
    half_open_max_requests: int = 3

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_requests: int = 0

    def call(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        timeout: float = 10.0,
    ) -> Coroutine[Any, Any, Any]:
        """包裝非同步呼叫，加入 circuit breaking。"""
        return self._call_async(coro_factory, timeout)

    async def _call_async(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        timeout: float,
    ):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_requests = 0
                logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN")
            else:
                raise CircuitOpenError(self.name)

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_requests >= self.half_open_max_requests:
                raise CircuitOpenError(self.name)
            self.half_open_requests += 1

        try:
            result = await asyncio.wait_for(coro_factory(), timeout=timeout)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info(f"Circuit {self.name}: HALF_OPEN → CLOSED")
        self.failure_count = 0

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit {self.name}: CLOSED → OPEN (failures={self.failure_count})")

    # ── 簡化 API（供 Adapter 直接使用）────────────────────────────────

    def allow_request(self) -> bool:
        """檢查是否允許請求通過。"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_requests = 0
                logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN")
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_requests >= self.half_open_max_requests:
                return False
            self.half_open_requests += 1
            return True
        return True

    def record_success(self):
        """記錄成功，重置 failure count。"""
        self._on_success()

    def record_failure(self):
        """記錄失敗，可能觸發熔斷。"""
        self._on_failure()


class CircuitOpenError(Exception):
    """Circuit breaker 開啟時拋出。"""
    def __init__(self, circuit_name: str):
        super().__init__(f"Circuit breaker '{circuit_name}' is OPEN")
        self.circuit_name = circuit_name


@dataclass
class RetryConfig:
    """重試配置。"""
    max_retries: int = 3
    base_delay: float = 1.0      # 秒
    max_delay: float = 30.0      # 秒
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple = (asyncio.TimeoutError, ConnectionError)


async def with_retry(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    config: RetryConfig = RetryConfig(),
    circuit: Optional[CircuitBreaker] = None,
) -> Any:
    """
    帶重試的非同步呼叫。

    Args:
        coro_factory: 非同步函數工廠（每次重試重新建立）
        config: 重試配置
        circuit: 可選的 Circuit Breaker

    Returns:
        函數回傳值

    Raises:
        最後一次失敗的例外
    """
    last_exc = None
    for attempt in range(config.max_retries + 1):
        try:
            if circuit:
                return await circuit._call_async(coro_factory, timeout=10.0)
            else:
                return await coro_factory()
        except CircuitOpenError:
            raise
        except config.retryable_exceptions as exc:
            last_exc = exc
            if attempt < config.max_retries:
                delay = min(
                    config.base_delay * (config.backoff_multiplier ** attempt),
                    config.max_delay,
                )
                logger.warning(f"Retry {attempt + 1}/{config.max_retries} after {delay:.1f}s: {exc}")
                await asyncio.sleep(delay)
        except Exception as exc:
            # 不可重試的例外
            raise exc

    raise last_exc  # type: ignore
