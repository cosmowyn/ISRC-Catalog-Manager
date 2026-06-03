from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations1011Tests(DatabaseSchemaServiceTestCase):
    test_migrate_10_to_11_preserves_runner_savepoint = (
        DatabaseSchemaServiceTestCase.case_migrate_10_to_11_preserves_runner_savepoint
    )


del DatabaseSchemaServiceTestCase
