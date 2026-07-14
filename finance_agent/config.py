"""Central config loaded from env. Fail fast if required keys missing."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

# Hosts whose OpenAI-compatible endpoint doesn't honour
# ``response_format=json_object`` and needs prompt-side JSON coaching instead.
# Keeping the list here (rather than in llm_openai.py + pydantic_runtime.py)
# means adding a new such backend is a single-line change.
ARK_HOST_MARKERS: tuple[str, ...] = ("ark.cn-beijing.volces.com",)

def is_ark_endpoint(base_url: str | None) -> bool:
    """True when ``base_url`` points at a JSON-mode-unfriendly Ark host."""
    if not base_url:
        return False
    return any(marker in base_url for marker in ARK_HOST_MARKERS)

@dataclass(frozen=True)
class Config:
    # LLMs - Doubao (Volcengine Ark)
    ark_api_key: str
    ark_base_url: str
    doubao_model: str
    # LLMs - DeepSeek
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    # Web
    tavily_api_key: str
    # US Market
    finnhub_api_key: str
    # Paths
    data_dir: Path
    output_dir: Path
    cache_dir: Path
    db_path: Path
    indices_dir: Path
    # Logging
    log_level: str

    # External Data (RAG)
    use_external_data: bool
    external_market_dir: Path | None
    external_financials_dir: Path | None
    external_filings_dir: Path | None

    # Milvus Vector Database
    use_milvus: bool
    milvus_host: str
    milvus_port: str
    milvus_collection: str

    @staticmethod
    def load() -> "Config":
        data_dir = Path(os.getenv("FA_DATA_DIR", ROOT / "data")).resolve()
        output_dir = Path(os.getenv("FA_OUTPUT_DIR", ROOT / "outputs")).resolve()
        cache_dir = Path(os.getenv("FA_CACHE_DIR", data_dir / "cache")).resolve()
        db_path = Path(os.getenv("FA_DB_PATH", data_dir / "finance_agent.db")).resolve()
        indices_dir = (data_dir / "indices").resolve()
        
        # External data directories
        ext_market = os.getenv("FA_EXTERNAL_MARKET_DIR")
        ext_financials = os.getenv("FA_EXTERNAL_FINANCIALS_DIR")
        ext_filings = os.getenv("FA_EXTERNAL_FILINGS_DIR")
        
        for p in (data_dir, output_dir, cache_dir, indices_dir):
            p.mkdir(parents=True, exist_ok=True)
        return Config(
            # Doubao (Volcengine Ark)
            ark_api_key=os.getenv("ARK_API_KEY", ""),
            ark_base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            doubao_model=os.getenv("DOUBAO_MODEL", "doubao-seed-evolving"),
            # DeepSeek
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            # Web
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            # US Market
            finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
            # Paths
            data_dir=data_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            db_path=db_path,
            indices_dir=indices_dir,
            log_level=os.getenv("FA_LOG_LEVEL", "INFO"),
            # External Data
            use_external_data=os.getenv("FA_USE_EXTERNAL_DATA", "true").lower() == "true",
            external_market_dir=Path(ext_market).resolve() if ext_market else None,
            external_financials_dir=Path(ext_financials).resolve() if ext_financials else None,
            external_filings_dir=Path(ext_filings).resolve() if ext_filings else None,
            # Milvus
            use_milvus=os.getenv("FA_USE_MILVUS", "true").lower() == "true",
            milvus_host=os.getenv("FA_MILVUS_HOST", "localhost"),
            milvus_port=os.getenv("FA_MILVUS_PORT", "19530"),
            milvus_collection=os.getenv("FA_MILVUS_COLLECTION", "finance_docs"),
        )

    def require(self, *names: str) -> None:
        """Raise a clear error if any listed key is empty."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                f"Missing required config: {missing}. "
                f"Set them in .env (see .env.example)."
            )

CONFIG = Config.load()
