from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations1214Tests(DatabaseSchemaServiceTestCase):
    test_migrate_12_to_13_promotes_default_custom_fields = (
        DatabaseSchemaServiceTestCase.case_migrate_12_to_13_promotes_default_custom_fields
    )
    test_migrate_13_to_14_reconciles_leftover_promoted_custom_fields = (
        DatabaseSchemaServiceTestCase.case_migrate_13_to_14_reconciles_leftover_promoted_custom_fields
    )
    test_migration_skips_same_name_fields_with_different_types = (
        DatabaseSchemaServiceTestCase.case_migration_skips_same_name_fields_with_different_types
    )


del DatabaseSchemaServiceTestCase
