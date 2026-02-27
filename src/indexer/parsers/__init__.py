"""
Document parsers for the indexer package.
"""

from .base import BaseParser, ParserRegistry
from .pdf import PDFParser
from .text import TextParser
from .word import WordParser

__all__ = [
    "BaseParser",
    "ParserRegistry",
    "PDFParser",
    "TextParser",
    "WordParser",
]


def create_default_registry() -> ParserRegistry:
    """Create a registry with all default parsers."""
    registry = ParserRegistry()
    registry.register(PDFParser())
    registry.register(TextParser())
    registry.register(WordParser())
    return registry
