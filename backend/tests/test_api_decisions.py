"""Tests for /api/v1/decisions list, filter, and export endpoints."""

from backend.config import settings


class TestDecisionsList:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_decisions_returns_200(self, client):
        resp = client.get("/api/v1/decisions")
        assert resp.status_code == 200

    def test_decisions_has_items_and_total(self, client):
        resp = client.get("/api/v1/decisions")
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_decisions_items_is_list(self, client):
        resp = client.get("/api/v1/decisions")
        data = resp.json()
        assert isinstance(data["items"], list)

    def test_decisions_total_is_int(self, client):
        resp = client.get("/api/v1/decisions")
        data = resp.json()
        assert isinstance(data["total"], int)

    def test_decisions_filter_by_strategy(self, client, db):
        """Seed a decision and filter by strategy."""
        from backend.models.database import DecisionLog

        # Seed a record
        rec = DecisionLog(
            strategy="copy_trader",
            market_ticker="TEST-MARKET",
            decision="BUY",
            confidence=0.7,
            reason="test",
        )
        db.add(rec)
        db.commit()

        resp = client.get("/api/v1/decisions?strategy=copy_trader")
        data = resp.json()
        assert resp.status_code == 200
        # All returned items belong to copy_trader
        for item in data["items"]:
            assert item["strategy"] == "copy_trader"

    def test_decisions_filter_by_decision(self, client, db):
        """Filter by decision type BUY returns only BUY decisions."""

        resp = client.get("/api/v1/decisions?decision=BUY")
        data = resp.json()
        assert resp.status_code == 200
        for item in data["items"]:
            assert item["decision"] == "BUY"

    def test_decisions_filter_nonexistent_strategy(self, client):
        """Filtering by a nonexistent strategy returns empty items."""
        resp = client.get("/api/v1/decisions?strategy=nonexistent_xyz_123")
        data = resp.json()
        assert resp.status_code == 200
        assert data["total"] == 0
        assert data["items"] == []


class TestDecisionsExport:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_export_returns_200(self, client):
        resp = client.get("/api/v1/decisions/export")
        assert resp.status_code == 200

    def test_export_content_type_ndjson(self, client):
        resp = client.get("/api/v1/decisions/export")
        assert "ndjson" in resp.headers.get("content-type", "")

    def test_export_disposition_header(self, client):
        resp = client.get("/api/v1/decisions/export")
        disposition = resp.headers.get("content-disposition", "")
        assert "decisions.jsonl" in disposition


class TestDecisionsSignalData:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_list_includes_signal_data(self, client, db):
        from backend.models.database import DecisionLog
        import json

        transcript = {
            "debate_transcript": {
                "bull_arguments": [{"stance": "bull", "round": 1, "probability": 0.7}],
                "bear_arguments": [],
                "judge": {"consensus_probability": 0.65, "confidence": 0.8},
                "rounds_completed": 1,
                "latency_ms": 100.0,
            },
            "market_question": "Test?",
            "market_price": 0.5,
            "data_sources": ["order_book", "market_data"],
        }
        rec = DecisionLog(
            strategy="general_market_scanner",
            market_ticker="SIG-DATA-TEST",
            decision="BUY",
            confidence=0.8,
            reason="test signal_data",
            signal_data=json.dumps(transcript),
        )
        db.add(rec)
        db.commit()

        resp = client.get("/api/v1/decisions?market=SIG-DATA-TEST")
        data = resp.json()
        assert resp.status_code == 200
        assert len(data["items"]) >= 1
        item = next(i for i in data["items"] if i["market_ticker"] == "SIG-DATA-TEST")
        assert item["signal_data"] is not None
        assert "debate_transcript" in item["signal_data"]
        assert item["signal_data"]["data_sources"] == ["order_book", "market_data"]

    def test_list_signal_data_null_when_empty(self, client, db):
        from backend.models.database import DecisionLog

        rec = DecisionLog(
            strategy="general_market_scanner",
            market_ticker="NO-SIGNAL-TEST",
            decision="BUY",
            confidence=0.5,
            reason="no signal data",
            signal_data=None,
        )
        db.add(rec)
        db.commit()

        resp = client.get("/api/v1/decisions?market=NO-SIGNAL-TEST")
        data = resp.json()
        assert resp.status_code == 200
        assert len(data["items"]) >= 1
        item = next(i for i in data["items"] if i["market_ticker"] == "NO-SIGNAL-TEST")
        assert item["signal_data"] is None
