from __future__ import annotations

import re
import unicodedata
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Compiled regex patterns (compiled once at module load) ────────────────────

# HTML/XML tags: <script>, </div>, <br/>, etc.
_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)

# HTML entities: &amp; &lt; &#x27; &#39; etc.
_HTML_ENTITY_RE = re.compile(r"&(?:#x?[0-9a-fA-F]+|[a-zA-Z]+);")

# Null bytes and other ASCII control characters (except tab, newline, carriage return)
# \x00-\x08 = null + non-printable control chars before tab
# \x0b-\x0c = vertical tab, form feed
# \x0e-\x1f = other control chars after carriage return
# \x7f      = DEL
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Unicode direction override characters (used in bidirectional text attacks)
# These can make "evil.exe" render as "exe.live" in some terminals/UIs
_BIDI_OVERRIDE_RE = re.compile(
    r"[\u200f\u200e\u202a-\u202e\u2066-\u2069\u061c]"
)

# Zero-width characters (can hide content or bypass filters)
_ZERO_WIDTH_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]"
)

# Multiple consecutive whitespace lines (more than 2 blank lines in a row)
_EXCESSIVE_NEWLINES_RE = re.compile(r"\n{3,}")

# Multiple consecutive spaces (more than 2)
_EXCESSIVE_SPACES_RE = re.compile(r" {3,}")

# JavaScript protocol in URLs (href="javascript:...")
_JS_PROTOCOL_RE = re.compile(
    r"(?:javascript|vbscript|data)\s*:",
    re.IGNORECASE,
)


    # ══════════════════════════════════════════════════════════════════════════════
    #  Core sanitization functions
    # ══════════════════════════════════════════════════════════════════════════════

def strip_html(text: str) -> str:
    """
    Remove all HTML and XML tags from a string.

    Does NOT entity-decode — entities like &amp; are left as-is.
    The DB stores raw text, not rendered HTML. Entity rendering is
    the frontend's responsibility.

    Preserves newlines and legitimate whitespace.

    Example:
        strip_html("<b>Hello</b> <script>alert(1)</script> world")
        → "Hello  world"
        """
    return _HTML_TAG_RE.sub("", text)


def strip_html_entities(text: str) -> str:
    """
    Remove HTML entities from a string.

    Used in contexts where even entity-encoded XSS payloads are a risk,
    such as usernames, display names, and group chat names that may be
    rendered without entity decoding in some contexts.

    Example:
        strip_html_entities("Hello &lt;script&gt; &amp; world")
        → "Hello  world"
        """
    return _HTML_ENTITY_RE.sub("", text)


def remove_null_bytes(text: str) -> str:
    """
    Remove null bytes and dangerous ASCII control characters.

    Null bytes (\x00) can:
        - Truncate strings in C-based systems
        - Bypass file extension checks (file.php\x00.jpg)
        - Corrupt PostgreSQL text columns (psycopg2 rejects them)

        Preserves: tab (\x09), newline (\x0a), carriage return (\x0d)
        These are legitimate in multi-line text content.

        Example:
            remove_null_bytes("hello\x00world\x01")
            → "helloworld"
            """
    return _CONTROL_CHAR_RE.sub("", text)


def remove_bidi_overrides(text: str) -> str:
    """
    Remove Unicode bidirectional override and direction control characters.

    These characters can make text display differently from how it is
    stored — a known technique for hiding malicious content in filenames,
    URLs, and chat messages.

    Reference: CVE-2021-42574 (Trojan Source)

    Example:
        remove_bidi_overrides("hello\u202eworld")   # RLO character
        → "helloworld"
        """
    return _BIDI_OVERRIDE_RE.sub("", text)


def remove_zero_width(text: str) -> str:
    """
    Remove zero-width and invisible Unicode characters.

    These characters are invisible but can:
        - Break regex-based content filters
        - Cause two visually identical strings to compare as different
        - Be used to mark/track content without the user's knowledge

        Preserves soft hyphens only if they serve typographic purpose —
        \u00ad is removed here as it is frequently used for evasion.
        """
    return _ZERO_WIDTH_RE.sub("", text)


