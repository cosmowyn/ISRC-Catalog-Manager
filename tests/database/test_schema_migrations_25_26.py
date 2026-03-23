from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations2526Tests(DatabaseSchemaServiceTestCase):
    test_migrate_25_to_26_adds_authenticity_tables = (
        DatabaseSchemaServiceTestCase.case_migrate_25_to_26_adds_authenticity_tables
    )


del DatabaseSchemaServiceTestCase
