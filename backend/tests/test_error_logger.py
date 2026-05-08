"""Test error logging functionality."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, ErrorLog
from backend.core.error_logger import ErrorLogger, ErrorContext, get_error_logger


@pytest.fixture
def test_db():
    """Create in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


@pytest.mark.asyncio
async def test_error_context_creation():
    """Test ErrorContext dataclass creation and serialization."""
    context = ErrorContext(
        timestamp=datetime.now(timezone.utc),
        error_type="ValueError",
        message="Test error",
        endpoint="/api/test",
        method="POST",
        user_id="user123",
        status_code=500,
    )

    assert context.error_type == "ValueError"
    assert context.message == "Test error"
    assert context.endpoint == "/api/test"

    data = context.to_dict()
    assert "timestamp" in data
    assert isinstance(data["timestamp"], str)


@pytest.mark.asyncio
async def test_error_logger_initialization(test_db):
    """Test ErrorLogger initialization."""
    logger = ErrorLogger(test_db)
    assert logger.db_session == test_db
    assert logger._error_counts == {}


@pytest.mark.asyncio
async def test_log_error_persistence(test_db):
    """Test error logging and database persistence."""
    logger = ErrorLogger(test_db)

    try:
        raise ValueError("Test error message")
    except ValueError as e:
        await logger.log_error(
            e,
            endpoint="/api/test",
            method="POST",
            user_id="user123",
            request_id="req-123",
            details={"key": "value"},
        )

    errors = test_db.query(ErrorLog).all()
    assert len(errors) == 1

    error = errors[0]
    assert error.error_type == "ValueError"
    assert error.message == "Test error message"
    assert error.endpoint == "/api/test"
    assert error.method == "POST"
    assert error.user_id == "user123"
    assert error.request_id == "req-123"
    assert error.status_code is None


@pytest.mark.asyncio
async def test_error_rate_calculation(test_db):
    """Test error rate calculation (errors per minute)."""
    logger = ErrorLogger(test_db)

    for i in range(5):
        try:
            raise RuntimeError(f"Error {i}")
        except RuntimeError as e:
            await logger.log_error(e, endpoint="/api/test")

    rate = await logger.get_error_rate()
    assert rate == 5.0


@pytest.mark.asyncio
async def test_error_aggregation(test_db):
    """Test error aggregation by type and endpoint."""
    logger = ErrorLogger(test_db)

    for i in range(3):
        try:
            raise ValueError(f"Value error {i}")
        except ValueError as e:
            await logger.log_error(e, endpoint="/api/endpoint1")

    for i in range(2):
        try:
            raise TypeError(f"Type error {i}")
        except TypeError as e:
            await logger.log_error(e, endpoint="/api/endpoint2")

    aggregation = await logger.get_error_aggregation()

    assert aggregation["by_type"]["ValueError"] == 3
    assert aggregation["by_type"]["TypeError"] == 2
    assert aggregation["by_endpoint"]["/api/endpoint1"] == 3
    assert aggregation["by_endpoint"]["/api/endpoint2"] == 2


@pytest.mark.asyncio
async def test_get_recent_errors(test_db):
    """Test retrieving recent errors."""
    logger = ErrorLogger(test_db)

    for i in range(5):
        try:
            raise RuntimeError(f"Error {i}")
        except RuntimeError as e:
            await logger.log_error(e, endpoint="/api/test")

    recent = await logger.get_recent_errors(limit=3)

    assert len(recent) == 3
    assert all("timestamp" in error for error in recent)
    assert all("error_type" in error for error in recent)
    assert all("message" in error for error in recent)


@pytest.mark.asyncio
async def test_cleanup_old_errors(test_db):
    """Test cleanup of old errors."""
    logger = ErrorLogger(test_db)

    try:
        raise RuntimeError("Test error")
    except RuntimeError as e:
        await logger.log_error(e, endpoint="/api/test")

    initial_count = test_db.query(ErrorLog).count()
    assert initial_count == 1

    deleted = await logger.cleanup_old_errors(days=0)
    assert deleted == 1

    final_count = test_db.query(ErrorLog).count()
    assert final_count == 0


@pytest.mark.asyncio
async def test_get_error_logger_singleton(test_db):
    """Test global error logger singleton."""
    logger1 = get_error_logger(test_db)
    logger2 = get_error_logger()

    assert logger1 is logger2
