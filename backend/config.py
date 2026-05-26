"""Configuration for the LLM Council."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.4",
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-sonnet-4.6",
    "z-ai/glm-5.1",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "google/gemini-3.1-pro-preview"

# Default editable council bundle. This seeds data/model_bundles.json on first run.
DEFAULT_COUNCIL_BUNDLE_ID = "default"
DEFAULT_COUNCIL_BUNDLES = [
    {
        "id": DEFAULT_COUNCIL_BUNDLE_ID,
        "name": "Default Council",
        "council_models": COUNCIL_MODELS,
        "chairman_model": CHAIRMAN_MODEL,
    }
]

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Storage root. In Docker/Unraid this should point at a mounted volume.
DATA_ROOT = Path(os.getenv("COUNCIL_DATA_ROOT", "data"))

# Raw transcripts stay on disk as the source of truth.
TRANSCRIPTS_DIR = Path(
    os.getenv("COUNCIL_TRANSCRIPTS_DIR", str(DATA_ROOT / "conversations"))
)

# Markdown and knowledge exports are generated separately from transcripts.
EXPORTS_DIR = Path(
    os.getenv("COUNCIL_EXPORTS_DIR", str(DATA_ROOT / "exports"))
)
OBSIDIAN_EXPORTS_DIR = Path(
    os.getenv("COUNCIL_OBSIDIAN_EXPORTS_DIR", str(EXPORTS_DIR / "obsidian"))
)

# Built frontend assets for the production webapp container.
FRONTEND_DIST_DIR = Path(
    os.getenv("COUNCIL_FRONTEND_DIST_DIR", "frontend/dist")
)

# Editable model bundle storage
BUNDLES_PATH = Path(
    os.getenv("COUNCIL_BUNDLES_PATH", str(DATA_ROOT / "model_bundles.json"))
)

# Database connection for metadata, memory, jobs, and future semantic search.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Rolling memory should stay compact when used as follow-up context.
ROLLING_MEMORY_MAX_TOKENS = int(os.getenv("COUNCIL_MEMORY_MAX_TOKENS", "900"))
