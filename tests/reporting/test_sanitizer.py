from isrc_manager.reporting.sanitizer import ReportSanitizer


def test_sanitizer_redacts_common_secret_and_identity_patterns() -> None:
    sanitizer = ReportSanitizer(max_chars=10_000)
    raw = """
    user email: legal@example.com and again legal@example.com
    phone: +31 647 821 383
    path: /Users/cosmowyn/Music/private/catalog.db
    password = hunter2
    access_token="oauth-secret-token"
    Authorization: Bearer abcdefghijklmnopqrstuvwxyz
    github token ghp_abcdefghijklmnopqrstuvwxyz1234567890
    database postgresql://catalog:secret@localhost/catalog
    -----BEGIN PRIVATE KEY-----
    secret material
    -----END PRIVATE KEY-----
    """

    sanitized = sanitizer.sanitize_text(raw)

    assert "legal@example.com" not in sanitized
    assert "<REDACTED_EMAIL_1>" in sanitized
    assert sanitized.count("<REDACTED_EMAIL_1>") == 2
    assert "+31 647 821 383" not in sanitized
    assert "<REDACTED_PHONE_1>" in sanitized
    assert "/Users/cosmowyn" not in sanitized
    assert "<USER_PATH>" in sanitized
    assert "hunter2" not in sanitized
    assert "oauth-secret-token" not in sanitized
    assert "abcdefghijklmnopqrstuvwxyz" not in sanitized
    assert "postgresql://catalog:secret@localhost/catalog" not in sanitized
    assert "secret material" not in sanitized
    assert "<REDACTED_PRIVATE_KEY_1>" in sanitized


def test_sanitizer_keeps_timestamps_useful_while_redacting_phone_numbers() -> None:
    sanitizer = ReportSanitizer()

    sanitized = sanitizer.sanitize_text("2026-06-01 13:13:00 call +31 647 821 383")

    assert "2026-06-01 13:13:00" in sanitized
    assert "+31 647 821 383" not in sanitized
    assert "<REDACTED_PHONE_1>" in sanitized


def test_sanitizer_removes_database_content_and_truncates_logs() -> None:
    sanitizer = ReportSanitizer(max_chars=80)
    raw = "INSERT INTO tracks VALUES ('Private Song', 'Private Artist');\n" + ("x" * 200)

    sanitized = sanitizer.sanitize_text(raw)

    assert "Private Song" not in sanitized
    assert "<REDACTED_DATABASE_CONTENT>" in sanitized
    assert "truncated" in sanitized
    assert len(sanitized) < 160
