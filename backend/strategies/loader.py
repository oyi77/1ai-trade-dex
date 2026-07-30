"""
Strategy Module Loader for PolyEdge.

Discovers and imports strategy modules to trigger auto-registration
in STRATEGY_REGISTRY. Separated from registry.py to break a circular
import deadlock: registry.py defines STRATEGY_REGISTRY and BaseStrategy;
loader.py imports FROM registry (correct direction) while importing
strategy modules that trigger __init_subclass__ auto-registration.
"""

import importlib
import os

from loguru import logger as log


def _skip_module(module_name: str) -> bool:
    """Return True for utility modules that should not be imported as strategies."""
    _SKIP = frozenset(
        {
            "backend.strategies.base",
            "backend.strategies.registry",
            "backend.strategies.loader",
            "backend.strategies.types_hft",
            "backend.strategies.wallet_sync",
        }
    )
    return module_name in _SKIP


def _discover_flat(package: str, path: str) -> list[str]:
    """Discover single-file modules in a flat package directory."""
    import pkgutil

    modules: list[str] = []
    for finder, name, ispkg in pkgutil.iter_modules([path]):
        if name.startswith("_") or ispkg:
            continue
        full = f"{package}.{name}"
        if not _skip_module(full):
            modules.append(full)
    return modules


def _discover_recursive(package_root: str, path_root: str) -> list[str]:
    """Recursively discover all leaf modules in a package tree."""

    modules: list[str] = []
    seen: set[str] = set()

    def _walk(pkg: str, dir_path: str) -> None:
        if not os.path.isdir(dir_path):
            return
        for entry in sorted(os.listdir(dir_path)):
            child = os.path.join(dir_path, entry)
            if os.path.isdir(child):
                init_file = os.path.join(child, "__init__.py")
                if os.path.isfile(init_file):
                    _walk(f"{pkg}.{entry}", child)
            elif entry.endswith(".py") and not entry.startswith("_"):
                name = entry[:-3]
                full = f"{pkg}.{name}"
                if full not in seen and not _skip_module(full):
                    seen.add(full)
                    modules.append(full)

    _walk(package_root, path_root)
    return modules


def load_all_strategies() -> None:
    """Import all strategy and strategy-module files to trigger auto-registration.

    Discovers modules dynamically by scanning ``backend/strategies/`` (flat)
    and ``backend/modules/`` (recursive). Any Python file that contains a
    ``BaseStrategy`` subclass with a ``name`` attribute will be auto-registered
    in ``STRATEGY_REGISTRY`` via ``__init_subclass__``.

    Dropping a new ``.py`` file into either tree is sufficient — no config
    changes needed.
    """

    # Access registry from the canonical module (loader -> registry, not circular)
    from backend.strategies.registry import STRATEGY_REGISTRY

    strategies_dir = os.path.join(os.path.dirname(__file__))
    modules_dir = os.path.join(os.path.dirname(__file__), "..", "modules")

    candidates: list[str] = []
    candidates.extend(_discover_flat("backend.strategies", strategies_dir))
    candidates.extend(_discover_recursive("backend.modules", modules_dir))

    loaded = 0
    errors = 0
    for module in sorted(candidates):
        try:
            importlib.import_module(module)
            loaded += 1
        except Exception as e:
            log.error(f"Could not load strategy module {module}: {e}", exc_info=True)
            errors += 1

    log.info(
        "Strategy discovery complete: {} loaded, {} errors, {} registered",
        loaded,
        errors,
        len(STRATEGY_REGISTRY),
    )


def load_active_genome_strategies() -> int:
    """Compile and register genome strategies that have StrategyConfig entries.

    Queries StrategyConfig for all genome_* entries, loads the corresponding
    GenomeRegistry record, and compiles via GenomeCompiler so they're available
    to the scheduler during runtime discovery.

    Returns the number of compiled strategies.
    """
    import json

    from backend.strategies.registry import STRATEGY_REGISTRY

    try:
        from backend.application.strategy.genome_compiler import compile_genome
        from backend.domain.genome.models import StrategyGenome
        from backend.models.database import SessionLocal, GenomeRegistry, StrategyConfig
    except ImportError as e:
        log.warning("genome compiler not available ({}), skipping genome strategy loading", e)
        return 0

    db = SessionLocal()
    compiled = 0
    try:
        configs = (
            db.query(StrategyConfig)
            .filter(
                StrategyConfig.strategy_name.like("genome_%"),
                StrategyConfig.enabled.is_(True),
            )
            .all()
        )
        if not configs:
            return 0

        for cfg in configs:
            if cfg.strategy_name in STRATEGY_REGISTRY:
                compiled += 1
                continue  # Already registered

            # Get genome_id from params
            params = cfg.params
            if isinstance(params, str):
                params = json.loads(params)
            genome_id = params.get("genome_id") if isinstance(params, dict) else None

            # Look up genome
            genome_row = (
                db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
                if genome_id
                else None
            )
            if not genome_row:
                log.warning("No GenomeRegistry row for genome_id={} (strategy={})", genome_id, cfg.strategy_name)
                continue

            # Parse chromosomes — the DB stores the full StrategyGenome JSON where
            # actual chromosomes (cognition, perception, risk, execution, meta) are
            # nested under the "chromosomes" key.  Extract them directly.
            chrom_data = (
                json.loads(genome_row.chromosomes_json)
                if isinstance(genome_row.chromosomes_json, str)
                else genome_row.chromosomes_json or {}
            )
            chromosomes = chrom_data.get("chromosomes", chrom_data) if isinstance(chrom_data, dict) else chrom_data

            genome = StrategyGenome(
                genome_id=genome_row.genome_id,
                strategy_name=genome_row.strategy_name,
                archetype=genome_row.archetype,
                version=getattr(genome_row, "version", 1),
                stage="PAPER",
                chromosomes=chromosomes,
            )

            try:
                compile_genome(genome)
                compiled += 1
                log.info("Compiled genome strategy: {} (archetype={})", cfg.strategy_name, genome_row.archetype)
            except Exception as e:
                log.error("Failed to compile genome {}: {}", cfg.strategy_name, e)

    finally:
        db.close()

    log.info("Genome strategy compilation complete: {} compiled", compiled)
    return compiled
