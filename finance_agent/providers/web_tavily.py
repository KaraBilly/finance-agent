"""Tavily + Trafilatura web search provider."""
from __future__ import annotations
import hashlib
import ipaddress
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura
from tavily import TavilyClient

from ..capabilities.web_search import WebSearchCapability
from ..capabilities.llm import LLMCapability
from ..capabilities.base import Evidence
from ..config import CONFIG
from ..retrieval.bm25 import bm25_topk
from ..retrieval.rerank import llm_rerank

log = logging.getLogger(__name__)

# Hard cap on response body size to defend against decompression bombs /
# runaway pages. 20 MB is generous for HTML news pages and small filings;
# anything above this is almost certainly not what we want to feed the LLM.
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024
# Concurrency for fanning out URL extraction. Tavily returns ~6 URLs per
# query; running them sequentially with 15s timeout + 3 retries can burn
# minutes. Six workers matches the default ``max_results``.
_FETCH_CONCURRENCY = 6

_SPLIT_RE = re.compile(r"\n{2,}|(?<=[。！？!?])\s+")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _is_safe_url(url: str) -> bool:
    """SSRF guard: only allow http(s) URLs whose host resolves to a public IP.

    Tavily results, and any LLM-emitted URLs, ultimately get fetched from
    this process. Without a guard, a malicious page could point us at
    ``http://169.254.169.254/`` (cloud metadata) or ``http://localhost:8080``
    (internal services). We defensively reject:

      - non-http(s) schemes (file://, gopher://, ftp://, ...);
      - hosts that resolve to loopback / private / link-local / reserved IPs.

    This isn't perfect (a hostile server can re-resolve between our check
    and requests', a classic TOCTOU) but it blocks the trivial attack.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        candidates = [ip]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            log.debug("DNS lookup failed for %s: %s", host, exc)
            return False
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(info[4][0]))
            except (ValueError, IndexError):
                continue
        if not candidates:
            return False
    for addr in candidates:
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            log.warning("Refusing SSRF-risky URL %s (resolves to %s)", url, addr)
            return False
    return True

def _bounded_get(
    url: str,
    *,
    timeout: int,
    max_bytes: int = _MAX_RESPONSE_BYTES,
) -> tuple[bytes, str] | None:
    """Fetch a URL with a hard size cap.

    Streams the body and aborts as soon as ``max_bytes`` is exceeded so a
    hostile server can't OOM us with a huge (or infinitely-streamed)
    payload. Returns ``(body_bytes, content_type)`` or ``None`` on any
    failure (already logged).
    """
    try:
        with requests.get(
            url, headers=_DEFAULT_HEADERS, timeout=timeout, stream=True
        ) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            # Bail early on advertised size when servers set it honestly.
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                log.warning(
                    "Refusing %s: Content-Length %s exceeds cap %d",
                    url, declared, max_bytes,
                )
                return None
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    log.warning(
                        "Refusing %s: body exceeded cap %d bytes mid-stream",
                        url, max_bytes,
                    )
                    return None
            return bytes(buf), content_type
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response else "unknown"
        log.debug("HTTP %s for %s", status, url)
    except requests.exceptions.Timeout:
        log.debug("Timeout fetching %s", url)
    except requests.exceptions.ConnectionError as exc:
        log.debug("Connection error for %s: %s", url, exc)
    except Exception as exc:
        log.debug("Error fetching %s: %s", url, exc)
    return None

def _fetch_with_retry(
    url: str,
    *,
    max_retries: int = 3,
    timeout: int = 15,
) -> str | None:
    """Fetch URL text with retries, exponential backoff, and size cap."""
    if not _is_safe_url(url):
        return None
    for attempt in range(1, max_retries + 1):
        result = _bounded_get(url, timeout=timeout)
        if result is not None:
            body, _ct = result
            try:
                return body.decode("utf-8", errors="replace")
            except Exception as exc:
                log.debug("decode failed for %s: %s", url, exc)
                return None
        if attempt < max_retries:
            sleep_time = 2 ** attempt
            log.info("Retrying %s in %ds (attempt %d/%d)...",
                     url, sleep_time, attempt, max_retries)
            time.sleep(sleep_time)
    log.warning("All retries failed for %s, skipping", url)
    return None

class TavilyWebProvider(WebSearchCapability):
    """Web search via Tavily, extraction via Trafilatura."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or CONFIG.cache_dir

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"web_{h}.txt"

    def search(self, query: str, *, max_results: int = 6) -> list[dict]:
        CONFIG.require("tavily_api_key")
        client = TavilyClient(api_key=CONFIG.tavily_api_key)
        resp = client.search(query=query, max_results=max_results,
                             search_depth="advanced", include_answer=False)
        return resp.get("results", [])

    def _extract_pdf(self, url: str) -> str:
        """Download and extract text from a PDF URL."""
        # ::: Code Generated by Copilot 3a1e7b02-2fb1-4b8c-9c07-4ed9c5f0a101. This comment will be removed automatically after the file is saved :::
        # Defence-in-depth: re-check SSRF here even though ``extract_content``
        # already gated us. If a future caller wires _extract_pdf directly,
        # they still get the guard.
        if not _is_safe_url(url):
            log.warning("skipping unsafe PDF URL: %s", url)
            return ""
        try:
            import fitz  # PyMuPDF

            # Download PDF with retries + hard size cap so a huge PDF can't
            # exhaust memory in a single ``resp.content`` read.
            pdf_bytes: bytes | None = None
            for attempt in range(1, 4):
                result = _bounded_get(url, timeout=30)
                if result is not None:
                    pdf_bytes, _ct = result
                    break
                if attempt < 3:
                    time.sleep(2 ** attempt)

            if not pdf_bytes:
                return ""
            
            # Extract text using PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            full_text = ""
            for page_num in range(len(doc)):
                page = doc[page_num]
                full_text += page.get_text()
            doc.close()
            
            return full_text.strip()
            
        except ImportError:
            log.warning("PyMuPDF not installed. Cannot process PDF: %s", url)
            return ""
        except Exception as e:
            log.warning("Failed to extract PDF %s: %s", url, e)
            return ""

    def extract_content(self, url: str, fallback_snippet: str = "") -> str:
        # SSRF guard applied here as well so trafilatura.fetch_url cannot be
        # used to reach internal hosts (it does its own request).
        if not _is_safe_url(url):
            log.warning("skipping unsafe URL: %s", url)
            return fallback_snippet or ""
        cache = self._cache_path(url)
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="ignore")
        
        # Check if URL is a PDF
        is_pdf = url.lower().endswith('.pdf') or '.pdf?' in url.lower()
        
        text = ""
        
        if is_pdf:
            # Use PDF extraction for PDF URLs
            log.info("Detected PDF URL, using PyMuPDF extraction: %s", url)
            text = self._extract_pdf(url)
        else:
            # Try trafilatura first (handles JS-heavy sites). We drop ``no_ssl``:
            # accepting untrusted TLS opens the door to MITM'd tampering of the
            # evidence we feed into the model.
            html = None
            try:
                html = trafilatura.fetch_url(url)
            except Exception as e:
                log.debug("trafilatura fetch_url failed for %s: %s", url, e)
            
            # Fallback to requests with retries if trafilatura fails
            if not html:
                try:
                    html = _fetch_with_retry(url)
                except Exception as e:
                    log.debug("requests fallback failed for %s: %s", url, e)
            
            # Extract text from HTML
            if html:
                try:
                    text = trafilatura.extract(
                        html,
                        include_comments=False,
                        include_tables=True,
                        favor_precision=True,
                    ) or ""
                except Exception as e:
                    log.debug("trafilatura extract failed for %s: %s", url, e)
        
        # Fallback to snippet if all extraction methods fail
        if not text:
            text = fallback_snippet or ""
            if text:
                log.info("Using fallback snippet for %s", url)
        
        # Cache the result
        if text:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
            except Exception as e:
                log.debug("Failed to cache content for %s: %s", url, e)
        
        return text

    def _chunk(self, text: str, target: int = 500) -> list[str]:
        parts = _SPLIT_RE.split(text)
        chunks: list[str] = []
        buf = ""
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(buf) + len(p) < target:
                buf = (buf + " " + p).strip()
            else:
                if buf:
                    chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)
        return chunks

    def search_and_extract(
        self,
        query: str,
        *,
        max_results: int = 6,
        bm25_top: int = 20,
        final_top: int = 6,
        reranker: LLMCapability | None = None,
    ) -> list[Evidence]:
        hits = self.search(query, max_results=max_results)
        if not hits:
            return []

        # ::: Code Generated by Copilot 3a1e7b02-2fb1-4b8c-9c07-4ed9c5f0a101. This comment will be removed automatically after the file is saved :::
        # Extract + chunk. Fan out URL extraction in parallel — network I/O
        # is the dominant cost here, so a small thread pool cuts wall time
        # for a typical 6-URL query from ~30s to ~5s in practice.
        def _one(hit: dict) -> tuple[str, dict, str] | None:
            url = hit.get("url", "") or ""
            if not url:
                return None
            title = hit.get("title", "") or ""
            publisher = hit.get("source") or (
                url.split("/")[2] if "://" in url else ""
            )
            snippet = hit.get("content", "") or ""
            try:
                text = self.extract_content(url, fallback_snippet=snippet)
            except Exception as exc:
                log.warning("extract_content failed for %s: %s", url, exc)
                return None
            if not text:
                return None
            return url, {
                "url": url,
                "title": title,
                "publisher": publisher,
                "raw_path": str(self._cache_path(url)),
            }, text

        candidates: list[tuple[str, dict]] = []
        with ThreadPoolExecutor(max_workers=min(_FETCH_CONCURRENCY, len(hits))) as pool:
            for res in pool.map(_one, hits):
                if not res:
                    continue
                _url, meta, text = res
                for ch in self._chunk(text):
                    candidates.append((ch, meta))
        if not candidates:
            return []
        log.info("web candidates: %d chunks from %d urls", len(candidates), len(hits))

        # BM25 pre-filter
        texts = [c[0] for c in candidates]
        top_idx = bm25_topk(query, texts, k=min(bm25_top, len(texts)))
        pre = [candidates[i] for i in top_idx]

        # LLM rerank
        if reranker is not None and pre:
            try:
                ranked_idx = llm_rerank(reranker, query, [p[0] for p in pre], k=final_top)
                pre = [pre[i] for i in ranked_idx]
            except Exception as e:
                log.warning("LLM rerank failed, falling back to BM25 order: %s", e)
                pre = pre[:final_top]
        else:
            pre = pre[:final_top]

        # Build Evidence list (without persisting - that's storage's job)
        evidences: list[Evidence] = []
        for text, meta in pre:
            evidences.append(Evidence(
                text=text,
                source_kind="web",
                url=meta["url"],
                title=meta["title"],
                publisher=meta["publisher"],
                meta={"raw_path": meta["raw_path"]},
            ))
        log.info("web final: %d chunks", len(evidences))
        return evidences
