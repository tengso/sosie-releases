"""
PDF parser using pymupdf4llm.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..models import Document, compute_file_hash
from ..exceptions import ParseError
from .base import BaseParser

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    """PDF document parser using pymupdf4llm."""
    
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        return [".pdf"]
    
    def supported_mimetypes(self) -> List[str]:
        """Return list of supported MIME types."""
        return ["application/pdf"]
    
    def parse(self, file_path: Path) -> Document:
        """
        Parse PDF file and return Document.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Parsed Document
            
        Raises:
            ParseError: If parsing fails
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        file_path = file_path.resolve()
        
        if not file_path.exists():
            raise ParseError(f"File not found: {file_path}")
        
        if not file_path.is_file():
            raise ParseError(f"Not a file: {file_path}")
        
        try:
            page_char_offsets: List[int] = []
            
            # Try pymupdf4llm first for better markdown extraction
            logger.debug(f"Attempting pymupdf4llm.to_markdown for: {file_path}")
            try:
                import pymupdf4llm
                pages_data = pymupdf4llm.to_markdown(str(file_path), page_chunks=True)
                # Build content from per-page chunks and track character offsets
                page_texts = []
                for pd in pages_data:
                    text = pd["text"] if isinstance(pd, dict) else str(pd)
                    page_texts.append(text)
                separator = "\n\n-----\n\n"
                content = separator.join(page_texts)
                # Compute cumulative character offsets per page
                offset = 0
                for i, text in enumerate(page_texts):
                    page_char_offsets.append(offset)
                    offset += len(text)
                    if i < len(page_texts) - 1:
                        offset += len(separator)
                logger.debug(f"pymupdf4llm extraction successful, content length: {len(content)}, pages: {len(page_texts)}")
            except ImportError as import_err:
                logger.error(f"pymupdf4llm import failed: {import_err}", exc_info=True)
                # Fallback to raw PyMuPDF text extraction
                logger.debug("Falling back to raw PyMuPDF extraction")
                content, page_char_offsets = self._extract_text_fallback(file_path)
            except Exception as e:
                logger.warning(f"pymupdf4llm failed for {file_path}: {e}, trying fallback")
                # Fallback to raw PyMuPDF text extraction
                content, page_char_offsets = self._extract_text_fallback(file_path)
            
            # Extract metadata
            metadata = self._extract_metadata(file_path)
            if page_char_offsets:
                metadata["page_char_offsets"] = page_char_offsets
            
            # Compute content hash
            content_hash = compute_file_hash(file_path)
            
            return Document(
                file_path=file_path,
                content=content,
                metadata=metadata,
                content_hash=content_hash,
                parsed_at=datetime.now(),
                file_type="application/pdf",
            )
            
        except Exception as e:
            raise ParseError(f"Failed to parse PDF {file_path}: {e}") from e
    
    def _extract_text_fallback(self, file_path: Path):
        """Fallback text extraction using raw PyMuPDF. Returns (content, page_char_offsets)."""
        logger.debug(f"_extract_text_fallback called for: {file_path}")
        try:
            import fitz
            logger.debug("fitz (pymupdf) imported successfully")
        except ImportError as e:
            logger.error(f"Failed to import fitz (pymupdf): {e}", exc_info=True)
            raise
        
        text_parts = []
        doc = fitz.open(str(file_path))
        
        for page_num, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                text_parts.append(f"## Page {page_num + 1}\n\n{text}")
        
        doc.close()
        separator = "\n\n"
        content = separator.join(text_parts)
        # Compute cumulative character offsets per page
        page_char_offsets = []
        offset = 0
        for i, text in enumerate(text_parts):
            page_char_offsets.append(offset)
            offset += len(text)
            if i < len(text_parts) - 1:
                offset += len(separator)
        return content, page_char_offsets
    
    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from PDF file."""
        import fitz  # pymupdf
        
        metadata = {
            "file_name": file_path.name,
            "file_size": file_path.stat().st_size,
        }
        
        try:
            doc = fitz.open(str(file_path))
            pdf_metadata = doc.metadata
            
            if pdf_metadata:
                if pdf_metadata.get("title"):
                    metadata["title"] = pdf_metadata["title"]
                if pdf_metadata.get("author"):
                    metadata["author"] = pdf_metadata["author"]
                if pdf_metadata.get("subject"):
                    metadata["subject"] = pdf_metadata["subject"]
                if pdf_metadata.get("keywords"):
                    metadata["keywords"] = pdf_metadata["keywords"]
                if pdf_metadata.get("creationDate"):
                    metadata["creation_date"] = pdf_metadata["creationDate"]
            
            metadata["page_count"] = len(doc)
            doc.close()
            
        except Exception:
            pass
        
        return metadata
