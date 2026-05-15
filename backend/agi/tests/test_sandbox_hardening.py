"""Tests for sandbox hardening - escape attempts and resource limit enforcement."""
import os
import pytest
import asyncio
from backend.agi.sandbox.sandbox_manager import SandboxManager


@pytest.mark.asyncio
async def test_file_escape_attempt():
    """Test that sandbox blocks attempts to write outside sandbox dir."""
    manager = SandboxManager()
    dangerous_code = '''
import os
# Try to write outside sandbox
with open("/tmp/escape_test.txt", "w") as f:
    f.write("ESCAPED!")
print("Attempted escape")
'''
    result = await manager.execute_code(dangerous_code)
    # The code is blocked by SandboxValidator (Gate 1) before execution,
    # so it should return as a 'failed' validation result, not necessarily 'error' status.
    assert result.status in ["failed", "error"]
    assert any("Forbidden import" in err for err in result.errors)
    # Verify file was not created
    assert not os.path.exists("/tmp/escape_test.txt")


@pytest.mark.asyncio
async def test_infinite_loop_timeout():
    """Test that infinite loops are killed by timeout."""
    manager = SandboxManager()
    loop_code = '''
while True:
    pass
'''
    result = await manager.execute_code(loop_code)
    assert result.killed
    assert result.status == "error"
    assert "timeout" in result.output.lower()


@pytest.mark.asyncio
async def test_large_memory_allocation():
    """Test that excessive memory allocation is blocked."""
    manager = SandboxManager()
    mem_code = '''
# Try to allocate 300MB (over 200MB limit)
data = bytearray(300 * 1024 * 1024)
print("Allocated")
'''
    result = await manager.execute_code(mem_code)
    assert result.status == "error"
    assert result.killed or "memory" in result.output.lower()


@pytest.mark.asyncio
async def test_cpu_spike_kill():
    """Test that CPU-intensive code is killed."""
    manager = SandboxManager()
    cpu_code = '''
# Burn CPU for more than 1s
def burn():
    x = 0
    while True:
        x += 1
        if x % 1000000 == 0:
            pass

burn()
'''
    result = await manager.execute_code(cpu_code)
    assert result.status == "error"
    assert result.killed


@pytest.mark.asyncio
async def test_safe_code_execution():
    """Test that safe code executes successfully."""
    manager = SandboxManager()
    safe_code = '''
def calculate(x):
    return x * 2

result = calculate(21)
print(f"Result: {result}")
'''
    result = await manager.execute_code(safe_code)
    assert result.status == "passed"
    assert "Result: 42" in result.output
    assert not result.killed
    assert result.cpu_ms > 0


@pytest.mark.asyncio
async def test_network_blocked():
    """Test that network access is blocked."""
    manager = SandboxManager()
    net_code = '''
import urllib.request
try:
    with urllib.request.urlopen("http://example.com", timeout=1) as response:
        print(response.read())
except Exception as e:
    print(f"Network error: {e}")
'''
    result = await manager.execute_code(net_code)
    assert result.status == "error" or "Network error" in result.output


@pytest.mark.asyncio
async def test_resource_limits_enforced():
    """Test that resource limits are enforced."""
    manager = SandboxManager()
    # Try to exceed CPU limit
    cpu_code = '''
import time
start = time.time()
while time.time() - start < 2.5:  # Try to run longer than CPU limit
    pass
print("Done")
'''
    result = await manager.execute_code(cpu_code)
    assert result.status == "error"
    assert result.killed


@pytest.mark.asyncio
async def test_filesystem_isolation():
    """Test that filesystem access is isolated to temp dir."""
    manager = SandboxManager()
    fs_code = '''
import os
# Create a file in sandbox
with open("test_file.txt", "w") as f:
    f.write("isolated")
# Try to read it back
with open("test_file.txt", "r") as f:
    content = f.read()
print(f"Read: {content}")
'''
    result = await manager.execute_code(fs_code)
    assert result.status == "passed"
    assert "Read: isolated" in result.output
