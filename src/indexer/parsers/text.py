"""
Text file parser for plain text, markdown, and code files.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..models import Document, compute_file_hash
from ..exceptions import ParseError
from .base import BaseParser

logger = logging.getLogger(__name__)


class TextParser(BaseParser):
    """Parser for plain text, markdown, and code files."""
    
    EXTENSION_MIMETYPES = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".rst": "text/x-rst",
        ".py": "text/x-python",
        ".js": "text/javascript",
        ".ts": "text/typescript",
        ".jsx": "text/javascript",
        ".tsx": "text/typescript",
        ".java": "text/x-java",
        ".c": "text/x-c",
        ".cpp": "text/x-c++",
        ".h": "text/x-c",
        ".hpp": "text/x-c++",
        ".go": "text/x-go",
        ".rs": "text/x-rust",
        ".rb": "text/x-ruby",
        ".php": "text/x-php",
        ".swift": "text/x-swift",
        ".kt": "text/x-kotlin",
        ".scala": "text/x-scala",
        ".sh": "text/x-shellscript",
        ".bash": "text/x-shellscript",
        ".zsh": "text/x-shellscript",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".json": "application/json",
        ".xml": "text/xml",
        ".html": "text/html",
        ".css": "text/css",
        ".sql": "text/x-sql",
    }
    
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions."""
        return list(self.EXTENSION_MIMETYPES.keys())
    
    def supported_mimetypes(self) -> List[str]:
        """Return list of supported MIME types."""
        return list(set(self.EXTENSION_MIMETYPES.values()))
    
    def parse(self, file_path: Path) -> Document:
        """
        Parse text file and return Document.
        
        Args:
            file_path: Path to text file
            
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
            # Try different encodings
            content = None
            encodings = ["utf-8", "utf-16", "latin-1", "cp1252"]
            
            for encoding in encodings:
                try:
                    content = file_path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                raise ParseError(f"Could not decode file with any supported encoding: {file_path}")
            
            # Extract metadata
            metadata = self._extract_metadata(file_path, content)
            
            # Compute content hash
            content_hash = compute_file_hash(file_path)
            
            # Determine file type
            ext = file_path.suffix.lower()
            file_type = self.EXTENSION_MIMETYPES.get(ext, "text/plain")
            
            return Document(
                file_path=file_path,
                content=content,
                metadata=metadata,
                content_hash=content_hash,
                parsed_at=datetime.now(),
                file_type=file_type,
            )
            
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"Failed to parse text file {file_path}: {e}") from e
    
    def _extract_metadata(self, file_path: Path, content: str) -> Dict[str, Any]:
        """Extract metadata from text file."""
        stat = file_path.stat()
        
        metadata = {
            "file_name": file_path.name,
            "file_size": stat.st_size,
            "line_count": content.count("\n") + 1 if content else 0,
            "char_count": len(content),
        }
        
        # Extract title from markdown if applicable
        ext = file_path.suffix.lower()
        if ext in [".md", ".markdown"]:
            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("# "):
                    metadata["title"] = line[2:].strip()
                    break
        
        return metadata
