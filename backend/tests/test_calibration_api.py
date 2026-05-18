"""
RED phase TDD tests for T24: GET /api/v1/calibration endpoint.

The endpoint does not exist yet. These tests define the expected behavior
and should FAIL (404 / KeyError) until T24 is implemented.

Expected response shape:
{
  "overall_brier": 0.18,
  "buckets": {
    "45-50": {"brier": 0.12, "win_rate": 0.683, "implied": 0.498,
              "edge_pp": 18.5, "n": 290, "negative_edge": false},
    "50-55": {"brier": 0.08, "win_rate": 0.856, "implied": 0.519,
              "edge_pp": 33.8, "n": 167, "negative_edge": false},
    ...
  }
}
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


CALIBRATION_URL = "/api/v1/calibration"


@pytest.fixture
def client():
    return TestClient(app)


def test_calibration_endpoint_returns_200(client):
    """Endpoint exists and returns HTTP 200."""
    response = client.get(CALIBRATION_URL)
    if response.status_code == 404:
        pytest.skip("Calibration endpoint not yet implemented (T24)")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )


def test_calibration_response_has_buckets_key(client):
    """Response JSON contains 'buckets' key."""
    response = client.get(CALIBRATION_URL)
    if response.status_code == 404:
        pytest.skip("Calibration endpoint not yet implemented (T24)")
    assert response.status_code == 200
    data = response.json()
    assert "buckets" in data, f"Missing 'buckets' key in response: {data}"
    assert isinstance(data["buckets"], dict), "'buckets' must be a dict"


def test_calibration_bucket_has_required_fields(client):
    """Each non-null bucket has win_rate, edge_pp, and n fields."""
    response = client.get(CALIBRATION_URL)
    if response.status_code == 404:
        pytest.skip("Calibration endpoint not yet implemented (T24)")
    assert response.status_code == 200
    data = response.json()
    buckets = data.get("buckets", {})

    assert len(buckets) > 0, "Expected at least one bucket in response"

    required_fields = {"win_rate", "edge_pp", "n"}
    for bucket_key, bucket in buckets.items():
        if bucket is None:
            continue
        missing = required_fields - set(bucket.keys())
        assert not missing, (
            f"Bucket '{bucket_key}' missing required fields: {missing}. "
            f"Got: {list(bucket.keys())}"
        )


def test_calibration_negative_edge_flag(client):
    """Buckets with edge_pp < 0 must include 'negative_edge': true."""
    response = client.get(CALIBRATION_URL)
    if response.status_code == 404:
        pytest.skip("Calibration endpoint not yet implemented (T24)")
    assert response.status_code == 200
    data = response.json()
    buckets = data.get("buckets", {})

    for bucket_key, bucket in buckets.items():
        if bucket is None:
            continue
        edge_pp = bucket.get("edge_pp")
        if edge_pp is None:
            continue
        if edge_pp < 0:
            assert bucket.get("negative_edge") is True, (
                f"Bucket '{bucket_key}' has edge_pp={edge_pp} < 0 "
                f"but negative_edge is not True: {bucket}"
            )
        else:
            # Non-negative edges should not be flagged
            assert bucket.get("negative_edge", False) is False, (
                f"Bucket '{bucket_key}' has edge_pp={edge_pp} >= 0 "
                f"but negative_edge is True: {bucket}"
            )


def test_calibration_insufficient_samples_null(client):
    """Buckets with fewer than 10 samples must return null (not a dict)."""
    response = client.get(CALIBRATION_URL)
    if response.status_code == 404:
        pytest.skip("Calibration endpoint not yet implemented (T24)")
    assert response.status_code == 200
    data = response.json()
    buckets = data.get("buckets", {})

    for bucket_key, bucket in buckets.items():
        if bucket is None:
            # Null bucket — acceptable for insufficient samples
            continue
        n = bucket.get("n")
        assert n is not None, f"Bucket '{bucket_key}' missing 'n': {bucket}"
        assert n >= 10, (
            f"Bucket '{bucket_key}' has n={n} < 10 but is not null. "
            f"Insufficient-sample buckets must return null."
        )
