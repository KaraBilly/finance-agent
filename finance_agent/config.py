"""Central config loaded from env. Fail fast if required keys missing."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


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

    @staticmethod
    def load() -> "Config":
        data_dir = Path(os.getenv("FA_DATA_DIR", ROOT / "data")).resolve()
        output_dir = Path(os.getenv("FA_OUTPUT_DIR", ROOT / "outputs")).resolve()
        cache_dir = Path(os.getenv("FA_CACHE_DIR", data_dir / "cache")).resolve()
        db_path = Path(os.getenv("FA_DB_PATH", data_dir / "finance_agent.db")).resolve()
        indices_dir = (data_dir / "indices").resolve()
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
