import os
import glob

def fix_file(file_path):
    with open(file_path, "r") as f:
        content = f.read()
    content = content.replace("from backend.core.logger import get_logger\nlogger = get_logger(__name__)\n", "from loguru import logger\n")
    content = content.replace("from backend.core.logger import get_logger\nlogger = get_logger(__name__)", "from loguru import logger")
    with open(file_path, "w") as f:
        f.write(content)

files = [
    "backend/core/strategy_allocator.py",
    "backend/markets/providers/limitless_provider.py",
    "backend/monitoring/backends/cloudwatch.py",
    "backend/monitoring/backends/datadog.py",
    "backend/strategies/fingerprint.py",
    "backend/agi/extended_sandbox.py"
]

for file in files:
    if os.path.exists(file):
        fix_file(file)
