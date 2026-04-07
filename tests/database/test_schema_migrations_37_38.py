from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3738Tests(DatabaseSchemaServiceTestCase):
    test_migrate_37_to_38_allows_unused_registry_sha256_key_deletion = (
        DatabaseSchemaServiceTestCase.case_migrate_37_to_38_allows_unused_registry_sha256_key_deletion
    )


del DatabaseSchemaServiceTestCase
