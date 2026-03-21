from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations2024Tests(DatabaseSchemaServiceTestCase):
    test_migrate_20_to_21_adds_repertoire_tables = (
        DatabaseSchemaServiceTestCase.case_migrate_20_to_21_adds_repertoire_tables
    )
    test_migrate_21_to_22_adds_blob_icon_payload_column = (
        DatabaseSchemaServiceTestCase.case_migrate_21_to_22_adds_blob_icon_payload_column
    )
    test_migrate_23_to_24_adds_history_visibility_column = (
        DatabaseSchemaServiceTestCase.case_migrate_23_to_24_adds_history_visibility_column
    )


del DatabaseSchemaServiceTestCase
