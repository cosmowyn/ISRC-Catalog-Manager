from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3233Tests(DatabaseSchemaServiceTestCase):
    test_migrate_32_to_33_adds_governance_columns_and_explicit_interest_tables = (
        DatabaseSchemaServiceTestCase.case_migrate_32_to_33_adds_governance_columns_and_explicit_interest_tables
    )


del DatabaseSchemaServiceTestCase
