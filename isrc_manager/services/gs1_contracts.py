"""Contract CSV import for GS1 GTIN number ranges."""

from __future__ import annotations

import csv
from pathlib import Path

from .gs1_mapping import normalize_gs1_text
from .gs1_models import GS1ContractEntry, GS1ContractImportError


class GS1ContractImportService:
    """Parses exported GS1 contract CSV files and keeps only GTIN-capable contracts."""

    HEADER_ALIASES = {
        "contract_number": ("contractnummer", "contract number"),
        "product": ("product", "contract product"),
        "company_number": ("bedrijfsnummer", "company number", "company prefix"),
        "start_number": ("startnummer", "start number", "gtin start"),
        "end_number": ("eindnummer", "end number", "gtin end"),
        "renewal_date": ("verlengingsdatum", "renewal date"),
        "end_date": ("einddatum", "end date"),
        "status": ("status",),
        "tier": ("staffel", "tier"),
    }

    def load_contracts(self, csv_path: str | Path) -> tuple[GS1ContractEntry, ...]:
        path = Path(csv_path)
        if not path.exists():
            raise GS1ContractImportError(f"The selected GS1 contracts file was not found:\n{path}")
        if path.suffix.lower() != ".csv":
            raise GS1ContractImportError("Choose the GS1 contracts export as a .csv file.")

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = [str(name or "").strip() for name in (reader.fieldnames or [])]
                if not any(fieldnames):
                    raise GS1ContractImportError(
                        "The selected file does not contain recognizable CSV headers."
                    )
                header_map = self._resolve_header_map(fieldnames)
                contracts = [
                    entry
                    for row in reader
                    if (entry := self._entry_from_row(row, header_map)) is not None
                ]
        except UnicodeDecodeError as exc:
            raise GS1ContractImportError(
                "The selected GS1 contracts CSV could not be decoded as text."
            ) from exc
        except OSError as exc:
            raise GS1ContractImportError(
                f"The selected GS1 contracts CSV could not be read:\n{exc}"
            ) from exc

        if not contracts:
            raise GS1ContractImportError(
                "No GTIN contract ranges were found in the selected CSV. Export the contracts list from your GS1 portal "
                "and choose the file that contains contract numbers with GTIN start and end values."
            )

        return tuple(
            sorted(
                contracts,
                key=lambda entry: (
                    0 if entry.is_active else 1,
                    self._sortable_contract_number(entry.contract_number),
                    entry.contract_number,
                ),
            )
        )

    def _resolve_header_map(self, fieldnames: list[str]) -> dict[str, str]:
        header_map: dict[str, str] = {}
        for canonical_name, aliases in self.HEADER_ALIASES.items():
            for fieldname in fieldnames:
                normalized = normalize_gs1_text(fieldname)
                if normalized in aliases:
                    header_map[canonical_name] = fieldname
                    break
        if "contract_number" not in header_map:
            raise GS1ContractImportError(
                "The selected CSV does not include a recognizable contract-number column."
            )
        return header_map

    def _entry_from_row(
        self, row: dict[str, object], header_map: dict[str, str]
    ) -> GS1ContractEntry | None:
        contract_number = self._value(row, header_map, "contract_number")
        if not contract_number:
            return None

        start_number = self._digits_only(self._value(row, header_map, "start_number"))
        end_number = self._digits_only(self._value(row, header_map, "end_number"))
        if not start_number or not end_number:
            return None

        return GS1ContractEntry(
            contract_number=contract_number,
            product=self._value(row, header_map, "product"),
            company_number=self._digits_only(self._value(row, header_map, "company_number")),
            start_number=start_number,
            end_number=end_number,
            renewal_date=self._value(row, header_map, "renewal_date"),
            end_date=self._value(row, header_map, "end_date"),
            status=self._value(row, header_map, "status"),
            tier=self._value(row, header_map, "tier"),
        )

    @staticmethod
    def _value(row: dict[str, object], header_map: dict[str, str], canonical_name: str) -> str:
        column_name = header_map.get(canonical_name)
        if not column_name:
            return ""
        return str(row.get(column_name) or "").strip()

    @staticmethod
    def _digits_only(value: str) -> str:
        return "".join(ch for ch in str(value or "").strip() if ch.isdigit())

    @staticmethod
    def _sortable_contract_number(contract_number: str) -> tuple[int, str]:
        digits = "".join(ch for ch in str(contract_number or "").strip() if ch.isdigit())
        if digits:
            return int(digits), digits
        return 10**18, str(contract_number or "").strip()
