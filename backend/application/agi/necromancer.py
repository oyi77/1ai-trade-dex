"""Necromancy Analysis — extracts insights from dead genomes.

Wave 9: Meta-Learning Layer — Part 5.3
Weekly analysis of graveyard genomes to identify high-risk genes and legend patterns.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import Counter

from backend.core.event_bus import publish_event


@dataclass
class NecromancyReport:
    """Structured report from necromancy analysis."""
    date: datetime
    death_causes: Dict[str, int]  # Counter of death reasons
    high_risk_genes: List[Dict[str, Any]]  # Overrepresented in dead genomes
    legend_genes: List[Dict[str, Any]]  # Overrepresented in surviving elite strategies
    new_anti_patterns: List[Dict[str, Any]]


def load_graveyard(db) -> List[Dict[str, Any]]:
    """Load genomes from GRAVEYARD stage."""
    # Simplified: in production, query GenomeRegistry for GRAVEYARD stage
    # For now, return empty list
    return []


def load_legends(db) -> List[Dict[str, Any]]:
    """Load elite genomes (LEGEND stage)."""
    # Simplified: in production, query GenomeRegistry for LEGEND stage
    # For now, return empty list
    return []


def find_genes_overrepresented_in(genomes: List[Dict[str, Any]], threshold: float = 0.70) -> List[Dict[str, Any]]:
    """Identify genes present in >threshold fraction of genomes.

    Simplified version: counts chromosome traits across genomes.
    """
    if not genomes:
        return []

    # Count chromosome occurrences
    chromosome_counts = Counter()
    total = len(genomes)

    for genome in genomes:
        chromosomes = genome.get("chromosomes", {})
        for chrom_name, chrom_data in chromosomes.items():
            # Simple trait counting
            if isinstance(chrom_data, dict):
                for trait, value in chrom_data.items():
                    chromosome_counts[f"{chrom_name}.{trait}.{value}"] += 1

    # Find overrepresented genes
    overrepresented = []
    for gene, count in chromosome_counts.items():
        frequency = count / total
        if frequency >= threshold:
            overrepresented.append({
                "gene": gene,
                "frequency": frequency,
                "count": count,
                "total": total
            })

    return sorted(overrepresented, key=lambda x: x["frequency"], reverse=True)


def update_synthesis_priors(prefer: List[Dict[str, Any]], avoid: List[Dict[str, Any]], db) -> None:
    """Update genome synthesis weight table with new priors.

    In production, this updates the SynthesisPrior table.
    For now, publish event for Wave 10 implementation.
    """
    publish_event("synthesis_priors_updated", {
        "prefer": [g["gene"] for g in prefer],
        "avoid": [g["gene"] for g in avoid],
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def generate_anti_patterns(dead_genomes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate anti-pattern rules from common death causes.

    Simplified: creates basic anti-pattern rules.
    """
    if not dead_genomes:
        return []

    # Count death causes
    death_causes = Counter()
    for genome in dead_genomes:
        death_cert = genome.get("death_certificate", {})
        cause = death_cert.get("killer_condition", "unknown")
        death_causes[cause] += 1

    # Generate anti-patterns for top causes
    anti_patterns = []
    for cause, count in death_causes.most_common(3):
        anti_patterns.append({
            "pattern_name": f"anti_{cause}",
            "trigger_condition": cause,
            "action": "suppress",
            "severity": "high" if count > 5 else "medium",
            "count": count
        })

    return anti_patterns


def inject_anti_patterns_into_risk_manager(new_rules: List[Dict[str, Any]]) -> None:
    """Inject anti-patterns into RiskManager.

    In production, this updates RiskManager rules.
    For now, publish event for Wave 10 implementation.
    """
    publish_event("risk_manager_updated", {
        "new_rules": new_rules,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def save_to_knowledge_graph(report: NecromancyReport, db) -> None:
    """Save necromancy report to KnowledgeGraph.

    KnowledgeGraph tables are created in Wave 10.
    For now, publish event as interface.
    """
    publish_event("necromancy_report", {
        "date": report.date.isoformat(),
        "death_causes": report.death_causes,
        "high_risk_genes": report.high_risk_genes,
        "legend_genes": report.legend_genes,
        "new_anti_patterns": report.new_anti_patterns
    })


def run_necromancy_analysis(db) -> NecromancyReport:
    """Run weekly necromancy analysis on graveyard genomes.

    Analyzes all GRAVEYARD genomes to extract:
    1. Death cause distribution
    2. High-risk gene patterns (overrepresented in dead strategies)
    3. Legend gene patterns (overrepresented in surviving elite strategies)
    Then updates synthesis priors so future genomes are born smarter.

    Args:
        db: Database session

    Returns:
        NecromancyReport with analysis results
    """
    # Load data
    dead = load_graveyard(db)
    legends = load_legends(db)

    # Analyze death causes
    death_causes = Counter()
    for genome in dead:
        death_cert = genome.get("death_certificate", {})
        if death_cert:
            death_causes[death_cert.get("killer_condition", "unknown")] += 1

    # Identify overrepresented genes
    high_risk_genes = find_genes_overrepresented_in(dead, threshold=0.70)
    legend_genes = find_genes_overrepresented_in(legends, threshold=0.70)

    update_synthesis_priors(prefer=legend_genes, avoid=high_risk_genes, db=db)

    # Generate anti-patterns
    new_rules = generate_anti_patterns(dead)
    inject_anti_patterns_into_risk_manager(new_rules)

    # Create report
    report = NecromancyReport(
        date=datetime.now(timezone.utc),
        death_causes=dict(death_causes),
        high_risk_genes=high_risk_genes,
        legend_genes=legend_genes,
        new_anti_patterns=new_rules
    )

    # Save to KnowledgeGraph (Wave 10)
    save_to_knowledge_graph(report, db)

    return report
