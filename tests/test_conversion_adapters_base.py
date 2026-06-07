from __future__ import annotations

import pytest

from isrc_manager.conversion.adapters.base import SourceAdapter, TemplateAdapter


class _ContractTemplateAdapter(TemplateAdapter):
    format_name = "contract-template"

    def inspect_template(self, path):
        return super().inspect_template(path)

    def select_scope(self, profile, scope_key):
        return super().select_scope(profile, scope_key)

    def build_preview(self, profile, rendered_field_rows):
        return super().build_preview(profile, rendered_field_rows)

    def export_preview(self, preview, output_path, *, progress_callback=None):
        return super().export_preview(
            preview,
            output_path,
            progress_callback=progress_callback,
        )


class _ContractSourceAdapter(SourceAdapter):
    format_name = "contract-source"

    def inspect_source(self, source, *, preferred_csv_delimiter=None):
        return super().inspect_source(
            source,
            preferred_csv_delimiter=preferred_csv_delimiter,
        )

    def select_scope(self, profile, scope_key):
        return super().select_scope(profile, scope_key)


def test_template_adapter_base_methods_raise_not_implemented():
    adapter = _ContractTemplateAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_template("template.xlsx")
    with pytest.raises(NotImplementedError):
        adapter.select_scope(object(), "sheet")
    with pytest.raises(NotImplementedError):
        adapter.build_preview(object(), [])
    with pytest.raises(NotImplementedError):
        adapter.export_preview(object(), "out.xlsx", progress_callback=lambda *_args: None)


def test_source_adapter_base_methods_raise_not_implemented():
    adapter = _ContractSourceAdapter()

    with pytest.raises(NotImplementedError):
        adapter.inspect_source("source.csv", preferred_csv_delimiter=",")
    with pytest.raises(NotImplementedError):
        adapter.select_scope(object(), "sheet")
