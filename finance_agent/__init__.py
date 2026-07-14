"""Finance Personal Agent — A-share focused, dual-model (doubao + deepseek)."""

# Load .env BEFORE any submodule (or third-party like huggingface_hub /
# sentence_transformers) is imported. huggingface_hub reads HF_HUB_OFFLINE
# exactly once at import time; if we let another module trigger that import
# first, offline mode silently won't take effect and the loader will still
# try to hit huggingface.co.
from dotenv import load_dotenv as _load_dotenv
_load_dotenv()

__version__ = "0.1.0"
