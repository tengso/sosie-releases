"""
Tests for indexer parsers.
"""

import pytest
from pathlib import Path

from src.indexer.parsers import (
    BaseParser,
    ParserRegistry,
    PDFParser,
    TextParser,
    create_default_registry,
)
from src.indexer.exceptions import ParseError, UnsupportedFileTypeError


class TestTextParser:
    """Tests for TextParser."""
    
    def test_supported_extensions(self):
        parser = TextParser()
        extensions = parser.supported_extensions()
        
        assert ".txt" in extensions
        assert ".md" in extensions
        assert ".py" in extensions
        assert ".js" in extensions
    
    def test_can_parse_txt(self):
        parser = TextParser()
        assert parser.can_parse(Path("/test/file.txt")) is True
    
    def test_can_parse_markdown(self):
        parser = TextParser()
        assert parser.can_parse(Path("/test/file.md")) is True
    
    def test_cannot_parse_pdf(self):
        parser = TextParser()
        assert parser.can_parse(Path("/test/file.pdf")) is False
    
    def test_parse_txt_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")
        
        parser = TextParser()
        doc = parser.parse(test_file)
        
        assert doc.content == "Hello, World!"
        assert doc.file_type == "text/plain"
        assert doc.file_path == test_file.resolve()
        assert doc.content_hash
    
    def test_parse_markdown_file(self, tmp_path):
        test_file = tmp_path / "test.md"
        test_file.write_text("# Title\n\nContent here.")
        
        parser = TextParser()
        doc = parser.parse(test_file)
        
        assert doc.content == "# Title\n\nContent here."
        assert doc.file_type == "text/markdown"
        assert doc.metadata.get("title") == "Title"
    
    def test_parse_python_file(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('Hello')")
        
        parser = TextParser()
        doc = parser.parse(test_file)
        
        assert "def hello():" in doc.content
        assert doc.file_type == "text/x-python"
    
    def test_parse_nonexistent_file(self, tmp_path):
        parser = TextParser()
        
        with pytest.raises(ParseError, match="not found"):
            parser.parse(tmp_path / "nonexistent.txt")
    
    def test_metadata_extraction(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3")
        
        parser = TextParser()
        doc = parser.parse(test_file)
        
        assert doc.metadata["line_count"] == 3
        assert doc.metadata["file_name"] == "test.txt"
        assert doc.metadata["file_size"] > 0


class TestPDFParser:
    """Tests for PDFParser."""
    
    def test_supported_extensions(self):
        parser = PDFParser()
        extensions = parser.supported_extensions()
        
        assert ".pdf" in extensions
    
    def test_can_parse_pdf(self):
        parser = PDFParser()
        assert parser.can_parse(Path("/test/file.pdf")) is True
    
    def test_cannot_parse_txt(self):
        parser = PDFParser()
        assert parser.can_parse(Path("/test/file.txt")) is False
    
    def test_parse_nonexistent_file(self, tmp_path):
        parser = PDFParser()
        
        with pytest.raises(ParseError, match="not found"):
            parser.parse(tmp_path / "nonexistent.pdf")


class TestParserRegistry:
    """Tests for ParserRegistry."""
    
    def test_create_empty_registry(self):
        registry = ParserRegistry()
        assert len(registry) == 0
    
    def test_register_parser(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        
        assert len(registry) == 1
    
    def test_get_parser_for_txt(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        
        parser = registry.get_parser(Path("/test/file.txt"))
        assert isinstance(parser, TextParser)
    
    def test_get_parser_for_unsupported(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        
        parser = registry.get_parser(Path("/test/file.xyz"))
        assert parser is None
    
    def test_can_parse(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        
        assert registry.can_parse(Path("/test/file.txt")) is True
        assert registry.can_parse(Path("/test/file.xyz")) is False
    
    def test_parse_txt(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content")
        
        registry = ParserRegistry()
        registry.register(TextParser())
        
        doc = registry.parse(test_file)
        assert doc.content == "Content"
    
    def test_parse_unsupported_raises(self, tmp_path):
        test_file = tmp_path / "test.xyz"
        test_file.write_text("Content")
        
        registry = ParserRegistry()
        registry.register(TextParser())
        
        with pytest.raises(UnsupportedFileTypeError):
            registry.parse(test_file)
    
    def test_supported_extensions(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        registry.register(PDFParser())
        
        extensions = registry.supported_extensions()
        assert ".txt" in extensions
        assert ".pdf" in extensions
    
    def test_multiple_parsers(self):
        registry = ParserRegistry()
        registry.register(TextParser())
        registry.register(PDFParser())
        
        assert len(registry) == 2
        assert isinstance(registry.get_parser(Path("/test/file.txt")), TextParser)
        assert isinstance(registry.get_parser(Path("/test/file.pdf")), PDFParser)


class TestCreateDefaultRegistry:
    """Tests for create_default_registry function."""
    
    def test_creates_registry_with_parsers(self):
        registry = create_default_registry()
        
        assert len(registry) >= 2
        assert registry.can_parse(Path("/test/file.txt"))
        assert registry.can_parse(Path("/test/file.pdf"))
