import sqlite3
import tempfile
import unittest
from pathlib import Path

from isrc_manager.services import (
    ContractTemplateDraftPayload,
    ContractTemplateOutputArtifactPayload,
    ContractTemplatePayload,
    ContractTemplatePlaceholderBindingPayload,
    ContractTemplatePlaceholderPayload,
    ContractTemplateResolvedSnapshotPayload,
    ContractTemplateRevisionPayload,
    ContractTemplateService,
    DatabaseSchemaService,
)


class ContractTemplateServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.schema = DatabaseSchemaService(self.conn, data_root=self.root)
        self.schema.init_db()
        self.schema.migrate_schema()
        self.service = ContractTemplateService(self.conn, data_root=self.root)

    def tearDown(self):
        self.conn.close()
        self.tmpdir.cleanup()

    def _create_template(self):
        return self.service.create_template(
            ContractTemplatePayload(
                name="Artist Agreement",
                description="Phase 1 template scaffold",
                template_family="contract",
                source_format="docx",
            )
        )

    def _create_revision(self, *, storage_mode="database"):
        template = self._create_template()
        revision = self.service.add_revision_from_bytes(
            template.template_id,
            b"phase1-template-source",
            payload=ContractTemplateRevisionPayload(
                source_filename="artist-agreement.docx",
                source_format="docx",
                storage_mode=storage_mode,
            ),
            placeholders=[
                ContractTemplatePlaceholderPayload(
                    canonical_symbol="{{db.track.track_title}}",
                    source_occurrence_count=2,
                ),
                ContractTemplatePlaceholderPayload(
                    canonical_symbol="{{manual.license_date}}",
                    inferred_field_type="date",
                ),
            ],
            bindings=[
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{db.track.track_title}}",
                    resolver_kind="db",
                    resolver_target="Tracks.track_title",
                    scope_entity_type="track",
                    scope_policy="required",
                    widget_hint="picker",
                ),
                ContractTemplatePlaceholderBindingPayload(
                    canonical_symbol="{{manual.license_date}}",
                    resolver_kind="manual",
                    widget_hint="date",
                    validation={"required": True},
                ),
            ],
        )
        return template, revision

    def _create_snapshot(self, draft_id: int, revision_id: int):
        return self.service.create_resolved_snapshot(
            ContractTemplateResolvedSnapshotPayload(
                draft_id=draft_id,
                revision_id=revision_id,
                resolved_values={"track_title": "First Song", "license_date": "2026-03-25"},
                resolution_warnings=["manual.license_date supplied manually"],
                preview_payload={"page_count": 2},
                scope_entity_type="track",
                scope_entity_id="1",
            )
        )

    def test_template_create_list_fetch_and_archive_flow(self):
        template = self._create_template()

        fetched = self.service.fetch_template(template.template_id)
        listed = self.service.list_templates()
        archived = self.service.archive_template(template.template_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Artist Agreement")
        self.assertEqual([item.template_id for item in listed], [template.template_id])
        self.assertTrue(archived.archived)
        self.assertEqual(self.service.list_templates(), [])
        self.assertEqual(
            [item.template_id for item in self.service.list_templates(include_archived=True)],
            [template.template_id],
        )

    def test_duplicate_template_copies_revisions_placeholders_and_bindings(self):
        template, revision = self._create_revision(storage_mode="managed_file")

        duplicated = self.service.duplicate_template(template.template_id)
        duplicated_revisions = self.service.list_revisions(duplicated.template_id)
        duplicated_placeholders = self.service.list_placeholders(
            duplicated_revisions[0].revision_id
        )
        duplicated_bindings = self.service.list_placeholder_bindings(
            duplicated_revisions[0].revision_id
        )

        self.assertNotEqual(duplicated.template_id, template.template_id)
        self.assertEqual(duplicated.name, "Artist Agreement Copy")
        self.assertEqual(len(duplicated_revisions), 1)
        self.assertEqual(duplicated.active_revision_id, duplicated_revisions[0].revision_id)
        self.assertEqual(
            self.service.load_revision_source_bytes(duplicated_revisions[0].revision_id),
            b"phase1-template-source",
        )
        self.assertEqual(
            [item.canonical_symbol for item in duplicated_placeholders],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )
        self.assertEqual(
            [item.resolver_kind for item in duplicated_bindings],
            ["db", "manual"],
        )

    def test_revision_database_storage_round_trip_with_placeholder_inventory(self):
        template, revision = self._create_revision(storage_mode="database")

        self.assertTrue(revision.stored_in_database)
        self.assertEqual(revision.storage_mode, "database")
        self.assertEqual(revision.placeholder_count, 2)
        self.assertEqual(
            self.service.fetch_template(template.template_id).active_revision_id,
            revision.revision_id,
        )
        self.assertEqual(
            self.service.load_revision_source_bytes(revision.revision_id),
            b"phase1-template-source",
        )

        placeholders = self.service.list_placeholders(revision.revision_id)
        bindings = self.service.list_placeholder_bindings(revision.revision_id)

        self.assertEqual(
            [item.canonical_symbol for item in placeholders],
            ["{{db.track.track_title}}", "{{manual.license_date}}"],
        )
        self.assertEqual(placeholders[0].source_occurrence_count, 2)
        self.assertEqual(bindings[0].resolver_kind, "db")
        self.assertEqual(bindings[1].widget_hint, "date")

    def test_revision_managed_file_storage_round_trip(self):
        template = self._create_template()
        source_path = self.root / "managed-artist-agreement.docx"
        source_path.write_bytes(b"managed-phase1-template")

        revision = self.service.add_revision_from_path(
            template.template_id,
            source_path,
            payload=ContractTemplateRevisionPayload(storage_mode="managed_file"),
        )

        self.assertFalse(revision.stored_in_database)
        self.assertEqual(revision.storage_mode, "managed_file")
        self.assertTrue(str(revision.managed_file_path).startswith("contract_template_sources/"))
        self.assertEqual(
            self.service.load_revision_source_bytes(revision.revision_id),
            b"managed-phase1-template",
        )

    def test_draft_database_storage_round_trip(self):
        _, revision = self._create_revision(storage_mode="database")

        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Draft A",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )

        self.assertTrue(draft.stored_in_database)
        self.assertEqual(
            self.service.fetch_draft_payload(draft.draft_id),
            {"manual_values": {"license_date": "2026-03-25"}},
        )

    def test_draft_managed_file_storage_round_trip(self):
        _, revision = self._create_revision(storage_mode="database")

        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Draft Managed",
                editable_payload={"selection": {"track_id": 7}},
                storage_mode="managed_file",
            )
        )

        self.assertFalse(draft.stored_in_database)
        self.assertTrue(str(draft.managed_file_path).startswith("contract_template_drafts/"))
        self.assertEqual(
            self.service.fetch_draft_payload(draft.draft_id),
            {"selection": {"track_id": 7}},
        )

    def test_list_drafts_can_filter_by_revision(self):
        template = self._create_template()
        revision_one = self.service.add_revision_from_bytes(
            template.template_id,
            b"revision-one",
            payload=ContractTemplateRevisionPayload(
                source_filename="artist-agreement-v1.docx",
                source_format="docx",
                storage_mode="database",
            ),
        )
        revision_two = self.service.add_revision_from_bytes(
            template.template_id,
            b"revision-two",
            payload=ContractTemplateRevisionPayload(
                source_filename="artist-agreement-v2.docx",
                source_format="docx",
                storage_mode="database",
            ),
        )
        draft_one = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision_one.revision_id,
                name="Revision One Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )
        draft_two = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision_two.revision_id,
                name="Revision Two Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-26"}},
                storage_mode="managed_file",
            )
        )

        self.assertEqual(
            [
                item.draft_id
                for item in self.service.list_drafts(revision_id=revision_one.revision_id)
            ],
            [draft_one.draft_id],
        )
        self.assertEqual(
            [
                item.draft_id
                for item in self.service.list_drafts(revision_id=revision_two.revision_id)
            ],
            [draft_two.draft_id],
        )

    def test_revision_storage_mode_conversion_preserves_bytes_and_metadata(self):
        _, revision = self._create_revision(storage_mode="database")

        converted = self.service.convert_revision_storage_mode(revision.revision_id, "managed_file")
        reverted = self.service.convert_revision_storage_mode(revision.revision_id, "database")

        self.assertEqual(converted.storage_mode, "managed_file")
        self.assertEqual(converted.source_filename, "artist-agreement.docx")
        self.assertEqual(converted.placeholder_count, 2)
        self.assertEqual(
            self.service.load_revision_source_bytes(revision.revision_id),
            b"phase1-template-source",
        )
        self.assertEqual(reverted.storage_mode, "database")
        self.assertEqual(reverted.placeholder_count, 2)

    def test_draft_storage_mode_conversion_preserves_payload_and_metadata(self):
        _, revision = self._create_revision(storage_mode="database")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Convertible Draft",
                editable_payload={"manual_values": {"batch_label": "Spring-2026"}},
                storage_mode="database",
            )
        )

        converted = self.service.convert_draft_storage_mode(draft.draft_id, "managed_file")
        reverted = self.service.convert_draft_storage_mode(draft.draft_id, "database")

        self.assertEqual(converted.storage_mode, "managed_file")
        self.assertEqual(converted.name, "Convertible Draft")
        self.assertEqual(
            self.service.fetch_draft_payload(draft.draft_id),
            {"manual_values": {"batch_label": "Spring-2026"}},
        )
        self.assertEqual(reverted.storage_mode, "database")
        self.assertEqual(reverted.name, "Convertible Draft")

    def test_update_draft_reuses_existing_row_across_storage_modes(self):
        _, revision = self._create_revision(storage_mode="database")
        original = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Reusable Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )

        updated_managed = self.service.update_draft(
            original.draft_id,
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Reusable Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-26"}},
                storage_mode="managed_file",
            ),
        )
        self.assertEqual(updated_managed.draft_id, original.draft_id)
        self.assertEqual(
            [item.draft_id for item in self.service.list_drafts(revision_id=revision.revision_id)],
            [original.draft_id],
        )
        self.assertEqual(updated_managed.storage_mode, "managed_file")
        self.assertFalse(updated_managed.stored_in_database)
        self.assertTrue(
            str(updated_managed.managed_file_path).startswith("contract_template_drafts/")
        )
        self.assertEqual(
            self.service.fetch_draft_payload(original.draft_id),
            {"manual_values": {"license_date": "2026-03-26"}},
        )

        updated_database = self.service.update_draft(
            original.draft_id,
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Reusable Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-27"}},
                storage_mode="database",
            ),
        )
        self.assertEqual(updated_database.draft_id, original.draft_id)
        self.assertEqual(
            [item.draft_id for item in self.service.list_drafts(revision_id=revision.revision_id)],
            [original.draft_id],
        )
        self.assertEqual(updated_database.storage_mode, "database")
        self.assertTrue(updated_database.stored_in_database)
        self.assertFalse(updated_database.managed_file_path)
        self.assertEqual(
            self.service.fetch_draft_payload(original.draft_id),
            {"manual_values": {"license_date": "2026-03-27"}},
        )

    def test_archive_draft_hides_record_from_default_listings(self):
        template, revision = self._create_revision(storage_mode="database")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Archive Me",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )

        archived = self.service.archive_draft(draft.draft_id, archived=True)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(
            self.service.list_drafts(revision_id=revision.revision_id),
            [],
        )
        restored = self.service.archive_draft(draft.draft_id, archived=False)
        self.assertEqual(
            [item.draft_id for item in self.service.list_template_drafts(template.template_id)],
            [restored.draft_id],
        )
        self.assertEqual(restored.status, "draft")

    def test_delete_output_artifact_can_remove_record_only_or_record_and_file(self):
        _, revision = self._create_revision(storage_mode="database")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Artifact Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )
        snapshot = self._create_snapshot(draft.draft_id, revision.revision_id)
        record_only_rel = self.service.artifact_store.write_bytes(
            b"%PDF-record-only",
            filename="record-only.pdf",
            subdir="tests",
        )
        record_only_path = self.service.artifact_store.resolve(record_only_rel)
        artifact_one = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(record_only_path),
                output_filename="record-only.pdf",
                mime_type="application/pdf",
                size_bytes=len(b"%PDF-record-only"),
            )
        )
        remove_file_rel = self.service.artifact_store.write_bytes(
            b"%PDF-remove-file",
            filename="remove-file.pdf",
            subdir="tests",
        )
        remove_file_path = self.service.artifact_store.resolve(remove_file_rel)
        artifact_two = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(remove_file_path),
                output_filename="remove-file.pdf",
                mime_type="application/pdf",
                size_bytes=len(b"%PDF-remove-file"),
            )
        )

        self.service.delete_output_artifact(artifact_one.artifact_id, remove_file=False)
        self.service.delete_output_artifact(artifact_two.artifact_id, remove_file=True)

        self.assertIsNone(self.service.fetch_output_artifact(artifact_one.artifact_id))
        self.assertIsNone(self.service.fetch_output_artifact(artifact_two.artifact_id))
        self.assertTrue(record_only_path.exists())
        self.assertFalse(remove_file_path.exists())

    def test_delete_draft_can_remove_managed_payload_and_output_files(self):
        _, revision = self._create_revision(storage_mode="database")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Delete Managed Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="managed_file",
            )
        )
        snapshot = self._create_snapshot(draft.draft_id, revision.revision_id)
        artifact_rel = self.service.artifact_store.write_bytes(
            b"%PDF-delete-draft",
            filename="delete-draft.pdf",
            subdir="tests",
        )
        artifact_path = self.service.artifact_store.resolve(artifact_rel)
        self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path),
                output_filename="delete-draft.pdf",
                mime_type="application/pdf",
                size_bytes=len(b"%PDF-delete-draft"),
            )
        )
        payload_path = self.service.draft_store.resolve(draft.managed_file_path)

        self.service.delete_draft(
            draft.draft_id,
            remove_managed_payload=True,
            remove_output_files=True,
        )

        self.assertIsNone(self.service.fetch_draft(draft.draft_id))
        self.assertFalse(payload_path.exists())
        self.assertFalse(artifact_path.exists())
        self.assertEqual(
            self.service.list_resolved_snapshots(draft_id=draft.draft_id),
            [],
        )

    def test_delete_template_can_remove_managed_source_draft_and_artifact_files(self):
        template, revision = self._create_revision(storage_mode="managed_file")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Template Delete Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="managed_file",
            )
        )
        snapshot = self._create_snapshot(draft.draft_id, revision.revision_id)
        artifact_rel = self.service.artifact_store.write_bytes(
            b"%PDF-delete-template",
            filename="delete-template.pdf",
            subdir="tests",
        )
        artifact_path = self.service.artifact_store.resolve(artifact_rel)
        self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path),
                output_filename="delete-template.pdf",
                mime_type="application/pdf",
                size_bytes=len(b"%PDF-delete-template"),
            )
        )
        source_path = self.service.source_store.resolve(revision.managed_file_path)
        draft_path = self.service.draft_store.resolve(draft.managed_file_path)

        self.service.delete_template(
            template.template_id,
            remove_source_files=True,
            remove_draft_files=True,
            remove_output_files=True,
        )

        self.assertIsNone(self.service.fetch_template(template.template_id))
        self.assertFalse(source_path.exists())
        self.assertFalse(draft_path.exists())
        self.assertFalse(artifact_path.exists())

    def test_snapshot_and_artifact_rows_can_be_created_and_listed_without_export_logic(self):
        _, revision = self._create_revision(storage_mode="database")
        draft = self.service.create_draft(
            ContractTemplateDraftPayload(
                revision_id=revision.revision_id,
                name="Snapshot Draft",
                editable_payload={"manual_values": {"license_date": "2026-03-25"}},
                storage_mode="database",
            )
        )

        snapshot = self._create_snapshot(draft.draft_id, revision.revision_id)
        artifact_path = self.root / "exports" / "artist-agreement.pdf"
        artifact = self.service.create_output_artifact(
            ContractTemplateOutputArtifactPayload(
                snapshot_id=snapshot.snapshot_id,
                artifact_type="pdf",
                output_path=str(artifact_path),
                mime_type="application/pdf",
                size_bytes=2048,
                checksum_sha256="abc123",
            )
        )

        self.assertEqual(
            [
                item.snapshot_id
                for item in self.service.list_resolved_snapshots(draft_id=draft.draft_id)
            ],
            [snapshot.snapshot_id],
        )
        self.assertEqual(
            [
                item.artifact_id
                for item in self.service.list_output_artifacts(snapshot_id=snapshot.snapshot_id)
            ],
            [artifact.artifact_id],
        )
        self.assertEqual(snapshot.preview_payload, {"page_count": 2})
        self.assertEqual(artifact.output_filename, "artist-agreement.pdf")


if __name__ == "__main__":
    unittest.main()
