"""Visual and generated-output qualification helpers for UI PQ."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QWidget

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class VisualCapture:
    name: str
    path: str
    width: int
    height: int
    sha256: str
    sample_count: int
    unique_sample_colors: int
    non_blank: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class QualificationComparison:
    name: str
    comparison_type: str
    actual_path: str
    baseline_path: str
    passed: bool
    baseline_created: bool
    reason: str
    actual_sha256: str
    baseline_sha256: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class VisualQualificationService:
    """Captures and compares visual/generated artifacts under a PQ artifact root."""

    def __init__(
        self,
        artifact_dir: Path | str,
        *,
        manifest_name: str = "visual_manifest.json",
    ) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.visual_dir = self.artifact_dir / "visual"
        self.screenshot_dir = self.visual_dir / "screenshots"
        self.actual_dir = self.visual_dir / "actual"
        self.baseline_dir = self.visual_dir / "baselines"
        self.manifest_path = self.visual_dir / _safe_name(manifest_name)
        for directory in (
            self.screenshot_dir,
            self.actual_dir,
            self.baseline_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.captures: list[VisualCapture] = []
        self.comparisons: list[QualificationComparison] = []

    def capture_widget(self, widget: QWidget, name: str) -> VisualCapture:
        safe_name = _safe_name(name)
        path = self.screenshot_dir / f"{safe_name}.png"
        widget.resize(max(widget.width(), 320), max(widget.height(), 240))
        widget.update()
        pixmap = widget.grab()
        if pixmap.isNull():
            raise AssertionError(f"Screenshot capture produced a null pixmap for {name!r}.")
        if not pixmap.save(str(path), "PNG"):
            raise AssertionError(f"Screenshot capture could not write {path}.")
        capture = _capture_from_image_file(safe_name, path)
        if not capture.non_blank:
            raise AssertionError(f"Screenshot capture appears blank for {name!r}: {path}")
        self.captures.append(capture)
        return capture

    def compare_capture_to_baseline(self, capture: VisualCapture) -> QualificationComparison:
        actual = Path(capture.path)
        baseline = self.baseline_dir / actual.name
        baseline_created = False
        if not baseline.exists():
            shutil.copy2(actual, baseline)
            baseline_created = True
        image_profile = _compare_image_files(actual, baseline)
        passed = bool(baseline_created or image_profile["passed"])
        comparison = QualificationComparison(
            name=capture.name,
            comparison_type="screenshot",
            actual_path=str(actual),
            baseline_path=str(baseline),
            passed=passed,
            baseline_created=baseline_created,
            reason=(
                "Baseline created from current qualified screenshot."
                if baseline_created
                else (
                    "Screenshot is visually within the baseline tolerance."
                    if passed
                    else "Screenshot differs beyond the baseline tolerance."
                )
            ),
            actual_sha256=_sha256_file(actual),
            baseline_sha256=_sha256_file(baseline),
            details={
                "capture": capture.to_dict(),
                "comparison_profile": image_profile,
            },
        )
        self.comparisons.append(comparison)
        if not comparison.passed:
            raise AssertionError(
                f"screenshot comparison failed for {capture.name!r}: "
                f"{actual} != {baseline}; profile={image_profile!r}"
            )
        return comparison

    def compare_text(
        self,
        name: str,
        text: str,
        *,
        extension: str = ".txt",
        comparison_type: str = "text",
    ) -> QualificationComparison:
        safe_name = _safe_name(name)
        suffix = extension if extension.startswith(".") else f".{extension}"
        actual_path = self.actual_dir / f"{safe_name}{suffix}"
        actual_path.write_text(_normalize_text(text), encoding="utf-8")
        return self.compare_file_to_baseline(
            name=safe_name,
            actual_path=actual_path,
            comparison_type=comparison_type,
            details={"normalized_bytes": actual_path.stat().st_size},
        )

    def compare_json_report(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        comparison_type: str = "report",
    ) -> QualificationComparison:
        stable_json = json.dumps(payload, indent=2, sort_keys=True)
        return self.compare_text(
            name,
            stable_json,
            extension=".json",
            comparison_type=comparison_type,
        )

    def render_pdf_report(
        self,
        name: str,
        *,
        title: str,
        lines: list[str],
    ) -> tuple[Path, dict[str, object]]:
        safe_name = _safe_name(name)
        pdf_path = self.actual_dir / f"{safe_name}.pdf"
        html_lines = "".join(f"<p>{_escape_html(line)}</p>" for line in lines)
        document = QTextDocument()
        document.setHtml(
            "<html><body>" f"<h1>{_escape_html(title)}</h1>" f"{html_lines}" "</body></html>"
        )
        writer = QPdfWriter(str(pdf_path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
        document.print_(writer)
        profile = inspect_pdf(pdf_path)
        if not profile["valid"]:
            raise AssertionError(f"Generated PDF did not pass structural validation: {profile!r}")
        return pdf_path, profile

    def compare_pdf_profile(
        self,
        name: str,
        pdf_path: Path,
        profile: dict[str, object] | None = None,
    ) -> QualificationComparison:
        stable_profile = dict(profile or inspect_pdf(pdf_path))
        stable_profile.pop("sha256", None)
        stable_profile.pop("size_bytes", None)
        return self.compare_json_report(
            f"{name}_pdf_profile",
            stable_profile,
            comparison_type="pdf_profile",
        )

    def compare_file_to_baseline(
        self,
        *,
        name: str,
        actual_path: Path,
        comparison_type: str,
        details: dict[str, object] | None = None,
    ) -> QualificationComparison:
        actual = Path(actual_path)
        if not actual.exists() or actual.stat().st_size <= 0:
            raise AssertionError(f"Actual comparison artifact is missing or empty: {actual}")
        baseline = self.baseline_dir / actual.name
        baseline_created = False
        if not baseline.exists():
            shutil.copy2(actual, baseline)
            baseline_created = True
        actual_sha = _sha256_file(actual)
        baseline_sha = _sha256_file(baseline)
        passed = actual_sha == baseline_sha
        comparison = QualificationComparison(
            name=_safe_name(name),
            comparison_type=comparison_type,
            actual_path=str(actual),
            baseline_path=str(baseline),
            passed=passed,
            baseline_created=baseline_created,
            reason=(
                "Baseline created from current qualified artifact."
                if baseline_created
                else ("Artifact matches baseline." if passed else "Artifact differs from baseline.")
            ),
            actual_sha256=actual_sha,
            baseline_sha256=baseline_sha,
            details=dict(details or {}),
        )
        self.comparisons.append(comparison)
        if not comparison.passed:
            raise AssertionError(
                f"{comparison_type} comparison failed for {name!r}: " f"{actual} != {baseline}"
            )
        return comparison

    def write_manifest(self) -> Path:
        payload = {
            "captures": [capture.to_dict() for capture in self.captures],
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
        }
        self.manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.manifest_path


def inspect_pdf(path: Path | str) -> dict[str, object]:
    pdf_path = Path(path)
    data = pdf_path.read_bytes()
    page_count = len(re.findall(rb"/Type\s*/Page\b", data))
    return {
        "valid": data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"),
        "starts_with_pdf_header": data.startswith(b"%PDF-"),
        "ends_with_eof": data.rstrip().endswith(b"%%EOF"),
        "page_count": page_count,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _capture_from_image_file(name: str, path: Path) -> VisualCapture:
    image = QImage(str(path))
    if image.isNull():
        raise AssertionError(f"Could not reload captured screenshot: {path}")
    sample_count, unique_colors = _sample_image_colors(image)
    return VisualCapture(
        name=name,
        path=str(path),
        width=image.width(),
        height=image.height(),
        sha256=_sha256_file(path),
        sample_count=sample_count,
        unique_sample_colors=len(unique_colors),
        non_blank=len(unique_colors) > 1,
    )


def _sample_image_colors(image: QImage) -> tuple[int, set[int]]:
    width = max(1, image.width())
    height = max(1, image.height())
    x_step = max(1, width // 16)
    y_step = max(1, height // 16)
    colors: set[int] = set()
    count = 0
    for y in range(0, height, y_step):
        for x in range(0, width, x_step):
            colors.add(int(image.pixelColor(x, y).rgba()))
            count += 1
    return count, colors


def _compare_image_files(actual_path: Path, baseline_path: Path) -> dict[str, object]:
    actual = QImage(str(actual_path))
    baseline = QImage(str(baseline_path))
    if actual.isNull() or baseline.isNull():
        return {
            "passed": False,
            "reason": "actual or baseline image could not be loaded",
        }
    same_size = actual.width() == baseline.width() and actual.height() == baseline.height()
    if not same_size:
        return {
            "passed": False,
            "reason": "image dimensions differ",
            "actual_width": actual.width(),
            "actual_height": actual.height(),
            "baseline_width": baseline.width(),
            "baseline_height": baseline.height(),
        }
    width = max(1, actual.width())
    height = max(1, actual.height())
    x_step = max(1, width // 32)
    y_step = max(1, height // 32)
    total_delta = 0
    changed_samples = 0
    sample_count = 0
    for y in range(0, height, y_step):
        for x in range(0, width, x_step):
            actual_color = actual.pixelColor(x, y)
            baseline_color = baseline.pixelColor(x, y)
            delta = (
                abs(actual_color.red() - baseline_color.red())
                + abs(actual_color.green() - baseline_color.green())
                + abs(actual_color.blue() - baseline_color.blue())
                + abs(actual_color.alpha() - baseline_color.alpha())
            )
            total_delta += delta
            changed_samples += int(delta > 0)
            sample_count += 1
    mean_channel_delta = total_delta / max(1, sample_count * 4)
    changed_sample_ratio = changed_samples / max(1, sample_count)
    passed = mean_channel_delta <= 6.0 and changed_sample_ratio <= 0.35
    return {
        "passed": passed,
        "same_size": same_size,
        "sample_count": sample_count,
        "changed_samples": changed_samples,
        "changed_sample_ratio": changed_sample_ratio,
        "mean_channel_delta": mean_channel_delta,
        "tolerance": {
            "max_mean_channel_delta": 6.0,
            "max_changed_sample_ratio": 0.35,
        },
    }


def _safe_name(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", str(value or "").strip()).strip("-._")
    return cleaned or "artifact"


def _normalize_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
