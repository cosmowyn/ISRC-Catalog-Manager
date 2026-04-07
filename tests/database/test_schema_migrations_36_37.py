from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3637Tests(DatabaseSchemaServiceTestCase):
    test_migrate_36_to_37_deduplicates_shared_external_catalog_identifiers = (
        DatabaseSchemaServiceTestCase.case_migrate_36_to_37_deduplicates_shared_external_catalog_identifiers
    )


del DatabaseSchemaServiceTestCase
