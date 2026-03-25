from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations2930Tests(DatabaseSchemaServiceTestCase):
    test_migrate_29_to_30_adds_contract_template_tables = (
        DatabaseSchemaServiceTestCase.case_migrate_29_to_30_adds_contract_template_tables
    )


del DatabaseSchemaServiceTestCase
