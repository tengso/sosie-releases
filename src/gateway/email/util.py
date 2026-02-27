"""
Utility functions for the email gateway.

- Relay body wrapping / unwrapping
- Subject-line tag parsing
- Relay token generation
- HTML → plain-text conversion
- Attachment text extraction via indexer parsers
"""

import html
import logging
import os
import re
import secrets
import tempfile
from typing import List, Optional, Tuple

from .models import Attachment

logger = logging.getLogger(__name__)

# ── Relay token ──────────────────────────────────────────────────


def generate_relay_token(length: int = 8) -> str:
    """Generate a random hex token for relay subject tags."""
    return secrets.token_hex(length // 2)


# ── Subject-line parsing ────────────────────────────────────────

_RELAY_TOKEN_RE = re.compile(r"\[R:([a-fA-F0-9]+)\]")
_FROM_TAG_RE = re.compile(r"\[From:\s*([^\]]+)\]")
_AGENT_TAG_RE = re.compile(r"\[(QA|Research|Help)\]", re.IGNORECASE)
_RELAY_TO_RE = re.compile(r"\[To:\s*([^\]]+)\]", re.IGNORECASE)


def parse_relay_token(subject: str) -> Optional[str]:
    """Extract relay token from subject, e.g. '[R:abc123]' → 'abc123'."""
    m = _RELAY_TOKEN_RE.search(subject)
    return m.group(1) if m else None


def parse_from_tag(subject: str) -> Optional[str]:
    """Extract [From: user@firm.com] from subject."""
    m = _FROM_TAG_RE.search(subject)
    return m.group(1).strip() if m else None


def parse_agent_tag(subject: str) -> Optional[str]:
    """Extract agent routing tag from subject.

    Returns agent name: 'doc_qa_agent', 'deep_research_agent', or None.
    """
    m = _AGENT_TAG_RE.search(subject)
    if not m:
        return None
    tag = m.group(1).lower()
    mapping = {
        "qa": "doc_qa_agent",
        "research": "deep_research_agent",
        "help": None,
    }
    return mapping.get(tag)


def parse_relay_target(subject: str) -> Optional[str]:
    """Extract relay target from subject, e.g. '[To: bob@firm.com]' → 'bob@firm.com'."""
    m = _RELAY_TO_RE.search(subject)
    return m.group(1).strip() if m else None


def is_help_request(subject: str) -> bool:
    """Check if the subject contains a [Help] tag."""
    return bool(re.search(r"\[Help\]", subject, re.IGNORECASE))


def clean_subject(subject: str) -> str:
    """Remove gateway-specific tags from subject for clean display."""
    cleaned = subject
    for pattern in [_RELAY_TOKEN_RE, _FROM_TAG_RE, _AGENT_TAG_RE, _RELAY_TO_RE]:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


# ── Relay body wrapping ─────────────────────────────────────────

_RELAY_HEADER_RE = re.compile(
    r"^--- Message from (.+?) ---\n(.*?)\n--- End ---",
    re.DOTALL | re.MULTILINE,
)


def wrap_relay_body(body: str, from_user: str) -> str:
    """Wrap a message body with relay attribution headers."""
    return f"--- Message from {from_user} ---\n{body}\n--- End ---"


def unwrap_relay_body(body: str) -> Tuple[Optional[str], str]:
    """Extract (from_user, original_body) from a relay-wrapped body.

    Returns (None, body) if no relay wrapper found.
    """
    m = _RELAY_HEADER_RE.search(body)
    if m:
        return m.group(1), m.group(2)
    return None, body


# ── HTML → plain text ───────────────────────────────────────────


def html_to_text(html_body: str) -> str:
    """Simple HTML to plain-text conversion."""
    text = re.sub(r"<br\s*/?>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_body_text(plain_body: Optional[str], html_body: Optional[str]) -> str:
    """Get the best plain-text representation of an email body."""
    if plain_body and plain_body.strip():
        return plain_body.strip()
    if html_body:
        return html_to_text(html_body)
    return ""


# ── Attachment text extraction ───────────────────────────────────


def extract_attachment_text(
    attachments: List[Attachment],
    max_chars: int = 50000,
) -> str:
    """Extract text from attachments using indexer parsers.

    Returns formatted text blocks for each successfully parsed attachment.
    """
    if not attachments:
        return ""

    blocks: List[str] = []

    for att in attachments:
        text = _parse_single_attachment(att)
        if text:
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n[... truncated at {max_chars} chars ...]"
            blocks.append(f"--- Attachment: {att.filename} ---\n{text}\n--- End Attachment ---")
        else:
            blocks.append(f"--- Attachment: {att.filename} (unsupported format, not parsed) ---")

    return "\n\n".join(blocks)


def _parse_single_attachment(att: Attachment) -> Optional[str]:
    """Try to extract text from a single attachment using indexer parsers."""
    try:
        from src.indexer.parsers import get_parser_for_extension

        ext = os.path.splitext(att.filename)[1].lower()
        parser = get_parser_for_extension(ext)
        if parser is None:
            logger.debug("No parser for extension %s (%s)", ext, att.filename)
            return None

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(att.content)
            tmp_path = tmp.name

        try:
            result = parser.parse(tmp_path)
            return result.text if hasattr(result, "text") else str(result)
        finally:
            os.unlink(tmp_path)

    except ImportError:
        logger.warning("Indexer parsers not available for attachment extraction")
        return None
    except Exception as e:
        logger.warning("Failed to parse attachment %s: %s", att.filename, e)
        return None


# ── Compose message with attachment context ──────────────────────


def compose_agent_message(body: str, attachments: List[Attachment], max_chars: int = 50000) -> str:
    """Compose the full message text sent to the agent, including attachment content."""
    parts = [body]
    att_text = extract_attachment_text(attachments, max_chars)
    if att_text:
        parts.append(att_text)
    return "\n\n".join(parts)


# ── Markdown → HTML for email ────────────────────────────────────

_EMAIL_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333; }
pre { background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 13px; }
code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-size: 13px; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #ccc; margin: 0; padding: 4px 12px; color: #666; }
table { border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
th { background: #f4f4f4; }
h1 { font-size: 20px; } h2 { font-size: 17px; } h3 { font-size: 15px; }
ul, ol { padding-left: 24px; }
"""


def markdown_to_html(text: str) -> str:
    """Convert markdown text to an email-friendly HTML document."""
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark", {"html": False, "typographer": True})
    body_html = md.render(text)

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{_EMAIL_CSS}</style></head>"
        f"<body>{body_html}</body></html>"
    )
