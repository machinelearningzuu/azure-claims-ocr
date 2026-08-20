"""Central place for configuration.

Two kinds of configuration, two homes:

  * Secrets and environment-specific values (endpoints, keys, DB URLs,
    thresholds) come from environment variables, loaded from `.env`.
  * The field schema (what to extract per document template, what is
    mandatory) lives in config/templates.yaml and is loaded by app/models.py.

Nothing is hard-coded in Python.
"""

import os

from dotenv import load_dotenv

load_dotenv()

AZURE_DOCINTEL_ENDPOINT = os.getenv("AZURE_DOCINTEL_ENDPOINT", "")
AZURE_DOCINTEL_KEY = os.getenv("AZURE_DOCINTEL_KEY", "")

# Fields below this confidence get flagged in the review UI. The human still
# reviews every field; the threshold only decides which ones get a warning.
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))

# Layer 1: sqlite:///./claims.db. Layer 2 swaps this to Azure PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./claims.db")


def require_azure_ocr_config() -> None:
    """Fail fast at startup with a clear message instead of a confusing
    SDK error on the first upload."""
    if not AZURE_DOCINTEL_ENDPOINT or not AZURE_DOCINTEL_KEY:
        raise RuntimeError(
            "Azure Document Intelligence is not configured. "
            "Copy .env.example to .env and set AZURE_DOCINTEL_ENDPOINT and "
            "AZURE_DOCINTEL_KEY (portal: your Document Intelligence resource "
            "-> 'Keys and Endpoint')."
        )
