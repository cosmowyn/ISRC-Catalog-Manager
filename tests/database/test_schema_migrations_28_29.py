from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations2829Tests(DatabaseSchemaServiceTestCase):
    test_migrate_28_to_29_adds_forensic_export_ledger = (
        DatabaseSchemaServiceTestCase.case_migrate_28_to_29_adds_forensic_export_ledger
    )


del DatabaseSchemaServiceTestCase
