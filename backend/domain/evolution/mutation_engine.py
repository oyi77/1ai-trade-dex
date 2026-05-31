import random
from typing import Tuple, List, Dict, Any
from uuid import uuid4

from loguru import logger

from backend.domain.genome.models import StrategyGenome, FitnessMetrics
from pydantic import BaseModel


def normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to [0, 1] range."""
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def tweak_random_numeric_gene(
    genome: StrategyGenome, sigma: float = 0.20
) -> Tuple[str, float]:
    """Randomly tweak a numeric gene by ±sigma%."""
    # Find all numeric fields in the genome
    numeric_fields = []

    # Helper to traverse nested structures
    def find_numeric_fields(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_fields.append((new_path, value))
                elif isinstance(value, (dict, BaseModel)):
                    find_numeric_fields(value, new_path)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        find_numeric_fields(item, f"{new_path}[{i}]")
        elif hasattr(obj, "__dict__"):
            for key, value in obj.__dict__.items():
                new_path = f"{path}.{key}" if path else key
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_fields.append((new_path, value))
                elif isinstance(value, (dict, BaseModel)):
                    find_numeric_fields(value, new_path)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        find_numeric_fields(item, f"{new_path}[{i}]")

    # Search through chromosomes
    for chromo_name, chromosome in genome.chromosomes.items():
        find_numeric_fields(chromosome, f"chromosomes.{chromo_name}")

    if not numeric_fields:
        return "", 0.0

    # Select a random numeric field
    field_path, current_value = random.choice(numeric_fields)

    # Apply tweak
    if isinstance(current_value, int):
        new_value = int(current_value * (1 + random.uniform(-sigma, sigma)))
    else:
        new_value = current_value * (1 + random.uniform(-sigma, sigma))

    return field_path, new_value


def swap_indicator(
    genome: StrategyGenome, weighted_by_regime: str = "neutral"
) -> Tuple[str, str]:
    """Swap one indicator for a regime-appropriate alternative."""
    # Common indicators by regime
    regime_indicators = {
        "trending": ["ema_crossover", "macd", "adx", "price_momentum"],
        "mean_reverting": ["rsi", "bolinger_bands", "stochastic_oscillator", "z_score"],
        "volatile": ["atr", "true_range", "volatility_rank", "vix_futures_basis"],
        "neutral": [
            "orderbook_imbalance",
            "spread_compression",
            "volume_spike",
            "price_velocity",
        ],
    }

    # Get current indicators from entry conditions
    current_indicators = []
    if "cognition" in genome.chromosomes:
        for condition in genome.chromosomes["cognition"].entry_logic.conditions:
            current_indicators.append(condition.indicator)

    if not current_indicators:
        current_indicators = ["rsi"]

    # Select regime-appropriate indicators
    available_indicators = regime_indicators.get(
        weighted_by_regime, regime_indicators["neutral"]
    )

    # Choose a random indicator to replace
    old_indicator = random.choice(current_indicators) if current_indicators else "rsi"

    # Choose a new indicator (different from old)
    new_indicator = random.choice(
        [i for i in available_indicators if i != old_indicator]
    )

    return old_indicator, new_indicator


def shift_timeframe(
    genome: StrategyGenome, current_volatility: float = 1.0
) -> Tuple[str, str]:
    """Shift timeframes based on current volatility."""
    _timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

    # Higher volatility = shorter timeframes
    if current_volatility > 1.5:
        preferred = ["1m", "5m"]
    elif current_volatility < 0.7:
        preferred = ["1h", "4h", "1d"]
    else:
        preferred = ["5m", "15m", "30m"]

    perception = genome.chromosomes.get("perception")
    if perception:
        current_tfs = (
            perception.timeframes if hasattr(perception, "timeframes") else ["5m"]
        )
    else:
        current_tfs = ["5m"]

    old_tf = random.choice(current_tfs) if current_tfs else "5m"
    new_tf = random.choice(preferred)

    return old_tf, new_tf


def reassign_risk_model(
    genome: StrategyGenome, drawdown_history: List[float] = None
) -> Tuple[str, str]:
    """Reassign risk model based on drawdown history."""
    risk_models = [
        "kelly_fraction",
        "fixed_fraction",
        "volatility_targeted",
        "optimal_f",
    ]

    # If high drawdowns, prefer more conservative models
    if drawdown_history and any(d > 0.2 for d in drawdown_history):
        preferred = ["fixed_fraction", "volatility_targeted"]
    else:
        preferred = risk_models

    risk_chromo = genome.chromosomes.get("risk")
    if risk_chromo:
        current_model = (
            risk_chromo.position_sizing_model
            if hasattr(risk_chromo, "position_sizing_model")
            else "kelly_fraction"
        )
    else:
        current_model = "kelly_fraction"

    new_model = random.choice([m for m in preferred if m != current_model])

    return current_model, new_model


def synthesize_novel_chromosome(market_regime: str) -> Dict[str, Any]:
    """Create a completely novel chromosome (placeholder)."""
    # This would be enhanced with actual regime-specific logic
    if market_regime == "trending":
        return {
            "type": "momentum_detector",
            "indicators": ["ema_crossover", "adx"],
            "timeframes": ["15m", "1h"],
        }
    else:
        return {
            "type": "mean_reversion",
            "indicators": ["rsi", "bolinger_bands"],
            "timeframes": ["5m", "15m"],
        }


def force_mutate_chromosome(
    genome: StrategyGenome, chromosome_name: str
) -> Dict[str, Any]:
    """Force mutate a specific chromosome."""
    chromosome = genome.chromosomes.get(chromosome_name)
    if not chromosome:
        return {"error": "chromosome_not_found"}

    # Apply multiple tweaks to this chromosome
    if chromosome_name == "perception":
        return {
            "action": "timeframe_shift",
            "old": chromosome.get("timeframes", ["5m"]),
            "new": shift_timeframe(genome)[1],
        }
    elif chromosome_name == "cognition":
        return {
            "action": "indicator_swap",
            "old": swap_indicator(genome)[0],
            "new": swap_indicator(genome)[1],
        }
    elif chromosome_name == "risk":
        return {
            "action": "risk_model_change",
            "old": chromosome.get("position_sizing_model", "kelly_fraction"),
            "new": reassign_risk_model(genome)[1],
        }
    else:
        return {
            "action": "hyperparameter_tweak",
            "gene": "mutation_rate",
            "new_value": random.uniform(0.01, 0.50),
        }


def apply_mutations(genome: StrategyGenome, mutations: List[dict]) -> StrategyGenome:
    """Apply a list of mutations to create a new genome."""
    # Create a proper copy with new UUID
    genome_data = genome.model_dump()
    genome_data["genome_id"] = str(uuid4())

    # Reconstruct chromosomes as proper Pydantic objects
    chromo_data = genome_data["chromosomes"]
    from backend.domain.genome.models import (
        PerceptionChromosome,
        CognitionChromosome,
        ExecutionChromosome,
        RiskChromosome,
        MetaChromosome,
    )

    reconstructed_chromos = {}
    for name, chromo_dict in chromo_data.items():
        if name == "perception":
            reconstructed_chromos[name] = PerceptionChromosome(**chromo_dict)
        elif name == "cognition":
            reconstructed_chromos[name] = CognitionChromosome(**chromo_dict)
        elif name == "execution":
            reconstructed_chromos[name] = ExecutionChromosome(**chromo_dict)
        elif name == "risk":
            reconstructed_chromos[name] = RiskChromosome(**chromo_dict)
        elif name == "meta":
            reconstructed_chromos[name] = MetaChromosome(**chromo_dict)
        else:
            reconstructed_chromos[name] = chromo_dict

    genome_data["chromosomes"] = reconstructed_chromos
    new_genome = StrategyGenome(**genome_data)

    for mutation in mutations:
        mut_type = mutation.get("type")

        if mut_type == "hyperparameter":
            # Parse field path and set new value
            field_path = mutation["gene"]
            new_value = mutation["new_value"]

            # Navigate to the field
            parts = field_path.split(".")
            obj = new_genome

            try:
                for part in parts[:-1]:
                    if part.startswith("chromosomes."):
                        chromo_name = part.replace("chromosomes.", "")
                        obj = obj.chromosomes[chromo_name]
                    elif "[" in part and "]" in part:
                        # Handle list indices
                        list_name = part.split("[")[0]
                        index = int(part.split("[")[1].split("]")[0])
                        obj = (
                            getattr(obj, list_name, [])[index]
                            if hasattr(obj, list_name)
                            else obj[list_name][index]
                        )
                    else:
                        obj = (
                            getattr(obj, part, {})
                            if hasattr(obj, part)
                            else obj.get(part, {})
                        )

                # Set the final value
                final_field = parts[-1]
                if hasattr(obj, final_field):
                    setattr(obj, final_field, new_value)
                elif isinstance(obj, dict) and final_field in obj:
                    obj[final_field] = new_value
            except (KeyError, IndexError, AttributeError):
                logger.debug("mutation_engine: failed to apply hyperparameter tweak")

        elif mut_type == "indicator_swap":
            if "cognition" in new_genome.chromosomes:
                cognition_chromo = new_genome.chromosomes["cognition"]
                if (
                    hasattr(cognition_chromo, "entry_logic")
                    and cognition_chromo.entry_logic
                ):
                    for condition in cognition_chromo.entry_logic.conditions:
                        if condition.indicator == mutation["old"]:
                            condition.indicator = mutation["new"]

        elif mut_type == "timeframe_shift":
            if "perception" in new_genome.chromosomes:
                perception_chromo = new_genome.chromosomes["perception"]
                if hasattr(perception_chromo, "timeframes"):
                    timeframes = perception_chromo.timeframes
                    if mutation["old"] in timeframes:
                        index = timeframes.index(mutation["old"])
                        timeframes[index] = mutation["new"]

        elif mut_type == "risk_model":
            # Change risk model
            if "risk" in new_genome.chromosomes:
                risk_chromo = new_genome.chromosomes["risk"]
                if hasattr(risk_chromo, "position_sizing_model"):
                    risk_chromo.position_sizing_model = mutation["new"]

        elif mut_type == "chromosome_addition":
            # Add new chromosome
            new_chromo_name = f"novel_{len(new_genome.chromosomes)}"
            new_genome.chromosomes[new_chromo_name] = mutation["chromosome"]

        elif mut_type == "targeted":
            # Apply targeted mutation
            chromo_name = mutation["chromosome"]
            if chromo_name in new_genome.chromosomes:
                if "gene" in mutation:
                    setattr(
                        new_genome.chromosomes[chromo_name],
                        mutation["gene"],
                        mutation["new_value"],
                    )

    return new_genome


def mutate_genome(
    genome: StrategyGenome, market_regime: str = "neutral", fitness_score: float = 0.5
) -> Tuple[StrategyGenome, List[dict]]:
    """
    Applies stochastic mutations to a genome.
    Mutation rate is adaptive: losing strategies mutate more (exploration),
    winning strategies mutate less (exploitation).
    """
    meta_chromo = genome.chromosomes.get("meta")
    if meta_chromo and hasattr(meta_chromo, "mutation_rate"):
        base_rate = meta_chromo.mutation_rate
    else:
        base_rate = 0.10

    # Adaptive mutation pressure
    if fitness_score < 0.30:
        effective_rate = min(base_rate * 2.0, 0.50)  # More exploration
    elif fitness_score > 0.80:
        effective_rate = max(base_rate * 0.5, 0.01)  # Exploit the edge
    else:
        effective_rate = base_rate

    # Override: if forensics feedback set a target chromosome, double its mutation rate
    targeted_chromosome = None
    meta_chromo = genome.chromosomes.get("meta")
    if meta_chromo and hasattr(meta_chromo, "next_mutation_target"):
        targeted_chromosome = meta_chromo.next_mutation_target

    mutations = []

    # Type 1: Hyperparameter tweak (±10-30%) — most common
    if random.random() < effective_rate:
        gene, new_value = tweak_random_numeric_gene(genome, sigma=0.20)
        if gene:  # Only add if valid gene found
            mutations.append(
                {"type": "hyperparameter", "gene": gene, "new_value": new_value}
            )

    # Type 2: Indicator swap — swap one signal input for a regime-appropriate one
    if random.random() < effective_rate * 0.70:
        old, new = swap_indicator(genome, weighted_by_regime=market_regime)
        mutations.append({"type": "indicator_swap", "old": old, "new": new})

    # Type 3: Timeframe shift — adapt to current volatility
    if random.random() < effective_rate * 0.50:
        # E-132: Use actual volatility from genome if available, not hardcoded 1.0
        actual_vol = 1.0
        risk_chromo = genome.chromosomes.get("risk")
        if risk_chromo:
            actual_vol = getattr(risk_chromo, "volatility_target", 1.0)
        old, new = shift_timeframe(genome, current_volatility=actual_vol)
        mutations.append({"type": "timeframe_shift", "old": old, "new": new})

    # Type 4: Risk model reassignment — based on drawdown history
    if random.random() < effective_rate * 0.30:
        # E-131: Use actual drawdown from genome fitness, not hardcoded
        actual_drawdown = []
        fitness = getattr(genome, "fitness_metrics", None)
        if fitness:
            dd = getattr(fitness, "max_drawdown_pct", 0.0)
            actual_drawdown = [dd] if dd else [0.1, 0.05, 0.15]
        else:
            actual_drawdown = [0.1, 0.05, 0.15]
        old, new = reassign_risk_model(genome, drawdown_history=actual_drawdown)
        mutations.append({"type": "risk_model", "old": old, "new": new})

    # Type 5: Chromosome addition — rare, high-impact, regime-informed
    if random.random() < effective_rate * 0.10:
        new_chromosome = synthesize_novel_chromosome(market_regime)
        mutations.append({"type": "chromosome_addition", "chromosome": new_chromosome})

    # Apply targeted chromosome boost if set by forensics
    if targeted_chromosome and random.random() < effective_rate:
        targeted_mutation = force_mutate_chromosome(genome, targeted_chromosome)
        mutations.append(
            {"type": "targeted", "chromosome": targeted_chromosome, **targeted_mutation}
        )

    new_genome = apply_mutations(genome, mutations)
    # Only set lineage if it's not already set (e.g., for crossover children)
    if new_genome.lineage.creator != "crossover":
        new_genome.lineage.parent_genome_ids = [genome.genome_id]
        new_genome.lineage.generation = genome.lineage.generation + 1
        new_genome.lineage.creator = "mutation"
    new_genome.stage = "DRAFT"  # All mutants start from DRAFT
    new_genome.fitness_metrics = FitnessMetrics()  # Reset metrics

    return new_genome, mutations
