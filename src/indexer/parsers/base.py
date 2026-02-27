"""
Base parser class and registry.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Type

from ..models import Document
from ..exceptions import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Abstract base class for document parsers."""
    
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions (with dot, e.g., '.pdf')."""
        pass
    
    @abstractmethod
    def supported_mimetypes(self) -> List[str]:
        """Return list of supported MIME types."""
        pass
    
    @abstractmethod
    def parse(self, file_path: Path) -> Document:
        """
        Parse file and return Document.
        
        Args:
            file_path: Path to the file to parse
            
        Returns:
            Parsed Document
            
        Raises:
            ParseError: If parsing fails
        """
        pass
    
    def can_parse(self, file_path: Path) -> bool:
        """
        Check if this parser can handle the file.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if this parser can handle the file
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        return file_path.suffix.lower() in self.supported_extensions()


class ParserRegistry:
    """Registry for document parsers."""
    
    def __init__(self):
        self._parsers: List[BaseParser] = []
        self._extension_map: Dict[str, BaseParser] = {}
    
    def register(self, parser: BaseParser) -> None:
        """
        Register a parser.
        
        Args:
            parser: Parser instance to register
        """
        self._parsers.append(parser)
        for ext in parser.supported_extensions():
            self._extension_map[ext.lower()] = parser
    
    def get_parser(self, file_path: Path) -> Optional[BaseParser]:
        """
        Get appropriate parser for file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Parser instance or None if no parser found
        """
        if isinstance(file_path, str):
            file_path = Path(file_path)
        ext = file_path.suffix.lower()
        return self._extension_map.get(ext)
    
    def can_parse(self, file_path: Path) -> bool:
        """
        Check if any parser can handle the file.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if a parser exists for this file type
        """
        return self.get_parser(file_path) is not None
    
    def parse(self, file_path: Path) -> Document:
        """
        Parse file using appropriate parser.
        
        Args:
            file_path: Path to file
            
        Returns:
            Parsed Document
            
        Raises:
            UnsupportedFileTypeError: If no parser found for file type
        """
        logger.debug(f"ParserRegistry.parse called for: {file_path}")
        parser = self.get_parser(file_path)
        if parser is None:
            logger.warning(f"No parser found for file type: {file_path.suffix}")
            raise UnsupportedFileTypeError(
                f"No parser found for file type: {file_path.suffix}"
            )
        logger.debug(f"Using parser: {parser.__class__.__name__} for {file_path}")
        try:
            result = parser.parse(file_path)
            logger.debug(f"Parse successful: {file_path}")
            return result
        except Exception as e:
            logger.error(f"Parser {parser.__class__.__name__} failed for {file_path}: {e}", exc_info=True)
            raise
    
    def supported_extensions(self) -> List[str]:
        """Get all supported file extensions."""
        return list(self._extension_map.keys())
    
    def __len__(self) -> int:
        return len(self._parsers)
