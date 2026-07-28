"""Integration tests for API validation error responses."""

import os
import sys

# Force test isolation — use SQLite in-memory, NOT production PostgreSQL
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Purge cached settings module so the new DATABASE_URL is picked up
for mod in list(sys.modules.keys()):
    if mod.startswith("backend.config"):
        del sys.modules[mod]

import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.auth import require_admin
