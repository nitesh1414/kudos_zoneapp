"""ZoneApp application package.

Configuration lives in a single ``.env`` file. Loading it here means every
entry point — the API, the market-close worker, the seeder and the CLI
scripts — reads exactly the same settings no matter which directory it is
started from. Real environment variables always win over the file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
ENV_CANDIDATES = (
    Path(os.environ["ZONEAPP_ENV_FILE"]) if os.getenv("ZONEAPP_ENV_FILE") else None,
    BACKEND_DIR / ".env",
    REPO_DIR / ".env",
)


def load_config() -> Path | None:
    """Load the first .env that exists. Returns the file that was used."""
    for candidate in ENV_CANDIDATES:
        if candidate and candidate.is_file():
            load_dotenv(candidate, override=False)
            return candidate
    return None


ENV_FILE = load_config()
