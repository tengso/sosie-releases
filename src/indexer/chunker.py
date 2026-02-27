"""
Document chunking for the indexer package.
"""

import re
import uuid
from pathlib import Path
from typing import List, Optional

from .models import Document, Chunk
from .config import ChunkingConfig
from .exceptions import ChunkingError


class Chunker:
    """Splits documents into chunks for embedding."""
    
    # Sentence ending patterns
    SENTENCE_ENDINGS = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')
    
    # Paragraph pattern (two or more newlines)
    PARAGRAPH_PATTERN = re.compile(r'\n\s*\n')
    
    def __init__(self, config: Optional[ChunkingConfig] = None):
        """
        Initialize chunker.
        
        Args:
            config: Chunking configuration
        """
        self.config = config or ChunkingConfig()
    
    def chunk(self, document: Document) -> List[Chunk]:
        """
        Split document into chunks.
        
        Args:
            document: Document to chunk
            
        Returns:
            List of chunks
            
        Raises:
            ChunkingError: If chunking fails
        """
        try:
            content = document.content
            
            if not content or not content.strip():
                return []
            
            # Split into initial segments based on split_by strategy
            if self.config.split_by == "paragraph":
                segments = self._split_by_paragraphs(content)
            elif self.config.split_by == "sentence":
                segments = self._split_by_sentences(content)
            else:
                segments = self._split_by_size(content)
            
            # Create chunks with proper sizing and overlap
            raw_chunks = self._create_sized_chunks(segments)
            
            # Build Chunk objects with offsets
            chunks = []
            current_offset = 0
            
            for i, chunk_text in enumerate(raw_chunks):
                # Find the actual offset in the document
                start_offset = content.find(chunk_text[:100], current_offset)
                if start_offset == -1:
                    start_offset = current_offset
                
                end_offset = start_offset + len(chunk_text)
                
                chunk = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    document_path=document.file_path,
                    content=chunk_text,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    chunk_index=i,
                    metadata={
                        **document.metadata,
                        "source_file": str(document.file_path),
                        "file_type": document.file_type,
                    },
                )
                chunks.append(chunk)
                
                # Update offset for next search (accounting for overlap)
                current_offset = max(start_offset + 1, end_offset - self.config.chunk_overlap)
            
            return chunks
            
        except Exception as e:
            raise ChunkingError(f"Failed to chunk document {document.file_path}: {e}") from e
    
    def _split_by_paragraphs(self, text: str) -> List[str]:
        """Split text by paragraph boundaries."""
        paragraphs = self.PARAGRAPH_PATTERN.split(text)
        return [p.strip() for p in paragraphs if p.strip()]
    
    def _split_by_sentences(self, text: str) -> List[str]:
        """Split text by sentence boundaries."""
        # First split by paragraphs to maintain structure
        paragraphs = self._split_by_paragraphs(text)
        
        sentences = []
        for para in paragraphs:
            # Split paragraph into sentences
            para_sentences = self.SENTENCE_ENDINGS.split(para)
            sentences.extend([s.strip() for s in para_sentences if s.strip()])
        
        return sentences
    
    def _split_by_size(self, text: str) -> List[str]:
        """Split text by fixed size."""
        segments = []
        for i in range(0, len(text), self.config.chunk_size):
            segment = text[i:i + self.config.chunk_size]
            if segment.strip():
                segments.append(segment)
        return segments
    
    def _create_sized_chunks(self, segments: List[str]) -> List[str]:
        """
        Create chunks of appropriate size with overlap.
        
        Merges small segments and splits large ones.
        """
        chunks = []
        current_chunk = []
        current_size = 0
        
        for segment in segments:
            segment_size = len(segment)
            
            # If single segment exceeds max size, split it
            if segment_size > self.config.max_chunk_size:
                # Flush current chunk first
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_size = 0
                
                # Split large segment
                for i in range(0, segment_size, self.config.chunk_size - self.config.chunk_overlap):
                    sub_segment = segment[i:i + self.config.chunk_size]
                    if sub_segment.strip():
                        chunks.append(sub_segment)
                continue
            
            # Check if adding this segment would exceed target size
            if current_size + segment_size > self.config.chunk_size and current_chunk:
                # Flush current chunk
                chunks.append(" ".join(current_chunk))
                
                # Start new chunk with overlap
                if self.config.chunk_overlap > 0 and current_chunk:
                    # Keep some content for overlap
                    overlap_text = " ".join(current_chunk)
                    overlap_start = max(0, len(overlap_text) - self.config.chunk_overlap)
                    overlap_content = overlap_text[overlap_start:].strip()
                    if overlap_content:
                        current_chunk = [overlap_content]
                        current_size = len(overlap_content)
                    else:
                        current_chunk = []
                        current_size = 0
                else:
                    current_chunk = []
                    current_size = 0
            
            current_chunk.append(segment)
            current_size += segment_size + 1  # +1 for space
        
        # Flush remaining
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            if len(chunk_text) >= self.config.min_chunk_size:
                chunks.append(chunk_text)
            elif chunks:
                # Merge with previous chunk if too small
                chunks[-1] = chunks[-1] + " " + chunk_text
        
        return chunks
    
    def estimate_chunk_count(self, document: Document) -> int:
        """
        Estimate number of chunks for a document.
        
        Args:
            document: Document to estimate
            
        Returns:
            Estimated chunk count
        """
        content_length = len(document.content)
        effective_chunk_size = self.config.chunk_size - self.config.chunk_overlap
        if effective_chunk_size <= 0:
            effective_chunk_size = self.config.chunk_size
        return max(1, content_length // effective_chunk_size)