def normalise_unicode(text: str) -> str:
    """
    Apply Unicode NFC normalisation.

    NFC (Canonical Decomposition followed by Canonical Composition)
    ensures that visually identical characters have identical byte
    representations. Without this, "café" can be stored as 4 or 5 bytes
    depending on whether é is U+00E9 (composed) or e + U+0301 (decomposed).

    This prevents:
        - Duplicate username bypasses (two different byte sequences
        for the same visual username)
        - Inconsistent search results
        - Hash comparison failures on normalised vs non-normalised input

        Example:
            normalise_unicode("cafe\u0301")   # e + combining acute
            → "café"                          # é as single code point
            """
    return unicodedata.normalize("NFC", text)


def clamp_length(text: str, max_length: int, *, truncation_marker: str = "") -> str:
    """
    Clamp a string to a maximum length.

    Truncates at character boundary, not byte boundary. This is important
    for multi-byte Unicode — truncating at a byte boundary can split
    a multi-byte code point, producing an invalid string.

    Args:
        text            : Input string.
        max_length      : Maximum allowed character count.
        truncation_marker: Optional suffix to indicate truncation
        (e.g. "..."). Subtracted from max_length.
        Default: empty string (silent truncation).

        Example:
            clamp_length("hello world", 5)
            → "hello"

            clamp_length("hello world", 8, truncation_marker="...")
            → "hello..."
            """
    if len(text) <= max_length:
        return text

    if truncation_marker:
        cutoff = max_length - len(truncation_marker)
        return text[:cutoff] + truncation_marker

    return text[:max_length]


def collapse_whitespace(text: str) -> str:
    """
    Collapse excessive whitespace in a string.

    Reduces:
        - 3+ consecutive blank lines → 2 blank lines (preserves paragraphs)
        - 3+ consecutive spaces → 2 spaces (preserves intentional double-space)

        Does NOT strip leading/trailing whitespace — that is the caller's
        responsibility via .strip().

        Example:
            collapse_whitespace("hello\n\n\n\n\nworld")
            → "hello\n\nworld"
            """
    text = _EXCESSIVE_NEWLINES_RE.sub("\n\n", text)
    text = _EXCESSIVE_SPACES_RE.sub("  ", text)
    return text


def remove_js_protocols(text: str) -> str:
    """
    Remove javascript:, vbscript:, and data: URL protocols.

    Prevents protocol injection in content that might be used in
    href or src attributes on the frontend.

    Example:
        remove_js_protocols("Click javascript:alert(1)")
        → "Click alert(1)"
        """
    return _JS_PROTOCOL_RE.sub("", text)


# ══════════════════════════════════════════════════════════════════════════════
#  Composite sanitizers — combine primitives for specific field types
# ══════════════════════════════════════════════════════════════════════════════

def sanitize_text_content(
    text: str | None,
    *,
    max_length: int,
) -> str:
    """
    Full sanitization pipeline for user-generated text content.

    Used for: post content, reply content, chat messages, bio text.

    Pipeline:
        1. Handle None → empty string
        2. NFC Unicode normalisation
        3. Remove null bytes and control characters
        4. Remove bidirectional override characters
        5. Remove zero-width characters
        6. Strip HTML tags (no HTML allowed in plain text content)
        7. Remove javascript: protocols
        8. Collapse excessive whitespace
        9. Strip leading/trailing whitespace
        10. Clamp to max_length

        Returns:
            Sanitized string. May be empty if input was all-whitespace or
            all-dangerous-characters.
            """
    if not text:
        return ""

    text = normalise_unicode(text)
    text = remove_null_bytes(text)
    text = remove_bidi_overrides(text)
    text = remove_zero_width(text)
    text = strip_html(text)
    text = remove_js_protocols(text)
    text = collapse_whitespace(text)
    text = text.strip()
    text = clamp_length(text, max_length)

    return text


