from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3536Tests(DatabaseSchemaServiceTestCase):
    test_migrate_35_to_36_adds_code_registry_tables_and_backfills_catalog_links = (
        DatabaseSchemaServiceTestCase.case_migrate_35_to_36_adds_code_registry_tables_and_backfills_catalog_links
    )


del DatabaseSchemaServiceTestCase
