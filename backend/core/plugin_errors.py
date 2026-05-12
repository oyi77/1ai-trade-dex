"""Shared error types for plugin registries."""


class PluginNotFound(KeyError):
    """Raised when a plugin with the given name doesn't exist in the registry."""


class PluginLoadError(RuntimeError):
    """Raised when a plugin fails to load (import error or instantiation failure)."""


class PluginHealthCheckFailed(RuntimeError):
    """Raised when a plugin's health check fails."""


class PluginEnvVarMissing(EnvironmentError):
    """Raised when a plugin requires environment variables that are not set."""


class SandboxViolation(PermissionError):
    """Raised when sandboxed code attempts to access live data or resources."""


class DataSourceError(IOError):
    """Raised when a data source fails to fetch data."""


class MarketProviderError(RuntimeError):
    """Raised when a market provider fails (venue error, order rejection, etc.)."""


class MarketProviderNotFound(KeyError):
    """Raised when a market provider with the given name doesn't exist."""


class MarketProviderHasOpenPositions(RuntimeError):
    """Raised when trying to disable a market provider that has open positions."""


class OrderRejectedError(MarketProviderError):
    """Raised when a venue explicitly rejects an order (e.g., insufficient balance)."""


class VenueUnavailableError(MarketProviderError):
    """Raised when a venue is unreachable or circuit open."""
