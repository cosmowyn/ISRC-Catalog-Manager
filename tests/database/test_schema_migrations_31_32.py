from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3132Tests(DatabaseSchemaServiceTestCase):
    test_migrate_31_to_32_adds_party_expansion_and_alias_table = (
        DatabaseSchemaServiceTestCase.case_migrate_31_to_32_adds_party_expansion_and_alias_table
    )


del DatabaseSchemaServiceTestCase
