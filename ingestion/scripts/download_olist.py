"""Download the Olist Brazilian E-Commerce dataset from Kaggle into data/raw/.

Authentication: place your Kaggle API token at ~/.kaggle/kaggle.json
(file content: {"username": "<you>", "key": "<api-key>"}).

Run from repo root:
    python ingestion/scripts/download_olist.py
"""
from __future__ import annotations

from pathlib import Path

# The kaggle package authenticates lazily on first API call by reading
# ~/.kaggle/kaggle.json (or KAGGLE_USERNAME / KAGGLE_KEY env vars).
import kaggle

# Public Kaggle dataset slug for Olist Brazilian E-Commerce.
DATASET = "olistbr/brazilian-ecommerce"

# Repo-root/data/raw — gitignored, holds the unzipped CSVs.
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {DATASET} -> {RAW_DIR}")

    # unzip=True extracts the .zip in place and removes the archive, leaving
    # only the CSV files in RAW_DIR. quiet=False keeps the progress bar visible.
    kaggle.api.dataset_download_files(
        DATASET,
        path=str(RAW_DIR),
        unzip=True,
        quiet=False,
    )

    csv_count = len(list(RAW_DIR.glob("*.csv")))
    print(f"[DONE] {csv_count} CSV files in {RAW_DIR}")


if __name__ == "__main__":
    main()
