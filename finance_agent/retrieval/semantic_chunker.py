"""Semantic Chunking — context-aware document splitting.

Improves over simple fixed-size chunking by:
1. Respecting semantic boundaries (sections, tables, paragraphs)
2. Adding context headers to each chunk
3. Smart overlap that preserves sentence boundaries
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# Chunk size targets
_TARGET_TOKENS = 512  # Target chunk size in tokens (approximate)
_MAX_TOKENS = 768     # Maximum chunk size
_OVERLAP_TOKENS = 128  # Overlap between chunks

# Approximate tokens: Chinese chars ≈ 1 token, English words ≈ 1.3 tokens
def estimate_tokens(text: str) -> int:
    """Estimate token count (rough approximation)."""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    return int(chinese_chars + english_words * 1.3 + len(text) * 0.1)


class SemanticChunker:
    """Semantic-aware chunking for financial documents."""

    @staticmethod
    def chunk_csv(df: pd.DataFrame, symbol: str | None = None, 
                  context: str = "") -> list[tuple[str, dict]]:
        """Chunk CSV data with semantic awareness.
        
        Strategy:
        - Keep related rows together (e.g., consecutive dates)
        - Add context header with column descriptions
        - Include summary statistics
        """
        if df.empty:
            return []

        chunks = []
        n_rows = len(df)
        
        # Determine rows per chunk based on data density
        avg_row_tokens = estimate_tokens(df.head(1).to_markdown(index=False))
        rows_per_chunk = max(1, min(50, _TARGET_TOKENS // max(avg_row_tokens, 1)))
        
        # Add summary context
        summary = SemanticChunker._create_csv_summary(df, symbol)
        
        for i in range(0, n_rows, rows_per_chunk):
            end_idx = min(i + rows_per_chunk, n_rows)
            chunk_df = df.iloc[i:end_idx]
            
            # Create rich context header
            header = f"**{context}股票数据: {symbol or '未知'}**\n\n"
            if i == 0:
                header += summary + "\n\n"
            
            header += f"数据范围: 第{i+1}-{end_idx}行 / 共{n_rows}行\n\n"
            
            # Convert to markdown
            md = chunk_df.to_markdown(index=False)
            text = header + md
            
            # Ensure size limit
            if estimate_tokens(text) > _MAX_TOKENS:
                # Reduce rows if too large
                reduced_df = chunk_df.head(max(1, len(chunk_df) // 2))
                md = reduced_df.to_markdown(index=False)
                text = header + md
            
            meta = {
                "type": "csv",
                "symbol": symbol,
                "rows": len(chunk_df),
                "row_range": f"{i}-{end_idx}",
                "context": context,
            }
            chunks.append((text, meta))
        
        return chunks

    @staticmethod
    def _create_csv_summary(df: pd.DataFrame, symbol: str | None) -> str:
        """Create summary for CSV data."""
        summary_parts = []
        
        if 'date' in df.columns:
            dates = pd.to_datetime(df['date'], errors='coerce')
            if not dates.empty and not dates.isna().all():
                summary_parts.append(f"时间范围: {dates.min().strftime('%Y-%m-%d')} 至 {dates.max().strftime('%Y-%m-%d')}")
        
        if 'close' in df.columns:
            summary_parts.append(f"收盘价范围: {df['close'].min():.2f} - {df['close'].max():.2f}")
        
        if 'volume' in df.columns:
            summary_parts.append(f"成交量范围: {df['volume'].min():,.0f} - {df['volume'].max():,.0f}")
        
        return " | ".join(summary_parts) if summary_parts else ""

    @staticmethod
    def chunk_text(text: str, source_kind: str = "", 
                   symbol: str | None = None) -> list[tuple[str, dict]]:
        """Chunk text with semantic awareness.
        
        Strategy:
        1. Split by semantic boundaries (headers, sections)
        2. Respect paragraph boundaries
        3. Add context overlap with sentence awareness
        4. Include metadata about position
        """
        if not text.strip():
            return []

        # Extract structure
        sections = SemanticChunker._split_by_structure(text)
        
        chunks = []
        current_chunk = ""
        current_tokens = 0
        overlap_buffer = ""
        
        for section in sections:
            section_text = section["text"]
            section_type = section["type"]
            section_tokens = estimate_tokens(section_text)
            
            # If single section is too large, split it
            if section_tokens > _MAX_TOKENS:
                if current_chunk:
                    chunks.append(SemanticChunker._create_chunk(
                        current_chunk, source_kind, symbol, 
                        len(chunks), len(sections)
                    ))
                    current_chunk = overlap_buffer
                    current_tokens = estimate_tokens(overlap_buffer)
                
                # Split large section by sentences
                sub_chunks = SemanticChunker._split_large_section(
                    section_text, source_kind, symbol, len(chunks)
                )
                chunks.extend(sub_chunks)
                
                # Reset state
                current_chunk = ""
                current_tokens = 0
                overlap_buffer = ""
                continue
            
            # Check if adding this section exceeds target
            if current_tokens + section_tokens > _TARGET_TOKENS and current_chunk:
                # Save current chunk
                chunks.append(SemanticChunker._create_chunk(
                    current_chunk, source_kind, symbol,
                    len(chunks), len(sections)
                ))
                
                # Start new chunk with overlap
                current_chunk = overlap_buffer
                current_tokens = estimate_tokens(overlap_buffer)
            
            # Add section to current chunk
            if current_chunk:
                current_chunk += "\n\n"
            current_chunk += section_text
            current_tokens += section_tokens
            
            # Update overlap buffer (last few sentences)
            overlap_buffer = SemanticChunker._extract_overlap(section_text)
        
        # Don't forget last chunk
        if current_chunk:
            chunks.append(SemanticChunker._create_chunk(
                current_chunk, source_kind, symbol,
                len(chunks), len(sections)
            ))
        
        return chunks

    @staticmethod
    def _split_by_structure(text: str) -> list[dict]:
        """Split text by semantic structure."""
        sections = []
        
        # Pattern 1: Markdown headers
        header_pattern = r'^(#{1,6}\s+.+)$'
        lines = text.split('\n')
        
        current_section = {"type": "text", "text": "", "header": ""}
        
        for line in lines:
            if re.match(header_pattern, line.strip()):
                # Save previous section
                if current_section["text"].strip():
                    sections.append(current_section)
                
                # Start new section with header
                current_section = {
                    "type": "section",
                    "text": line + "\n",
                    "header": line.strip()
                }
            else:
                current_section["text"] += line + "\n"
        
        # Don't forget last section
        if current_section["text"].strip():
            sections.append(current_section)
        
        # If no headers found, split by paragraphs
        if len(sections) <= 1:
            paragraphs = re.split(r'\n{2,}', text)
            sections = [
                {"type": "paragraph", "text": p.strip(), "header": ""}
                for p in paragraphs if p.strip()
            ]
        
        return sections

    @staticmethod
    def _split_large_section(text: str, source_kind: str, 
                            symbol: str | None, start_index: int) -> list[tuple[str, dict]]:
        """Split a large section by sentences."""
        # Split by sentence boundaries (Chinese and English)
        sentence_pattern = r'(?<=[。！？!?]|[.!?]\s+)'
        sentences = re.split(sentence_pattern, text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        chunks = []
        current_chunk = ""
        current_tokens = 0
        
        for sent in sentences:
            sent_tokens = estimate_tokens(sent)
            
            if current_tokens + sent_tokens > _TARGET_TOKENS and current_chunk:
                chunks.append(SemanticChunker._create_chunk(
                    current_chunk, source_kind, symbol,
                    start_index + len(chunks), len(sentences)
                ))
                current_chunk = sent
                current_tokens = sent_tokens
            else:
                if current_chunk:
                    current_chunk += " "
                current_chunk += sent
                current_tokens += sent_tokens
        
        if current_chunk:
            chunks.append(SemanticChunker._create_chunk(
                current_chunk, source_kind, symbol,
                start_index + len(chunks), len(sentences)
            ))
        
        return chunks

    @staticmethod
    def _extract_overlap(text: str) -> str:
        """Extract last few sentences for overlap."""
        sentence_pattern = r'(?<=[。！？!?]|[.!?]\s+)'
        sentences = re.split(sentence_pattern, text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Take last 2-3 sentences or up to overlap token limit
        overlap = ""
        for sent in reversed(sentences):
            if estimate_tokens(overlap + sent) > _OVERLAP_TOKENS:
                break
            overlap = sent + " " + overlap if overlap else sent
        
        return overlap.strip()

    @staticmethod
    def _create_chunk(text: str, source_kind: str, symbol: str | None,
                      index: int, total: int) -> tuple[str, dict]:
        """Create a chunk with metadata."""
        # Add context header
        header = ""
        if symbol:
            header = f"**{source_kind}: {symbol}**\n\n"
        elif source_kind:
            header = f"**{source_kind}**\n\n"
        
        full_text = header + text if header else text
        
        meta = {
            "type": "text",
            "symbol": symbol,
            "source_kind": source_kind,
            "chunk_index": index,
            "total_chunks": total,
            "tokens": estimate_tokens(full_text),
        }
        
        return (full_text, meta)

    @staticmethod
    def chunk_json(data: list | dict, symbol: str | None = None,
                   context: str = "") -> list[tuple[str, dict]]:
        """Chunk JSON data with semantic awareness."""
        if isinstance(data, dict):
            data = [data]
        
        if not data:
            return []
        
        chunks = []
        n_items = len(data)
        
        # Group related items
        items_per_chunk = max(1, min(20, _TARGET_TOKENS // 50))
        
        for i in range(0, n_items, items_per_chunk):
            end_idx = min(i + items_per_chunk, n_items)
            chunk_items = data[i:end_idx]
            
            header = f"**{context}数据: {symbol or '未知'}**\n\n"
            header += f"条目范围: 第{i+1}-{end_idx}条 / 共{n_items}条\n\n"
            
            text = header + json.dumps(chunk_items, ensure_ascii=False, indent=2)
            
            meta = {
                "type": "json",
                "symbol": symbol,
                "items": len(chunk_items),
                "item_range": f"{i}-{end_idx}",
                "context": context,
            }
            chunks.append((text, meta))
        
        return chunks
