"""Promo-code ledger workflow orchestration for the application shell."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QDockWidget, QMessageBox, QWidget

from isrc_manager.catalog_workspace import ensure_catalog_workspace_dock
from isrc_manager.promo_codes import PromoCodeLedgerPanel, PromoCodeService
from isrc_manager.tasks.history_helpers import run_snapshot_history_action


def _root_attr(name: str, fallback):
    main_window_module = sys.modules.get("isrc_manager.main_window")
    return (
        getattr(main_window_module, name, fallback)
        if main_window_module is not None
        else fallback
    )


def _message_box():
    return _root_attr("QMessageBox", QMessageBox)


def _run_snapshot_history_action(*args, **kwargs):
    return _root_attr("run_snapshot_history_action", run_snapshot_history_action)(*args, **kwargs)


def _create_promo_code_ledger_panel(self, parent: QWidget) -> PromoCodeLedgerPanel:
    return _root_attr("PromoCodeLedgerPanel", PromoCodeLedgerPanel)(
        service_provider=lambda: self.promo_code_service,
        import_handler=self.import_bandcamp_promo_codes,
        ledger_update_handler=self.update_promo_code_ledger,
        parent=parent,
    )


def _ensure_promo_code_ledger_dock(self) -> QDockWidget:
    dock = ensure_catalog_workspace_dock(
        self,
        key="promo_code_ledger",
        title="Promo Code Ledger",
        object_name="promoCodeLedgerDock",
        panel_factory=self._create_promo_code_ledger_panel,
    )
    self.promo_code_ledger_dock = dock
    return dock


def open_promo_code_ledger(self, sheet_id: int | None = None):
    if self.promo_code_service is None:
        _message_box().warning(self, "Promo Code Ledger", "Open a profile first.")
        return

    def _configure(panel) -> None:
        panel.refresh()
        panel.focus_sheet(sheet_id)

    return self._show_workspace_panel(
        self._ensure_promo_code_ledger_dock,
        panel_attr="promo_code_ledger_panel",
        configure=_configure,
    )


def import_bandcamp_promo_codes(
    self,
    path: str,
    owner: QWidget | None = None,
    on_success=None,
):
    if not str(path or "").strip():
        return None
    if self.promo_code_service is None:
        _message_box().warning(self, "Promo Code Ledger", "Open a profile first.")
        return None
    resolved_path = str(Path(path))
    profile_name = self._current_profile_name()

    def _worker(bundle, ctx):
        service = PromoCodeService(bundle.conn)
        ctx.report_progress(
            value=0,
            maximum=100,
            message="Importing or updating Bandcamp promo-code sheet...",
        )
        import_progress = self._scaled_progress_callback(
            ctx.report_progress,
            start=2,
            end=48,
        )
        result = _run_snapshot_history_action(
            history_manager=bundle.history_manager,
            action_label=f"Import or Update Promo Codes: {Path(resolved_path).name}",
            action_type="promo_codes.import",
            entity_type="PromoCodeSheet",
            entity_id=Path(resolved_path).name,
            payload={
                "source_path": resolved_path,
                "profile_name": profile_name,
            },
            mutation=lambda: service.import_bandcamp_csv(
                resolved_path,
                profile_name=profile_name,
                progress_callback=import_progress,
            ),
            progress_callback=ctx.report_progress,
            post_mutation_progress=(62, "Capturing promo-code import history snapshot..."),
            record_progress=(72, "Recording promo-code import history..."),
            logger=self.logger,
        )
        ctx.report_progress(
            value=86,
            maximum=100,
            message="Promo-code import history recorded.",
        )
        return result

    def _before_cleanup(result, ui_progress) -> None:
        try:
            if self.conn is not None:
                self.conn.commit()
        except Exception:
            pass
        self._refresh_history_actions()
        self._advance_task_ui_progress(
            ui_progress,
            value=100,
            message="Promo-code ledger is ready.",
        )

    def _after_cleanup(result) -> None:
        self._log_event(
            "promo_codes.import",
            "Imported or updated Bandcamp promo-code sheet",
            sheet_id=getattr(result, "sheet_id", None),
            sheet_name=getattr(result, "sheet_name", ""),
            source_path=resolved_path,
            inserted_codes=getattr(result, "inserted_codes", None),
            active_codes=getattr(result, "active_codes", None),
            marked_redeemed_codes=getattr(result, "marked_redeemed_codes", None),
            reactivated_codes=getattr(result, "reactivated_codes", None),
            updated_existing_sheet=getattr(result, "updated_existing_sheet", False),
        )
        if callable(on_success):
            on_success(result)
        sheet_name = str(getattr(result, "sheet_name", "") or "promo-code sheet")
        inserted = int(getattr(result, "inserted_codes", 0) or 0)
        if bool(getattr(result, "updated_existing_sheet", False)):
            active = int(getattr(result, "active_codes", 0) or 0)
            marked = int(getattr(result, "marked_redeemed_codes", 0) or 0)
            reactivated = int(getattr(result, "reactivated_codes", 0) or 0)
            self.statusBar().showMessage(
                "Updated promo-code sheet: "
                f"{sheet_name} ({active} active, {marked} marked redeemed, "
                f"{reactivated} reactivated)",
                5000,
            )
        else:
            self.statusBar().showMessage(
                f"Imported promo-code sheet: {sheet_name} ({inserted} code(s))",
                5000,
            )

    return self._submit_background_bundle_task(
        title="Import or Update Promo Codes",
        description="Importing or updating Bandcamp promo-code CSV...",
        task_fn=_worker,
        kind="write",
        unique_key=f"promo_codes.import.{resolved_path}",
        owner=owner or self,
        worker_completion_progress=(96, "Finalizing promo-code import..."),
        on_success_before_cleanup=_before_cleanup,
        on_success_after_cleanup=_after_cleanup,
        on_error=lambda failure: self._show_background_task_error(
            "Promo Code Ledger",
            failure,
            user_message="Could not import the Bandcamp promo-code CSV:",
        ),
    )


def update_promo_code_ledger(
    self,
    code_id: int,
    redeemed: bool,
    recipient_name: str | None = None,
    recipient_email: str | None = None,
    ledger_notes: str | None = None,
):
    if self.promo_code_service is None:
        raise ValueError("Promo code service is unavailable.")
    before = self.promo_code_service.fetch_code(int(code_id))
    if before is None:
        raise ValueError("Promo code not found.")
    status_label = "Redeemed" if bool(redeemed) else "Available"

    def mutation():
        return self.promo_code_service.update_code_ledger(
            int(code_id),
            redeemed=bool(redeemed),
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            ledger_notes=ledger_notes,
        )

    updated = self.__run_snapshot_history_action(
        action_label=f"Update Promo Code Ledger: {before.code}",
        action_type="promo_codes.ledger.update",
        entity_type="PromoCode",
        entity_id=int(code_id),
        payload={
            "code_id": int(code_id),
            "code": before.code,
            "sheet_id": int(before.sheet_id),
            "redeemed": bool(redeemed),
            "status": status_label,
        },
        mutation=mutation,
    )
    self._refresh_promo_code_ledger_panel()
    return updated


def _refresh_promo_code_ledger_panel(self) -> None:
    seen_panel_ids: set[int] = set()
    candidates = [getattr(self, "promo_code_ledger_panel", None)]
    dock = getattr(self, "promo_code_ledger_dock", None)
    if dock is not None:
        try:
            candidates.append(dock.widget())
        except Exception:
            pass
    for panel in candidates:
        if panel is None:
            continue
        panel_id = id(panel)
        if panel_id in seen_panel_ids:
            continue
        seen_panel_ids.add(panel_id)
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            refresh()
