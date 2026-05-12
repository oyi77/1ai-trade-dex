import pytest
from backend.core.plugin_errors import (
    PluginNotFound,
    PluginLoadError,
    PluginHealthCheckFailed,
    PluginEnvVarMissing,
    SandboxViolation,
    DataSourceError,
    MarketProviderError,
    MarketProviderNotFound,
    MarketProviderHasOpenPositions,
    OrderRejectedError,
    VenueUnavailableError,
)


class TestPluginNotFound:
    def test_inherits_keyerror(self):
        assert issubclass(PluginNotFound, KeyError)

    def test_exception_message(self):
        exc = PluginNotFound("test_plugin")
        assert "test_plugin" in str(exc)


class TestPluginLoadError:
    def test_inherits_runtimeerror(self):
        assert issubclass(PluginLoadError, RuntimeError)

    def test_exception_message(self):
        exc = PluginLoadError("Failed to load")
        assert "Failed to load" in str(exc)


class TestPluginHealthCheckFailed:
    def test_inherits_runtimeerror(self):
        assert issubclass(PluginHealthCheckFailed, RuntimeError)

    def test_exception_message(self):
        exc = PluginHealthCheckFailed("Health check failed")
        assert "Health check failed" in str(exc)


class TestPluginEnvVarMissing:
    def test_inherits_environmenterror(self):
        assert issubclass(PluginEnvVarMissing, EnvironmentError)

    def test_exception_message(self):
        exc = PluginEnvVarMissing("Missing vars: ['API_KEY']")
        assert "API_KEY" in str(exc)


class TestSandboxViolation:
    def test_inherits_permissionerror(self):
        assert issubclass(SandboxViolation, PermissionError)

    def test_exception_message(self):
        exc = SandboxViolation("Access denied")
        assert "Access denied" in str(exc)


class TestDataSourceError:
    def test_inherits_ioerror(self):
        assert issubclass(DataSourceError, IOError)

    def test_exception_message(self):
        exc = DataSourceError("Data fetch failed")
        assert "Data fetch failed" in str(exc)


class TestMarketProviderError:
    def test_inherits_runtimeerror(self):
        assert issubclass(MarketProviderError, RuntimeError)

    def test_exception_message(self):
        exc = MarketProviderError("Order failed")
        assert "Order failed" in str(exc)


class TestMarketProviderNotFound:
    def test_inherits_keyerror(self):
        assert issubclass(MarketProviderNotFound, KeyError)

    def test_exception_message(self):
        exc = MarketProviderNotFound("venue_not_found")
        assert "venue_not_found" in str(exc)


class TestMarketProviderHasOpenPositions:
    def test_inherits_runtimeerror(self):
        assert issubclass(MarketProviderHasOpenPositions, RuntimeError)

    def test_exception_message(self):
        exc = MarketProviderHasOpenPositions("Has open positions")
        assert "Has open positions" in str(exc)


class TestOrderRejectedError:
    def test_inherits_marketprovidererror(self):
        assert issubclass(OrderRejectedError, MarketProviderError)

    def test_exception_message(self):
        exc = OrderRejectedError("Insufficient balance")
        assert "Insufficient balance" in str(exc)


class TestVenueUnavailableError:
    def test_inherits_marketprovidererror(self):
        assert issubclass(VenueUnavailableError, MarketProviderError)

    def test_exception_message(self):
        exc = VenueUnavailableError("Venue unreachable")
        assert "Venue unreachable" in str(exc)


def test_all_exceptions_inherit_from_base_exception():
    exceptions = [
        PluginNotFound,
        PluginLoadError,
        PluginHealthCheckFailed,
        PluginEnvVarMissing,
        SandboxViolation,
        DataSourceError,
        MarketProviderError,
        MarketProviderNotFound,
        MarketProviderHasOpenPositions,
        OrderRejectedError,
        VenueUnavailableError,
    ]

    for exc in exceptions:
        assert issubclass(exc, Exception)


def test_plugin_env_var_missing_structure():
    exc = PluginEnvVarMissing("Plugin 'test' requires env vars: ['API_KEY', 'SECRET']")
    assert "API_KEY" in str(exc)
    assert "SECRET" in str(exc)


def test_order_rejected_inherits_chain():
    assert issubclass(OrderRejectedError, MarketProviderError)
    assert issubclass(OrderRejectedError, RuntimeError)
    assert issubclass(OrderRejectedError, Exception)


def test_venue_unavailable_inherits_chain():
    assert issubclass(VenueUnavailableError, MarketProviderError)
    assert issubclass(VenueUnavailableError, RuntimeError)
    assert issubclass(VenueUnavailableError, Exception)


def test_plugin_not_found_can_be_caught_as_keyerror():
    try:
        raise PluginNotFound("test")
    except KeyError:
        pass
    else:
        pytest.fail("PluginNotFound should be catchable as KeyError")


def test_market_provider_not_found_can_be_caught_as_keyerror():
    try:
        raise MarketProviderNotFound("test")
    except KeyError:
        pass
    else:
        pytest.fail("MarketProviderNotFound should be catchable as KeyError")


def test_sandbox_violation_can_be_caught_as_permissionerror():
    try:
        raise SandboxViolation("test")
    except PermissionError:
        pass
    else:
        pytest.fail("SandboxViolation should be catchable as PermissionError")


def test_data_source_error_can_be_caught_as_ioerror():
    try:
        raise DataSourceError("test")
    except IOError:
        pass
    else:
        pytest.fail("DataSourceError should be catchable as IOError")


def test_all_modules_can_be_imported():
    from backend.core import plugin_errors
    import backend.core.plugin_errors as pe

    assert hasattr(pe, "PluginNotFound")
    assert hasattr(pe, "PluginLoadError")
    assert hasattr(pe, "PluginHealthCheckFailed")
    assert hasattr(pe, "PluginEnvVarMissing")
    assert hasattr(pe, "SandboxViolation")
    assert hasattr(pe, "DataSourceError")
    assert hasattr(pe, "MarketProviderError")
    assert hasattr(pe, "MarketProviderNotFound")
    assert hasattr(pe, "MarketProviderHasOpenPositions")
    assert hasattr(pe, "OrderRejectedError")
    assert hasattr(pe, "VenueUnavailableError")
