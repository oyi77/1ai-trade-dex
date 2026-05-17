#!/usr/bin/env python3
import pytest
pytest.skip(
    "Standalone shutdown script — requires a live backend process and interactive input. "
    "Run directly: python tests/test_shutdown_existing.py",
    allow_module_level=True,
)

import asyncio
import httpx
import signal
import sys
import time
from datetime import datetime

BACKEND_PID = int(os.environ.get("BACKEND_PID", "0"))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8100")


async def make_requests(count: int) -> list:
    """Generate concurrent HTTP requests."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            client.get(f"{BACKEND_URL}/api/health")
            for _ in range(count)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


async def test_shutdown():
    """Test graceful shutdown with active load."""
    print("=" * 70)
    print("GRACEFUL SHUTDOWN TEST - Using Existing Backend")
    print("=" * 70)
    print(f"Backend PID: {BACKEND_PID}")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Time: {datetime.now().isoformat()}")
    print()
    
    try:
        response = await httpx.AsyncClient().get(f"{BACKEND_URL}/api/health", timeout=5.0)
        print(f"✓ Backend is healthy (status: {response.status_code})")
    except Exception as e:
        print(f"❌ Backend not responding: {e}")
        return 1
    
    print("\nTest Steps:")
    print("1. Generate 10 concurrent requests")
    print("2. Send SIGTERM to backend")
    print("3. Monitor shutdown sequence")
    print("4. Verify exit code and timing")
    print()
    
    input("Press ENTER to start test (this will shutdown the backend)...")
    
    print("\n1. Starting 10 concurrent requests...")
    request_task = asyncio.create_task(make_requests(10))
    
    await asyncio.sleep(1.0)
    
    print("2. Sending SIGTERM signal...")
    shutdown_start = time.time()
    
    try:
        import os
        os.kill(BACKEND_PID, signal.SIGTERM)
        print(f"   ✓ SIGTERM sent to PID {BACKEND_PID}")
    except ProcessLookupError:
        print(f"   ❌ Process {BACKEND_PID} not found")
        return 1
    
    print("3. Waiting for requests to complete...")
    results = await request_task
    
    completed = sum(1 for r in results if not isinstance(r, Exception) and r.status_code == 200)
    failed = len(results) - completed
    
    print(f"   - Completed: {completed}/{len(results)}")
    print(f"   - Failed: {failed}/{len(results)}")
    
    print("4. Monitoring process exit...")
    max_wait = 30
    exit_code = None
    
    for i in range(max_wait):
        try:
            import os
            os.kill(BACKEND_PID, 0)
            await asyncio.sleep(1.0)
        except ProcessLookupError:
            shutdown_time = time.time() - shutdown_start
            print(f"   ✓ Process exited after {shutdown_time:.1f}s")
            exit_code = 0
            break
    
    if exit_code is None:
        shutdown_time = time.time() - shutdown_start
        print(f"   ⚠ Process still running after {shutdown_time:.1f}s")
        exit_code = -1
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Requests completed: {completed}/{len(results)}")
    print(f"Shutdown time: {shutdown_time:.1f}s")
    print(f"Exit code: {exit_code}")
    print()
    
    if exit_code == 0 and shutdown_time < 30 and completed > 0:
        print("✅ TEST PASSED")
        return 0
    else:
        print("❌ TEST FAILED")
        if exit_code != 0:
            print(f"   - Exit code: {exit_code} (expected 0)")
        if shutdown_time >= 30:
            print(f"   - Shutdown time: {shutdown_time:.1f}s >= 30s")
        if completed == 0:
            print("   - No requests completed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_shutdown())
    sys.exit(exit_code)