def sanitize_short_text(
    text: str | None,
    *,
    max_length: int,
) -> str:
    """
    Sanitization pipeline for short single-line fields.

    Used for: display names, group chat names, group descriptions,
    location fields, website URLs (before URL validation),
    username (before regex validation).

    Pipeline:
        1. Handle None → empty string
        2. NFC Unicode normalisation
        3. Remove null bytes and control characters
        4. Remove bidirectional override characters
        5. Remove zero-width characters
        6. Strip HTML tags AND entities
        7. Remove javascript: protocols
        8. Collapse to single line (replace any newline with space)
        9. Collapse excessive spaces
        10. Strip leading/trailing whitespace
        11. Clamp to max_length
        """
    if not text:
        return ""

    text = normalise_unicode(text)
    text = remove_null_bytes(text)
    text = remove_bidi_overrides(text)
    text = remove_zero_width(text)
    text = strip_html(text)
    text = strip_html_entities(text)
    text = remove_js_protocols(text)

    # Collapse any newlines to a single space — short fields are one-liners
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = _EXCESSIVE_SPACES_RE.sub(" ", text)
    text = text.strip()
    text = clamp_length(text, max_length)

    return text


def sanitize_username(username: str | None) -> str:
    """
    Sanitization for username fields.

    Usernames have strict format requirements (handled by Pydantic regex
    validation). This sanitizer does minimal cleaning — just the dangerous
    character removal — before the format validator runs.

    Pipeline:
        1. Handle None → empty string
        2. NFC normalisation
        3. Remove null bytes
        4. Remove bidi overrides
        5. Remove zero-width characters
        6. Lowercase (usernames are case-insensitive)
        7. Strip whitespace
        8. Clamp to 30 characters
        """
    if not username:
        return ""

    username = normalise_unicode(username)
    username = remove_null_bytes(username)
    username = remove_bidi_overrides(username)
    username = remove_zero_width(username)
    username = username.lower().strip()
    username = clamp_length(username, 30)

    return username


def sanitize_filename(filename: str | None) -> str:
    """
    Sanitize a filename for safe storage on disk.

    Used when storing uploaded file attachment names in the DB
    (attachment_name column in messages table).

    Does NOT determine the actual storage path — that is always
    a server-generated UUID path. This sanitizes the display name only.

    Pipeline:
        1. Handle None → "file"
        2. Remove null bytes and control characters
        3. Remove path traversal sequences (../, .\/)
        4. Remove characters invalid in most filesystems
        5. Clamp to 255 characters (POSIX filename limit)
        """
    if not filename:
        return "file"

    filename = remove_null_bytes(filename)

    # Remove path traversal
    filename = filename.replace("..", "").replace("/", "").replace("\\", "")

    # Remove characters invalid on Windows/Linux filesystems
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', "", filename)

    filename = filename.strip(". ")   # strip leading/trailing dots and spaces
    filename = clamp_length(filename, 255)

    return filename or "file"


def sanitize_search_query(query: str | None) -> str:
    """
    Sanitize a user search query string.

    More aggressive than content sanitization — search queries are used
    in SQL LIKE and tsvector expressions. Extra care is taken to remove
    characters that could alter query semantics.

    Pipeline:
        1. Handle None → empty string
        2. NFC normalisation
        3. Remove null bytes
        4. Remove bidi overrides and zero-width chars
        5. Strip HTML
        6. Remove PostgreSQL tsquery special chars: & | ! : * ( ) '
        (These are safe in plainto_tsquery() but dangerous in to_tsquery())
        7. Collapse whitespace
        8. Strip and clamp to 100 characters
        """
    if not query:
        return ""

    query = normalise_unicode(query)
    query = remove_null_bytes(query)
    query = remove_bidi_overrides(query)
    query = remove_zero_width(query)
    query = strip_html(query)

    # Remove PostgreSQL tsquery operators
    query = re.sub(r"[&|!:*()\'\"\\]", " ", query)

    query = collapse_whitespace(query)
    query = query.strip()
    query = clamp_length(query, 100)

    return query