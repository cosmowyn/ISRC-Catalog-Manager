from __future__ import annotations

import json
import os

from isrc_manager.external_launch import (
    TEST_BLOCK_ENV_VAR,
    clear_recorded_external_launches,
    external_launch_blocking_enabled,
    external_launch_guard_active,
    get_recorded_external_launches,
)

try:
    from PySide6.QtCore import QCoreApplication, Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication
except Exception as exc:  # pragma: no cover - probe fallback
    raise SystemExit(str(exc))


def main() -> int:
    app = QApplication.instance() or QApplication([])
    clear_recorded_external_launches()
    opened = QDesktopServices.openUrl(QUrl.fromLocalFile("/tmp/external-launch-probe.txt"))
    requests = get_recorded_external_launches()
    payload = {
        "env": os.environ.get(TEST_BLOCK_ENV_VAR),
        "guard_active": external_launch_guard_active(),
        "blocking_enabled": external_launch_blocking_enabled(),
        "native_dialogs_disabled": QCoreApplication.testAttribute(Qt.AA_DontUseNativeDialogs),
        "open_result": bool(opened),
        "request_count": len(requests),
        "first_via": requests[0].via if requests else None,
        "first_target": requests[0].target if requests else None,
        "first_blocked": requests[0].blocked if requests else None,
    }
    print(json.dumps(payload))
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
