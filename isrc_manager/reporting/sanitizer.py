"""Privacy-preserving report sanitisation."""

from __future__ import annotations

import getpass
import re
from collections.abc import Mapping

DEFAULT_MAX_CHARS = 80_000


class ReportSanitizer:
    """Redact secrets and private identifiers before preview or submission."""

    _PRIVATE_KEY_RE = re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    )
    _GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
    _OPENAI_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
    _AWS_KEY_RE = re.compile(r"\bA(?:KIA|SIA)[A-Z0-9]{16}\b")
    _BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
    _ASSIGNMENT_SECRET_RE = re.compile(
        r"(?ix)"
        r"\b("
        r"password|passwd|pwd|secret|client_secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|oauth[_-]?token|github[_-]?token|authorization"
        r")\b"
        r"(\s*[:=]\s*)"
        r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    _CONNECTION_STRING_RE = re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|sqlite)://[^\s'\"<>]+"
    )
    _URL_CREDENTIAL_RE = re.compile(r"\b(https?://)([^/\s:@]+):([^@\s/]+)@")
    _EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
    _PHONE_RE = re.compile(
        r"(?x)" r"(?<![\w])" r"(?:\+|00)?\d{1,3}?" r"(?:[\s().-]*\d){7,}" r"(?![\w])"
    )
    _POSIX_HOME_RE = re.compile(r"(?<![\w])(?:/Users|/home)/[A-Za-z0-9._-]+(?:/[^\s'\"<>]*)?")
    _WINDOWS_HOME_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[A-Za-z0-9._-]+(?:\\[^\s'\"<>]*)?")
    _DB_CONTENT_RE = re.compile(
        r"(?i)\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|VALUES\s*\(|SELECT\s+.+?\s+FROM)\b.*"
    )

    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS):
        self.max_chars = int(max_chars)
        self._placeholder_maps: dict[str, dict[str, str]] = {
            "email": {},
            "phone": {},
            "secret": {},
            "token": {},
            "connection": {},
            "private_key": {},
        }

    def sanitize_text(self, value: object, *, max_chars: int | None = None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return "<BINARY_DATA_REMOVED>"

        text = str(value).replace("\x00", "")
        text = self._PRIVATE_KEY_RE.sub(
            lambda match: self._placeholder("private_key", match.group(0), "REDACTED_PRIVATE_KEY"),
            text,
        )
        text = self._URL_CREDENTIAL_RE.sub(r"\1<REDACTED_USER>:<REDACTED_PASSWORD>@", text)
        text = self._CONNECTION_STRING_RE.sub(
            lambda match: self._placeholder(
                "connection", match.group(0), "REDACTED_CONNECTION_STRING"
            ),
            text,
        )
        text = self._GITHUB_TOKEN_RE.sub(
            lambda match: self._placeholder("token", match.group(0), "REDACTED_GITHUB_TOKEN"),
            text,
        )
        text = self._OPENAI_TOKEN_RE.sub(
            lambda match: self._placeholder("token", match.group(0), "REDACTED_API_KEY"),
            text,
        )
        text = self._AWS_KEY_RE.sub(
            lambda match: self._placeholder("token", match.group(0), "REDACTED_ACCESS_KEY"),
            text,
        )
        text = self._BEARER_RE.sub(
            lambda match: "Bearer "
            + self._placeholder("token", match.group(0), "REDACTED_BEARER_TOKEN"),
            text,
        )
        text = self._ASSIGNMENT_SECRET_RE.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}"
                f"{self._placeholder('secret', match.group(3), 'REDACTED_SECRET')}"
            ),
            text,
        )
        text = self._EMAIL_RE.sub(
            lambda match: self._placeholder("email", match.group(0).lower(), "REDACTED_EMAIL"),
            text,
        )
        text = self._PHONE_RE.sub(self._redact_phone_match, text)
        text = self._POSIX_HOME_RE.sub("<USER_PATH>", text)
        text = self._WINDOWS_HOME_RE.sub("<USER_PATH>", text)
        text = self._redact_current_username(text)
        text = self._DB_CONTENT_RE.sub("<REDACTED_DATABASE_CONTENT>", text)
        return self._truncate(text, max_chars=max_chars)

    def sanitize_mapping(
        self, values: Mapping[str, object], *, max_chars: int | None = None
    ) -> dict[str, str]:
        return {
            str(key): self.sanitize_text(value, max_chars=max_chars)
            for key, value in values.items()
        }

    def _placeholder(self, namespace: str, raw_value: str, prefix: str) -> str:
        mapping = self._placeholder_maps[namespace]
        if raw_value not in mapping:
            mapping[raw_value] = f"<{prefix}_{len(mapping) + 1}>"
        return mapping[raw_value]

    def _redact_current_username(self, text: str) -> str:
        try:
            username = getpass.getuser()
        except Exception:
            return text
        if not username or username.lower() in {"user", "unknown", "root"}:
            return text
        return re.sub(rf"(?<![\w.-]){re.escape(username)}(?![\w.-])", "<LOCAL_USER>", text)

    def _redact_phone_match(self, match: re.Match[str]) -> str:
        raw_value = match.group(0)
        if re.search(r"\b\d{4}[-/.]\d{2}[-/.]\d{2}\b", raw_value):
            return raw_value
        digits = re.sub(r"\D", "", raw_value)
        if len(digits) < 8 or len(digits) > 16:
            return raw_value
        return self._placeholder("phone", raw_value, "REDACTED_PHONE")

    def _truncate(self, text: str, *, max_chars: int | None) -> str:
        limit = self.max_chars if max_chars is None else int(max_chars)
        if limit <= 0 or len(text) <= limit:
            return text
        head = max(1, int(limit * 0.65))
        tail = max(1, limit - head)
        omitted = len(text) - head - tail
        return (
            f"{text[:head].rstrip()}\n"
            f"...[truncated {omitted} characters before report submission]...\n"
            f"{text[-tail:].lstrip()}"
        )
