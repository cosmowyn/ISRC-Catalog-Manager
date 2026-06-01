"""Application update workflow orchestration for the application shell."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from isrc_manager.app_dialogs import ReleaseNotesDialog
from isrc_manager.tasks import TaskFailure
from isrc_manager.update_checker import (
    DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS,
    UpdateChecker,
    UpdateCheckResult,
    UpdateCheckStatus,
    fetch_release_notes_text,
)
from isrc_manager.update_handoff import (
    cleanup_legacy_update_backups_for_version,
    cleanup_ready_update_backup,
    cleanup_update_backup_siblings,
    cleanup_update_cache_artifacts,
    mark_update_backup_ready_for_deletion,
)
from isrc_manager.update_installer import (
    UpdateInstallerError,
    UpdateInstallPlan,
    detect_platform_key,
    download_update_asset,
    launch_update_helper,
    prepare_update_install_plan,
    resolve_installed_target_path,
    select_platform_asset,
    update_workspace_root,
    validate_install_target_is_replaceable,
)


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback) if main_window_module is not None else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _root_sys():
    return _root_attr("sys", sys)


def _cleanup_ready_update_backup():
    return _root_attr("cleanup_ready_update_backup", cleanup_ready_update_backup)()


def _resolve_installed_target_path(*args, **kwargs):
    return _root_attr("resolve_installed_target_path", resolve_installed_target_path)(
        *args, **kwargs
    )


def _cleanup_update_backup_siblings(*args, **kwargs):
    return _root_attr("cleanup_update_backup_siblings", cleanup_update_backup_siblings)(
        *args, **kwargs
    )


def _cleanup_legacy_update_backups_for_version(*args, **kwargs):
    return _root_attr(
        "cleanup_legacy_update_backups_for_version", cleanup_legacy_update_backups_for_version
    )(*args, **kwargs)


def _cleanup_update_cache_artifacts_helper(*args, **kwargs):
    return _root_attr("cleanup_update_cache_artifacts", cleanup_update_cache_artifacts)(
        *args, **kwargs
    )


def _mark_update_backup_ready_for_deletion():
    return _root_attr(
        "mark_update_backup_ready_for_deletion", mark_update_backup_ready_for_deletion
    )()


def _detect_platform_key(*args, **kwargs):
    return _root_attr("detect_platform_key", detect_platform_key)(*args, **kwargs)


def _select_platform_asset(*args, **kwargs):
    return _root_attr("select_platform_asset", select_platform_asset)(*args, **kwargs)


def _validate_install_target_is_replaceable(*args, **kwargs):
    return _root_attr(
        "validate_install_target_is_replaceable", validate_install_target_is_replaceable
    )(*args, **kwargs)


def _update_workspace_root(*args, **kwargs):
    return _root_attr("update_workspace_root", update_workspace_root)(*args, **kwargs)


def _download_update_asset(*args, **kwargs):
    return _root_attr("download_update_asset", download_update_asset)(*args, **kwargs)


def _prepare_update_install_plan(*args, **kwargs):
    return _root_attr("prepare_update_install_plan", prepare_update_install_plan)(*args, **kwargs)


def _launch_update_helper(*args, **kwargs):
    return _root_attr("launch_update_helper", launch_update_helper)(*args, **kwargs)


def _fetch_release_notes_text(*args, **kwargs):
    return _root_attr("fetch_release_notes_text", fetch_release_notes_text)(*args, **kwargs)


def _cleanup_ready_update_backup_handoff(self, *, phase: str) -> None:
    try:
        _cleanup_ready_update_backup()
    except Exception as exc:
        self._log_event(
            "updates.backup_cleanup_failed",
            "Update backup cleanup failed",
            level=logging.WARNING,
            phase=phase,
            error=str(exc),
        )


def _cleanup_legacy_update_backup_siblings(self) -> None:
    if not getattr(_root_sys(), "frozen", False):
        return
    try:
        installed_target = _resolve_installed_target_path()
        removed_paths = _cleanup_update_backup_siblings(installed_target)
        if not removed_paths:
            removed_paths = _cleanup_legacy_update_backups_for_version(
                installed_target,
                self._app_version_text(),
            )
    except Exception as exc:
        self._log_event(
            "updates.legacy_backup_cleanup_failed",
            "Legacy update backup cleanup failed",
            level=logging.WARNING,
            error=str(exc),
        )
        return
    if removed_paths:
        self._log_event(
            "updates.legacy_backup_cleanup",
            "Removed legacy update backup(s)",
            level=logging.INFO,
            count=len(removed_paths),
            paths=[str(path) for path in removed_paths],
        )


def _cleanup_update_cache_artifacts(self) -> None:
    if not getattr(_root_sys(), "frozen", False):
        return
    try:
        removed_paths = _cleanup_update_cache_artifacts_helper(
            update_root=self.storage_layout.preferred_data_root / "updates",
        )
    except Exception as exc:
        self._log_event(
            "updates.cache_cleanup_failed",
            "Update cache cleanup failed",
            level=logging.WARNING,
            error=str(exc),
        )
        return
    if removed_paths:
        self._log_event(
            "updates.cache_cleanup",
            "Removed update cache artifact(s)",
            level=logging.INFO,
            count=len(removed_paths),
            paths=[str(path) for path in removed_paths],
        )


def _finalize_update_backup_handoff(self, *, phase: str) -> None:
    if not getattr(self, "_startup_ready_emitted", False):
        return
    try:
        state = _mark_update_backup_ready_for_deletion()
    except Exception as exc:
        self._log_event(
            "updates.backup_handoff_ready_failed",
            "Update backup handoff could not be marked ready for cleanup",
            level=logging.WARNING,
            phase=phase,
            error=str(exc),
        )
        return
    if state is not None:
        self._cleanup_ready_update_backup_handoff(phase=phase)
    self._cleanup_legacy_update_backup_siblings()
    self._cleanup_update_cache_artifacts()


def _mark_update_backup_handoff_ready_on_close(self) -> None:
    if getattr(self, "_update_install_handoff_in_progress", False):
        self._log_event(
            "updates.cache_cleanup_deferred",
            "Deferred update backup/cache cleanup while update helper is installing",
            level=logging.INFO,
            phase="close",
        )
        return
    self._finalize_update_backup_handoff(phase="close")


def _schedule_startup_update_check(self) -> None:
    QTimer.singleShot(1000, lambda: self._run_startup_update_check())


def _run_startup_update_check(self) -> None:
    if getattr(self, "_is_closing", False):
        return
    try:
        self._start_update_check(manual=False)
    except RuntimeError as exc:
        if "Internal C++ object" in str(exc):
            return
        raise


def check_for_updates(self) -> None:
    self._start_update_check(manual=True)


def _build_update_checker(self) -> UpdateChecker:
    return UpdateChecker()


def _start_update_check(self, *, manual: bool) -> None:
    if not getattr(_root_sys(), "frozen", False):
        return
    action = getattr(self, "check_for_updates_action", None)
    if manual and action is not None:
        action.setEnabled(False)
    ignored_version = "" if manual else self.update_preferences.ignored_version()
    current_version = self._app_version_text()

    def _task(ctx):
        ctx.set_status("Checking for updates...")
        checker = self._build_update_checker()
        return checker.check(current_version, ignored_version=ignored_version)

    def _success(result):
        if isinstance(result, UpdateCheckResult):
            self._handle_update_check_result(result, manual=manual)
        elif manual:
            _message_box().information(
                self,
                "Check for Updates",
                "Update information is unavailable right now.",
            )

    def _error(failure: TaskFailure):
        if manual:
            _message_box().information(
                self,
                "Check for Updates",
                "Update information is unavailable right now. Check your internet connection and try again.",
            )
        else:
            self._log_event(
                "updates.check_failed",
                "Startup update check failed",
                level=logging.INFO,
                error=getattr(failure, "message", ""),
            )

    def _finished():
        if manual and action is not None:
            action.setEnabled(True)

    task_id = self._submit_background_task(
        title="Check for Updates",
        description="Checking for updates...",
        task_fn=_task,
        kind="network",
        unique_key="updates.check",
        requires_profile=False,
        show_dialog=manual,
        owner=self,
        on_success=_success,
        on_error=_error,
        on_finished=_finished,
    )
    if task_id is None and manual and action is not None:
        action.setEnabled(True)


def _handle_update_check_result(
    self,
    result: UpdateCheckResult,
    *,
    manual: bool,
) -> None:
    if result.status == UpdateCheckStatus.UPDATE_AVAILABLE:
        self._show_update_available_message(result)
        return
    if result.status == UpdateCheckStatus.CURRENT:
        if manual:
            _message_box().information(
                self,
                "Check for Updates",
                (
                    "You are running the latest available version.\n\n"
                    f"Installed version: {result.current_version}"
                ),
            )
        return
    if result.status == UpdateCheckStatus.IGNORED:
        return
    if manual:
        _message_box().information(
            self,
            "Check for Updates",
            "Update information is unavailable right now. Check your internet connection and try again.",
        )
    else:
        self._log_event(
            "updates.check_unavailable",
            "Startup update information unavailable",
            level=logging.INFO,
            current_version=result.current_version,
        )


def _show_update_available_message(self, result: UpdateCheckResult) -> None:
    manifest = result.manifest
    if manifest is None:
        return
    install_button = None
    install_asset_available = False
    installer_unavailable = ""
    try:
        _select_platform_asset(manifest)
        install_asset_available = True
    except UpdateInstallerError as exc:
        installer_unavailable = f"\n\nAutomatic installation is not available: {exc}"
    text = (
        "A newer version of Music Catalog Manager is available.\n\n"
        f"Installed version: {result.current_version}\n"
        f"Latest version: {manifest.version}\n\n"
        f"{manifest.summary}"
        f"{installer_unavailable}"
    )
    message_box = _message_box()(self)
    message_box.setWindowTitle("Update Available")
    message_box.setIcon(_message_box().Information)
    message_box.setText(text)
    release_notes_button = None
    if install_asset_available:
        install_button = message_box.addButton("Download and Install", _message_box().ActionRole)
    if manifest.release_notes_url:
        release_notes_button = message_box.addButton("Release Notes", _message_box().ActionRole)
    ignore_button = message_box.addButton("Ignore This Version", _message_box().RejectRole)
    later_button = message_box.addButton("Later", _message_box().AcceptRole)
    message_box.setDefaultButton(later_button)
    message_box.exec()
    clicked = message_box.clickedButton()
    if clicked is ignore_button:
        self.update_preferences.set_ignored_version(manifest.version)
        self.statusBar().showMessage(f"Ignoring update {manifest.version}.", 5000)
        return
    if clicked is release_notes_button:
        self._show_update_release_notes(manifest)
        return
    if install_button is not None and clicked is install_button:
        self._confirm_and_start_update_install(manifest)


def _confirm_and_start_update_install(self, manifest) -> None:
    if not getattr(_root_sys(), "frozen", False):
        _message_box().information(
            self,
            "Install Update",
            "Automatic installation is only available in packaged builds.",
        )
        return
    reply = _message_box().question(
        self,
        "Install Update",
        (
            f"Download and install version {getattr(manifest, 'version', '')}?\n\n"
            "The application will close and restart after the package is verified."
        ),
        _message_box().Yes | _message_box().No,
        _message_box().No,
    )
    if reply != _message_box().Yes:
        return
    self._start_update_install(manifest)


def _start_update_install(self, manifest) -> None:
    try:
        platform_key = _detect_platform_key()
        asset = _select_platform_asset(manifest, platform_key=platform_key)
        _validate_install_target_is_replaceable(
            _resolve_installed_target_path(platform_key=platform_key),
            platform_key=platform_key,
        )
    except UpdateInstallerError as exc:
        _message_box().information(self, "Install Update", str(exc))
        return

    workspace = _update_workspace_root(getattr(manifest, "version", ""), platform_key=platform_key)

    def _task(ctx):
        ctx.raise_if_cancelled()
        ctx.set_status("Downloading update package...")
        downloaded = _download_update_asset(
            asset,
            workspace / "downloads",
            progress_callback=ctx.report_progress,
            is_cancelled=ctx.is_cancelled,
        )
        ctx.raise_if_cancelled()
        ctx.set_status("Preparing update installer...")
        return _prepare_update_install_plan(
            manifest,
            downloaded.package_path,
            platform_key=platform_key,
            cache_root=workspace.parent,
            progress_callback=ctx.report_progress,
            is_cancelled=ctx.is_cancelled,
        )

    def _success(plan):
        if isinstance(plan, UpdateInstallPlan):
            self._launch_prepared_update(plan)
        else:
            _message_box().warning(
                self,
                "Install Update",
                "The update installer could not be prepared.",
            )

    def _error(failure: TaskFailure):
        failure_message = str(getattr(failure, "message", "") or "").strip()
        self._log_event(
            "updates.install_prepare_failed",
            "Update installer preparation failed",
            level=logging.WARNING,
            version=getattr(manifest, "version", ""),
            error=failure_message,
        )
        if failure_message:
            message = f"The update could not be prepared.\n\n{failure_message}"
        else:
            message = (
                "The update could not be prepared. Check your internet connection and "
                "try again later."
            )
        _message_box().warning(
            self,
            "Install Update",
            message,
        )

    task_id = self._submit_background_task(
        title="Install Update",
        description="Preparing update installation...",
        task_fn=_task,
        kind="network",
        unique_key="updates.install",
        requires_profile=False,
        show_dialog=True,
        cancellable=True,
        owner=self,
        on_success=_success,
        on_error=_error,
        worker_completion_progress=(95, "Ready to install update."),
    )
    if task_id is None:
        _message_box().information(
            self,
            "Install Update",
            "Another update task is already running.",
        )


def _launch_prepared_update(self, plan: UpdateInstallPlan) -> None:
    try:
        _launch_update_helper(plan.helper_command)
    except Exception as exc:
        self._log_event(
            "updates.helper_launch_failed",
            "Update helper could not be launched",
            level=logging.ERROR,
            version=plan.expected_version,
            error=str(exc),
        )
        _message_box().critical(
            self,
            "Install Update",
            "The update installer could not be started. The application was not changed.",
        )
        return

    self._log_event(
        "updates.helper_launched",
        "Update helper launched",
        level=logging.INFO,
        version=plan.expected_version,
        target=str(plan.target_path),
        replacement=str(plan.replacement_path),
        backup=str(plan.backup_path),
        handoff=str(plan.handoff_path),
        log=str(plan.log_path),
    )
    self._update_install_handoff_in_progress = True
    _message_box().information(
        self,
        "Installing Update",
        "The update is ready. The application will close now and restart after installation.",
    )
    self._is_closing = True
    app = QApplication.instance()
    if app is not None:
        QTimer.singleShot(0, app.quit)
    else:
        self.close()


def _show_update_release_notes(self, manifest) -> None:
    if not getattr(manifest, "release_notes_url", ""):
        self._present_update_release_notes(manifest, "")
        return

    def _task(ctx):
        ctx.set_status("Loading release notes...")
        return _fetch_release_notes_text(
            manifest.release_notes_url,
            DEFAULT_RELEASE_NOTES_TIMEOUT_SECONDS,
        )

    def _success(release_notes_markdown):
        self._present_update_release_notes(manifest, str(release_notes_markdown or ""))

    def _error(failure: TaskFailure):
        self._log_event(
            "updates.release_notes_unavailable",
            "Release notes could not be loaded inside the app",
            level=logging.INFO,
            version=getattr(manifest, "version", ""),
            error=getattr(failure, "message", ""),
        )
        self._present_update_release_notes(manifest, "")

    task_id = self._submit_background_task(
        title="Release Notes",
        description="Loading release notes...",
        task_fn=_task,
        kind="network",
        unique_key="updates.release_notes",
        requires_profile=False,
        show_dialog=True,
        owner=self,
        on_success=_success,
        on_error=_error,
    )
    if task_id is None:
        self._present_update_release_notes(manifest, "")


def _present_update_release_notes(self, manifest, release_notes_markdown: str) -> None:
    install_available = False
    try:
        _select_platform_asset(manifest)
        install_available = True
    except UpdateInstallerError:
        install_available = False
    dialog = _root_attr("ReleaseNotesDialog", ReleaseNotesDialog)(
        version=getattr(manifest, "version", ""),
        released_at=getattr(manifest, "released_at", ""),
        summary=getattr(manifest, "summary", ""),
        release_notes_markdown=release_notes_markdown,
        release_notes_url=getattr(manifest, "release_notes_url", ""),
        allow_update_install=install_available,
        parent=self,
    )
    dialog.exec()
    if dialog.install_requested():
        self._confirm_and_start_update_install(manifest)
