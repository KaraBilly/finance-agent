"""Model downloader — pre-download embedding models during installation.

This module is called during package installation to pre-download
the embedding model, so users don't have to wait on first use.

Usage:
    python -m finance_agent.download_models
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Default model to pre-download
DEFAULT_MODEL = "BAAI/bge-large-zh-v1.5"


def download_embedding_model(model_name: str = DEFAULT_MODEL, cache_dir: str | None = None):
    """Download embedding model during installation.
    
    Args:
        model_name: Name of the model to download
        cache_dir: Directory to cache the model
    
    Returns:
        True if successful, False otherwise
    """
    try:
        from sentence_transformers import SentenceTransformer
        
        log.info(f"Downloading embedding model: {model_name}")
        
        # Set cache directory
        if cache_dir:
            os.environ["SENTENCE_TRANSFORMERS_HOME"] = cache_dir
            os.environ["HF_HOME"] = cache_dir
        
        # Download model
        model = SentenceTransformer(model_name)
        
        log.info(f"Model downloaded successfully: {model_name}")
        log.info(f"Model path: {model.cache_folder}")
        
        # Test the model
        test_embedding = model.encode("test")
        log.info(f"Model test successful, embedding dim: {len(test_embedding)}")
        
        return True
        
    except ImportError:
        log.warning("sentence-transformers not installed, skipping model download")
        return False
    except Exception as e:
        log.error(f"Failed to download model: {e}")
        return False


def download_all_models():
    """Download all required models."""
    print("=" * 60)
    print("Finance Agent - Model Downloader")
    print("=" * 60)
    
    # Download embedding model
    success = download_embedding_model(DEFAULT_MODEL)
    
    if success:
        print("\n✅ All models downloaded successfully!")
    else:
        print("\n⚠️  Model download failed or skipped")
        print("   The system will work with BM25 only (no semantic search)")
        print("   To enable semantic search, install sentence-transformers:")
        print("   pip install sentence-transformers")
    
    return success


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    download_all_models()
