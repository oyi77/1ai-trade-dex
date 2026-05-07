import pytest
from unittest.mock import MagicMock, patch

from backend.core.retry import retry


def test_succeeds_first_try():
    call_count = 0

    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1)
    def func():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = func()
    assert result == "ok"
    assert call_count == 1


def test_retries_on_failure_then_succeeds():
    attempts = []

    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1)
    def func():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    with patch("time.sleep"):
        result = func()

    assert result == "ok"
    assert len(attempts) == 3


def test_exhausted_retries_raises():
    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1)
    def func():
        raise ValueError("always fails")

    with patch("time.sleep"):
        with pytest.raises(ValueError, match="always fails"):
            func()


def test_non_retryable_exception_passthrough():
    call_count = 0

    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1, retryable_exceptions=(RuntimeError,))
    def func():
        nonlocal call_count
        call_count += 1
        raise TypeError("not retryable")

    with patch("time.sleep"):
        with pytest.raises(TypeError, match="not retryable"):
            func()

    assert call_count == 1


@pytest.mark.asyncio
async def test_async_function_retry():
    attempts = []

    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1)
    async def func():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "async_ok"

    async def noop(_):
        pass

    with patch("asyncio.sleep", new=noop):
        result = await func()

    assert result == "async_ok"
    assert len(attempts) == 3


def test_jitter_adds_randomness():
    delays = []

    @retry(max_attempts=2, backoff_base=1.0, max_delay=10.0)
    def func():
        raise RuntimeError("fail")

    with patch("time.sleep", side_effect=lambda d: delays.append(d)), \
         patch("random.random", return_value=0.42):
        with pytest.raises(RuntimeError):
            func()

    assert len(delays) == 1
    assert abs(delays[0] - (1.0 + 0.42)) < 1e-9


def test_on_retry_callback():
    callback = MagicMock()
    attempts = []

    @retry(max_attempts=3, backoff_base=0.01, max_delay=0.1, on_retry=callback)
    def func():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("retry me")
        return "done"

    with patch("time.sleep"):
        result = func()

    assert result == "done"
    assert callback.call_count == 2
    for i, call in enumerate(callback.call_args_list, start=1):
        name, attempt, exc = call.args
        assert name == "func"
        assert attempt == i
        assert isinstance(exc, RuntimeError)
