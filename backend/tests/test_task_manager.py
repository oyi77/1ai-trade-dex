import asyncio
import pytest
from backend.core.scheduling.task_manager import TaskManager


async def short_task():
    """Task that completes quickly."""
    await asyncio.sleep(0.01)
    return "completed"


async def long_running_task():
    """Task that runs for a long time."""
    try:
        await asyncio.sleep(10)
        return "should_not_complete"
    except asyncio.CancelledError:
        raise


async def failing_task():
    """Task that raises an exception."""
    await asyncio.sleep(0.01)
    raise ValueError("task failed")


async def immediate_task():
    """Task that completes immediately."""
    return "instant"


@pytest.mark.asyncio
async def test_create_task_adds_to_tracking():
    """Test that create_task adds task to tracking set."""
    manager = TaskManager()

    task = await manager.create_task(short_task(), name="test_task")

    assert task in manager.tasks
    assert len(manager.tasks) == 1

    await task
    await asyncio.sleep(0.05)

    assert task not in manager.tasks
    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_create_task_with_name():
    """Test that task names are properly set."""
    manager = TaskManager()

    task = await manager.create_task(short_task(), name="named_task")

    assert task.get_name() == "named_task"

    await task


@pytest.mark.asyncio
async def test_create_task_without_name():
    """Test that tasks without names get default names."""
    manager = TaskManager()

    task = await manager.create_task(short_task())

    assert task.get_name() is not None

    await task


@pytest.mark.asyncio
async def test_task_cleanup_on_completion():
    """Test that completed tasks are automatically removed from tracking."""
    manager = TaskManager()

    task1 = await manager.create_task(short_task(), name="task1")
    task2 = await manager.create_task(short_task(), name="task2")
    task3 = await manager.create_task(short_task(), name="task3")

    assert len(manager.tasks) == 3

    await asyncio.gather(task1, task2, task3)
    await asyncio.sleep(0.05)

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_task_cleanup_on_exception():
    """Test that failed tasks are automatically removed from tracking."""
    manager = TaskManager()

    task = await manager.create_task(failing_task(), name="failing")

    assert len(manager.tasks) == 1

    with pytest.raises(ValueError):
        await task

    await asyncio.sleep(0.05)

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_all_pending_tasks():
    """Test that shutdown cancels all pending tasks."""
    manager = TaskManager()

    task1 = await manager.create_task(long_running_task(), name="long1")
    task2 = await manager.create_task(long_running_task(), name="long2")
    task3 = await manager.create_task(long_running_task(), name="long3")

    assert len(manager.tasks) == 3
    assert not task1.done()
    assert not task2.done()
    assert not task3.done()

    await manager.shutdown()

    assert task1.cancelled()
    assert task2.cancelled()
    assert task3.cancelled()


@pytest.mark.asyncio
async def test_shutdown_with_already_completed_tasks():
    """Test that shutdown handles already-completed tasks gracefully."""
    manager = TaskManager()

    task1 = await manager.create_task(immediate_task(), name="immediate1")
    task2 = await manager.create_task(immediate_task(), name="immediate2")

    await asyncio.gather(task1, task2)
    await asyncio.sleep(0.05)

    await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_with_mixed_task_states():
    """Test shutdown with mix of pending, completed, and failed tasks."""
    manager = TaskManager()

    completed_task = await manager.create_task(immediate_task(), name="completed")
    long_task = await manager.create_task(long_running_task(), name="long")
    failing = await manager.create_task(failing_task(), name="failing")

    await completed_task
    with pytest.raises(ValueError):
        await failing

    await asyncio.sleep(0.05)

    assert len(manager.tasks) == 1
    assert not long_task.done()

    await manager.shutdown()

    assert long_task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_with_no_tasks():
    """Test that shutdown with no tasks doesn't raise errors."""
    manager = TaskManager()

    assert len(manager.tasks) == 0

    await manager.shutdown()

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_waits_for_cancellation():
    """Test that shutdown waits for all tasks to be cancelled."""
    manager = TaskManager()

    task = await manager.create_task(long_running_task(), name="long")

    await manager.shutdown()

    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_multiple_tasks_concurrent_creation():
    """Test creating multiple tasks concurrently."""
    manager = TaskManager()

    tasks = await asyncio.gather(
        manager.create_task(short_task(), name="concurrent1"),
        manager.create_task(short_task(), name="concurrent2"),
        manager.create_task(short_task(), name="concurrent3"),
        manager.create_task(short_task(), name="concurrent4"),
        manager.create_task(short_task(), name="concurrent5"),
    )

    assert len(manager.tasks) == 5

    await asyncio.gather(*tasks)
    await asyncio.sleep(0.05)

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_task_exception_doesnt_affect_other_tasks():
    """Test that one task's exception doesn't affect other tasks."""
    manager = TaskManager()

    task1 = await manager.create_task(short_task(), name="good1")
    task2 = await manager.create_task(failing_task(), name="bad")
    task3 = await manager.create_task(short_task(), name="good2")

    results = await asyncio.gather(task1, task2, task3, return_exceptions=True)

    assert results[0] == "completed"
    assert isinstance(results[1], ValueError)
    assert results[2] == "completed"

    await asyncio.sleep(0.05)

    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_suppresses_cancellation_exceptions():
    """Test that shutdown suppresses CancelledError from tasks."""
    manager = TaskManager()

    await manager.create_task(long_running_task(), name="long1")
    await manager.create_task(long_running_task(), name="long2")

    await manager.shutdown()


@pytest.mark.asyncio
async def test_task_tracking_count_accuracy():
    """Test that task count is accurate throughout lifecycle."""
    manager = TaskManager()

    async def controlled_task(duration: float):
        await asyncio.sleep(duration)
        return "done"

    assert len(manager.tasks) == 0

    task1 = await manager.create_task(controlled_task(0.05), name="task1")
    assert len(manager.tasks) == 1

    task2 = await manager.create_task(controlled_task(0.1), name="task2")
    assert len(manager.tasks) == 2

    task3 = await manager.create_task(controlled_task(0.15), name="task3")
    assert len(manager.tasks) == 3

    await task1
    await asyncio.sleep(0.02)
    assert len(manager.tasks) == 2

    await asyncio.gather(task2, task3)
    await asyncio.sleep(0.02)
    assert len(manager.tasks) == 0


@pytest.mark.asyncio
async def test_create_task_returns_awaitable_task():
    """Test that create_task returns a proper asyncio.Task."""
    manager = TaskManager()

    task = await manager.create_task(short_task(), name="test")

    assert isinstance(task, asyncio.Task)

    result = await task
    assert result == "completed"


@pytest.mark.asyncio
async def test_shutdown_idempotency():
    """Test that calling shutdown multiple times is safe."""
    manager = TaskManager()

    task = await manager.create_task(long_running_task(), name="long")

    await manager.shutdown()
    assert task.cancelled()

    await manager.shutdown()
    await manager.shutdown()
