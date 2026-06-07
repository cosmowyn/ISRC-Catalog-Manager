import json
from zipfile import ZipFile

from openpyxl import Workbook

from isrc_manager.exchange.repertoire_service import (
    REPERTOIRE_JSON_SCHEMA_VERSION,
    RepertoireImportOptions,
    _stage_progress,
)
from tests.exchange._repertoire_exchange_support import SearchAndRepertoireExchangeTestCase


class RepertoireExchangeServiceTests(SearchAndRepertoireExchangeTestCase):
    test_repertoire_exchange_json_round_trip = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_json_round_trip
    )
    test_repertoire_exchange_json_round_trip_preserves_expanded_party_metadata = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_json_round_trip_preserves_expanded_party_metadata
    )
    test_repertoire_exchange_package_round_trip_preserves_files_and_document_chain = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_package_round_trip_preserves_files_and_document_chain
    )
    test_repertoire_import_skips_unresolved_catalog_release_links = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_import_skips_unresolved_catalog_release_links
    )
    test_repertoire_exchange_package_round_trip_preserves_database_backed_files = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_package_round_trip_preserves_database_backed_files
    )
    test_repertoire_exchange_xlsx_csv_and_schema_validation = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_exchange_xlsx_csv_and_schema_validation
    )
    test_repertoire_inspection_previews_counts_without_writing = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_inspection_previews_counts_without_writing
    )
    test_repertoire_export_reports_staged_progress = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_export_reports_staged_progress
    )
    test_repertoire_import_reports_staged_progress_to_completion = (
        SearchAndRepertoireExchangeTestCase.case_repertoire_import_reports_staged_progress_to_completion
    )

    def test_repertoire_payload_helper_edges_and_seeded_reference_resolution(self):
        ids = self._seed_repertoire()
        service = self.exchange_service

        self.assertEqual(_stage_progress(20, 40, 0, 0), 40)
        self.assertEqual(service._decode_value('{"nested": [1]}'), {"nested": [1]})
        self.assertEqual(service._decode_value("[1, 2]"), [1, 2])
        self.assertEqual(service._decode_value("{not-json"), "{not-json")
        self.assertEqual(service._decode_value("   "), "")
        self.assertEqual(
            service._normalize_source_id_map({"1": "2", "bad": "3", "4": "0"}),
            {1: 2},
        )
        self.assertEqual(service._normalized_id_map({"9": "10", "bad": "11"}), {9: 10})
        self.assertIsNone(
            service._resolve_mapped_entity_id(
                "not-int",
                mapped_ids={},
                table_name="Tracks",
            )
        )
        self.assertEqual(
            service._resolve_mapped_entity_id(
                "55",
                mapped_ids={55: ids["track_id"]},
                table_name="Tracks",
            ),
            ids["track_id"],
        )
        self.assertEqual(
            service._resolve_mapped_entity_id(
                ids["track_id"],
                mapped_ids={},
                table_name="Tracks",
            ),
            ids["track_id"],
        )
        self.assertIsNone(
            service._resolve_mapped_entity_id(
                "999999",
                mapped_ids={},
                table_name="Tracks",
            )
        )
        self.assertEqual(
            service._resolve_seeded_entity_id(
                "7",
                mapping={7: int(ids["track_id"])},
                table_name="Tracks",
                strict=True,
                entity_label="track",
            ),
            int(ids["track_id"]),
        )
        self.assertEqual(
            service._resolve_seeded_entity_id(
                ids["track_id"],
                mapping={},
                table_name="Tracks",
                strict=True,
                entity_label="track",
            ),
            int(ids["track_id"]),
        )
        self.assertIsNone(
            service._resolve_seeded_entity_id(
                "",
                mapping={},
                table_name="Tracks",
                strict=False,
                entity_label="track",
            )
        )
        self.assertIsNone(
            service._resolve_seeded_entity_id(
                "999999",
                mapping={},
                table_name="Tracks",
                strict=False,
                entity_label="track",
            )
        )
        self.assertIsNone(
            service._resolve_seeded_entity_id(
                "-1",
                mapping={},
                table_name="Tracks",
                strict=True,
                entity_label="track",
            )
        )
        with self.assertRaisesRegex(ValueError, "Invalid source track id"):
            service._resolve_seeded_entity_id(
                "not-int",
                mapping={},
                table_name="Tracks",
                strict=True,
                entity_label="track",
            )
        with self.assertRaisesRegex(ValueError, "could not be resolved"):
            service._resolve_seeded_entity_id(
                "999999",
                mapping={},
                table_name="Tracks",
                strict=True,
                entity_label="track",
            )

    def test_repertoire_inspection_reports_empty_missing_and_existing_rows(self):
        ids = self._seed_repertoire()
        existing_party = self.party_service.fetch_party(ids["label_party_id"])
        progress: list[tuple[int, str]] = []
        cancel_calls: list[str] = []

        inspection = self.exchange_service._inspect_payload(
            {
                "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                "parties": [
                    {"id": ids["label_party_id"], "legal_name": existing_party.legal_name},
                    {"id": 88, "display_name": "No Legal Name"},
                ],
                "works": [{"title": "Imported Work", "iswc": "T-111.222.333-4"}],
                "contracts": [{"title": "Imported Contract", "contract_type": "license"}],
                "rights": [{"title": "Imported Right", "right_type": "mechanical"}],
                "assets": [{"filename": "import.wav", "asset_type": "main_master"}],
            },
            file_path=self.data_root / "repertoire.json",
            format_name="json",
            progress_callback=lambda value, _maximum, message: progress.append((value, message)),
            cancel_callback=lambda: cancel_calls.append("checked"),
            warnings=["archive warning"],
        )

        self.assertEqual(inspection.existing_parties, 1)
        self.assertEqual(inspection.new_parties, 1)
        self.assertEqual(inspection.entity_counts["assets"], 1)
        self.assertIn("archive warning", inspection.warnings)
        self.assertTrue(
            any("does not include a legal name" in warning for warning in inspection.warnings)
        )
        self.assertEqual(inspection.preview_rows[0]["Action"], "Reuse Existing")
        self.assertTrue(cancel_calls)
        self.assertEqual(progress[-1], (100, "Contracts and Rights inspection complete."))

        empty = self.exchange_service._inspect_payload(
            {"schema_version": REPERTOIRE_JSON_SCHEMA_VERSION},
            file_path=self.data_root / "empty.json",
            format_name="json",
        )
        self.assertTrue(
            any("did not contain any importable rows" in warning for warning in empty.warnings)
        )
        with self.assertRaisesRegex(ValueError, "Unsupported repertoire schema version"):
            self.exchange_service._inspect_payload(
                {"schema_version": 0},
                file_path=self.data_root / "bad.json",
                format_name="json",
            )

    def test_repertoire_csv_and_json_input_helpers_cover_missing_sheets_and_schema_errors(self):
        bundle_dir = self.data_root / "csv-bundle"
        bundle_dir.mkdir()
        (bundle_dir / self.exchange_service.ENTITY_FILENAMES["parties"]).write_text(
            'id,legal_name,aliases\n1,CSV Party,"[""Alias""]"\n',
            encoding="utf-8",
        )

        rows = self.exchange_service._rows_from_csv_bundle(bundle_dir)

        self.assertEqual(rows["parties"][0]["legal_name"], "CSV Party")
        self.assertEqual(rows["works"], [])
        self.assertEqual(rows["contracts"], [])

        valid_json = self.data_root / "valid-repertoire.json"
        valid_json.write_text(
            json.dumps({"schema_version": REPERTOIRE_JSON_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        self.assertEqual(
            self.exchange_service._load_json_payload(valid_json)["schema_version"],
            REPERTOIRE_JSON_SCHEMA_VERSION,
        )

        invalid_json = self.data_root / "invalid-repertoire.json"
        invalid_json.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported repertoire JSON schema version"):
            self.exchange_service._load_json_payload(invalid_json)

        with self.assertRaisesRegex(ValueError, "Unsupported repertoire import phase"):
            self.exchange_service._import_payload(
                {"schema_version": REPERTOIRE_JSON_SCHEMA_VERSION},
                options=RepertoireImportOptions(phase="bad"),
            )
        with self.assertRaisesRegex(ValueError, "Unsupported repertoire schema version"):
            self.exchange_service._import_payload({"schema_version": 0})

    def test_repertoire_public_ingress_paths_report_cancel_and_package_mappings(self):
        json_path = self.data_root / "empty-repertoire.json"
        json_path.write_text(
            json.dumps({"schema_version": REPERTOIRE_JSON_SCHEMA_VERSION}),
            encoding="utf-8",
        )
        workbook_path = self.data_root / "empty-sheets.xlsx"
        workbook = Workbook()
        workbook.active.title = "Works"
        workbook.save(workbook_path)
        csv_dir = self.data_root / "csv-empty"
        csv_dir.mkdir()

        cancel_calls: list[str] = []
        progress_events: list[tuple[int, str]] = []

        def cancel() -> None:
            cancel_calls.append("checked")

        def progress(value: int, _maximum: int, message: str) -> None:
            progress_events.append((value, message))

        workbook_rows = self.exchange_service._rows_from_workbook(workbook_path)
        self.assertEqual(workbook_rows["works"], [])

        self.exchange_service.inspect_json(
            json_path,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        self.exchange_service.inspect_xlsx(
            workbook_path,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        self.exchange_service.inspect_csv_bundle(
            csv_dir,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        self.exchange_service.import_json(
            json_path,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        self.exchange_service.import_xlsx(
            workbook_path,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        self.exchange_service.import_csv_bundle(
            csv_dir,
            progress_callback=progress,
            cancel_callback=cancel,
        )

        package_path = self.data_root / "mapped-package.repertoire.zip"
        with ZipFile(package_path, "w") as archive:
            archive.writestr("files/contracts/doc.txt", "contract doc")
            archive.writestr("files/assets/audio.wav", b"RIFFaudio")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                        "parties": [],
                        "works": [],
                        "contracts": [
                            {
                                "id": 1,
                                "title": "Mapped Contract",
                                "documents": [
                                    {
                                        "id": 9,
                                        "title": "Mapped Doc",
                                        "file_path": "stored/doc.txt",
                                        "filename": "doc.txt",
                                    },
                                    {
                                        "id": 10,
                                        "title": "External Doc",
                                        "file_path": "not-packaged/doc.txt",
                                    },
                                ],
                            }
                        ],
                        "rights": [],
                        "assets": [
                            {
                                "id": 3,
                                "filename": "audio.wav",
                                "stored_path": "stored/audio.wav",
                            },
                            {
                                "id": 4,
                                "filename": "outside.wav",
                                "stored_path": "not-packaged/audio.wav",
                            },
                        ],
                        "packaged_files": {
                            "stored/doc.txt": "files/contracts/doc.txt",
                            "stored/audio.wav": "files/assets/audio.wav",
                        },
                    }
                ),
            )

        inspection = self.exchange_service.inspect_package(
            package_path,
            progress_callback=progress,
            cancel_callback=cancel,
        )
        result = self.exchange_service.import_package(
            package_path,
            options=RepertoireImportOptions(phase="parties_only"),
            progress_callback=progress,
            cancel_callback=cancel,
        )

        self.assertEqual(inspection.entity_counts["contracts"], 1)
        self.assertEqual(result.phase, "parties_only")
        self.assertGreaterEqual(len(cancel_calls), 9)
        self.assertTrue(
            any(
                "Parsing repertoire package manifest" in message
                for _value, message in progress_events
            )
        )

    def test_repertoire_package_export_omits_unreadable_documents_assets_and_lineage(self):
        package_path = self.data_root / "omissions.repertoire.zip"
        omitted: list[dict[str, str]] = []
        payload = {
            "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
            "parties": [],
            "works": [],
            "contracts": [
                {
                    "id": 10,
                    "title": "Broken Contract",
                    "documents": [
                        {"id": 0, "filename": "draft.txt", "file_path": ""},
                        {"id": 44, "filename": "missing.txt", "file_path": "missing/doc.txt"},
                    ],
                }
            ],
            "rights": [],
            "assets": [
                {"id": 0, "filename": "loose.wav", "stored_path": ""},
                {"id": 7, "filename": "missing.wav", "stored_path": "missing/asset.wav"},
                {
                    "id": 8,
                    "filename": "derived.wav",
                    "stored_path": "embedded/derived.wav",
                    "derived_from_asset_id": 7,
                },
            ],
        }

        with (
            self.subTest("strict failure"),
            self.assertRaisesRegex(ValueError, "could not resolve a file-backed source"),
        ):
            self.exchange_service.export_payload = lambda **_kwargs: payload
            self.exchange_service.export_package(package_path)

        self.exchange_service.export_payload = lambda **_kwargs: json.loads(json.dumps(payload))
        self.contract_service.resolve_document_path = lambda _path: None
        self.contract_service.fetch_document_bytes = lambda _document_id: (_ for _ in ()).throw(
            FileNotFoundError("document gone")
        )
        self.asset_service.resolve_asset_path = lambda _path: None

        def fetch_asset_bytes(asset_id):
            if int(asset_id) == 8:
                return b"derived-audio", "audio/wav"
            raise FileNotFoundError("asset gone")

        self.asset_service.fetch_asset_bytes = fetch_asset_bytes

        self.exchange_service.export_package(
            package_path,
            continue_on_item_errors=True,
            omission_callback=omitted.append,
        )

        with ZipFile(package_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            names = set(archive.namelist())

        self.assertEqual(len(manifest["contracts"][0]["documents"]), 0)
        self.assertEqual([asset["id"] for asset in manifest["assets"]], [8])
        self.assertIsNone(manifest["assets"][0]["derived_from_asset_id"])
        self.assertIn("files/assets/8_derived.wav", names)
        self.assertTrue(any(item["item_type"] == "contract_document" for item in omitted))
        self.assertTrue(any(item["item_type"] == "asset" for item in omitted))
        self.assertTrue(any(item["item_type"] == "asset_lineage_reference" for item in omitted))

        inspect_path = self.data_root / "broken-manifest.repertoire.zip"
        with ZipFile(inspect_path, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                        "contracts": [
                            {
                                "documents": [
                                    {
                                        "id": 1,
                                        "file_path": "docs/missing.txt",
                                        "filename": "missing.txt",
                                    }
                                ]
                            }
                        ],
                        "assets": [
                            {
                                "id": 2,
                                "stored_path": "assets/missing.wav",
                                "filename": "missing.wav",
                            }
                        ],
                        "packaged_files": {
                            "docs/missing.txt": "files/contracts/missing.txt",
                            "assets/missing.wav": "files/assets/missing.wav",
                        },
                    }
                ),
            )

        inspection = self.exchange_service.inspect_package(inspect_path)
        self.assertTrue(any("contract document" in warning for warning in inspection.warnings))
        self.assertTrue(any("asset file" in warning for warning in inspection.warnings))

    def test_repertoire_remaining_import_reuses_seeded_links_and_warns_for_optional_refs(self):
        ids = self._seed_repertoire()
        payload = {
            "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
            "parties": [],
            "works": [
                {
                    "id": 101,
                    "title": "Midnight Circuit",
                    "iswc": "T-222.333.444-5",
                    "registration_number": "REG-NEW",
                    "track_ids": [901, 902],
                    "contributors": [
                        {
                            "role": "songwriter",
                            "display_name": "Unknown Writer",
                            "party_id": ids["label_party_id"],
                        }
                    ],
                }
            ],
            "contracts": [
                {
                    "id": 201,
                    "title": "Unmapped Links",
                    "contract_type": "license",
                    "parties": [
                        {"party_id": ids["label_party_id"], "role_label": "label"},
                    ],
                    "track_ids": [902],
                    "release_ids": [903],
                }
            ],
            "rights": [
                {
                    "id": 301,
                    "title": "Optional Right",
                    "right_type": "master",
                    "track_id": 901,
                    "release_id": 903,
                }
            ],
            "assets": [
                {
                    "id": 401,
                    "filename": "optional.wav",
                    "asset_type": "main_master",
                    "track_id": 901,
                    "release_id": 903,
                }
            ],
        }

        result = self.exchange_service._import_payload(
            payload,
            options=RepertoireImportOptions(
                phase="remaining",
                source_party_id_map={},
                source_track_id_map={901: ids["track_id"], "bad": ids["track_id"]},
                source_release_id_map={},
            ),
        )

        self.assertEqual(result.imported_works, 1)
        self.assertEqual(result.source_work_id_map["101"], ids["work_id"])
        self.assertEqual(result.imported_contracts, 1)
        self.assertEqual(result.imported_rights, 1)
        self.assertEqual(result.imported_assets, 1)
        self.assertTrue(any("track reference 902" in warning for warning in result.warnings))
        self.assertTrue(any("release reference 903" in warning for warning in result.warnings))

    def test_repertoire_import_fails_loudly_for_required_unresolved_references(self):
        ids = self._seed_repertoire()
        cases = [
            (
                "contract work",
                {
                    "contracts": [
                        {
                            "id": 1,
                            "title": "Broken Work Link",
                            "work_ids": [404],
                        }
                    ]
                },
                "Work reference 404",
            ),
            (
                "contract supersedes",
                {
                    "contracts": [
                        {
                            "id": 1,
                            "title": "Broken Contract Link",
                            "supersedes_contract_id": 404,
                        }
                    ]
                },
                "Contract supersession reference 404",
            ),
            (
                "contract superseded by",
                {
                    "contracts": [
                        {
                            "id": 1,
                            "title": "Broken Reverse Contract Link",
                            "superseded_by_contract_id": 405,
                        }
                    ]
                },
                "Contract supersession reference 405",
            ),
            (
                "right contract",
                {
                    "rights": [
                        {
                            "id": 1,
                            "title": "Broken Right Contract",
                            "source_contract_id": 406,
                        }
                    ]
                },
                "Contract reference 406",
            ),
            (
                "right work",
                {
                    "rights": [
                        {
                            "id": 1,
                            "title": "Broken Right Work",
                            "work_id": 407,
                        }
                    ]
                },
                "Work reference 407",
            ),
            (
                "asset derivation",
                {
                    "assets": [
                        {
                            "id": 1,
                            "filename": "derived.wav",
                            "track_id": ids["track_id"],
                            "derived_from_asset_id": 408,
                        }
                    ]
                },
                "Asset derivation reference 408",
            ),
        ]

        for label, fragment, message in cases:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, message):
                payload = {
                    "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                    "parties": [],
                    "works": [],
                    "contracts": [],
                    "rights": [],
                    "assets": [],
                }
                payload.update(fragment)
                self.exchange_service._import_payload(
                    payload,
                    options=RepertoireImportOptions(phase="remaining"),
                )

        with self.assertRaisesRegex(ValueError, "Invalid source track id"):
            self.exchange_service._import_payload(
                {
                    "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                    "works": [{"id": 1, "title": "Bad Track", "track_ids": ["bad"]}],
                },
                options=RepertoireImportOptions(phase="remaining"),
            )

        result = self.exchange_service._import_payload(
            {
                "schema_version": REPERTOIRE_JSON_SCHEMA_VERSION,
                "contracts": [
                    {
                        "id": 2,
                        "title": "Missing Optional Party",
                        "parties": [{"party_id": 999, "role_label": "missing"}],
                    }
                ],
            }
        )
        self.assertEqual(result.imported_contracts, 1)


del SearchAndRepertoireExchangeTestCase
