"""Path constants for the project."""

import os

# Project root directory (parent of backend/)
# paths.py is at backend/config/paths.py → need 3 x dirname to reach project root
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Default SQLite database path
DB_PATH = os.path.join(ROOT_DIR, "tradingbot.db")