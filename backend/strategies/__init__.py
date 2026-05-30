# Auto-import all strategies to trigger BaseStrategy.__init_subclass__ registration
from backend.strategies.market_maker import MarketMakerStrategy  # noqa: F401
from backend.strategies.copy_trader_strategy import CopyTraderStrategy  # noqa: F401
from backend.strategies.cross_platform_arb import CrossPlatformArbStrategy  # noqa: F401
from backend.strategies.crypto_oracle import CryptoOracleStrategy  # noqa: F401
from backend.strategies.line_movement_detector import LineMovementDetectorStrategy  # noqa: F401
from backend.strategies.cex_pm_leadlag import CexPmLeadLagStrategy  # noqa: F401
from backend.strategies.bond_scanner import BondScannerStrategy  # noqa: F401
from backend.strategies.longshot_bias import LongshotBiasStrategy  # noqa: F401
from backend.strategies.negrisk_strategy import NegRiskStrategy  # noqa: F401
from backend.strategies.probability_arb import ProbabilityArb  # noqa: F401
