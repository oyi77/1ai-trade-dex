"""Ingest HuggingFace datasets and save as Parquet.

Downloads a HuggingFace dataset using huggingface_hub and saves it locally
as Parquet files for offline use in backtesting and analysis.

Usage:
    python -m backend.scripts.ingest_hf_dataset
    python -m backend.scripts.ingest_hf_dataset --dataset SII-WANGZJ/Polymarket_data --output data/hf/
"""

import argparse
import os
from pathlib import Path

from loguru import logger


def ingest_dataset(
    dataset_id: str = "SII-WANGZJ/Polymarket_data",
    output_dir: str = "data/hf",
    split: str = "train",
) -> Path:
    """Download a HuggingFace dataset and save as Parquet.

    Args:
        dataset_id: HuggingFace dataset identifier.
        output_dir: Local directory to save Parquet files.
        split: Dataset split to download (default: 'train').

    Returns:
        Path to the saved Parquet file.
    """
    try:
        from huggingface_hub import hf_hub_download
        import pyarrow.parquet as pq
    except ImportError as e:
        logger.error("Missing dependency: {}. Install with: pip install huggingface_hub pyarrow", e)
        raise

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    safe_name = dataset_id.replace("/", "_")
    parquet_path = output_path / f"{safe_name}_{split}.parquet"

    logger.info("Downloading dataset: {} (split={})", dataset_id, split)

    try:
        # Try downloading Parquet directly if available
        downloaded = hf_hub_download(
            repo_id=dataset_id,
            filename=f"data/{split}-*.parquet",
            repo_type="dataset",
            local_dir=str(output_path / "raw"),
        )
        logger.info("Downloaded raw Parquet to: {}", downloaded)

        # Read and consolidate
        table = pq.read_table(downloaded)
        pq.write_table(table, str(parquet_path))
        logger.info("Saved consolidated Parquet: {} ({} rows)", parquet_path, table.num_rows)

    except Exception:
        # Fallback: use datasets library to load and convert
        logger.info("Direct Parquet download failed, falling back to datasets library")
        try:
            from datasets import load_dataset

            ds = load_dataset(dataset_id, split=split)
            table = ds.to_arrow()
            pq.write_table(table, str(parquet_path))
            logger.info("Saved via datasets lib: {} ({} rows)", parquet_path, table.num_rows)
        except Exception as e:
            logger.error("Dataset ingestion failed: {}", e)
            raise

    return parquet_path


def main():
    parser = argparse.ArgumentParser(description="Ingest HuggingFace dataset as Parquet")
    parser.add_argument("--dataset", default="SII-WANGZJ/Polymarket_data", help="HF dataset ID")
    parser.add_argument("--output", default="data/hf", help="Output directory")
    parser.add_argument("--split", default="train", help="Dataset split")
    args = parser.parse_args()

    path = ingest_dataset(args.dataset, args.output, args.split)
    print(f"Dataset saved to: {path}")


if __name__ == "__main__":
    main()
