"""Track duration formatting helpers."""


def seconds_to_hms(total: int) -> str:
    try:
        total = max(0, int(total or 0))
    except Exception:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def hms_to_seconds(h: int, m: int, s: int) -> int:
    try:
        h = max(0, int(h or 0))
        m = max(0, int(m or 0))
        s = max(0, int(s or 0))
    except Exception:
        h, m, s = 0, 0, 0
    if m > 59 or s > 59:
        m = min(m, 59)
        s = min(s, 59)
    return h * 3600 + m * 60 + s


def parse_hms_text(t: str) -> int:
    try:
        parts = [int(x) for x in (t or "").split(":")]
        if len(parts) == 3:
            return hms_to_seconds(parts[0], parts[1], parts[2])
    except Exception:
        pass
    return 0

