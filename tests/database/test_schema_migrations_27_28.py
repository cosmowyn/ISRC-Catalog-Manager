from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations2728Tests(DatabaseSchemaServiceTestCase):
    test_migrate_27_to_28_adds_derivative_ledger_semantics = (
        DatabaseSchemaServiceTestCase.case_migrate_27_to_28_adds_derivative_ledger_semantics
    )


del DatabaseSchemaServiceTestCase
