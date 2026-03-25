from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaMigrations3031Tests(DatabaseSchemaServiceTestCase):
    test_migrate_30_to_31_adds_contract_template_scan_columns = (
        DatabaseSchemaServiceTestCase.case_migrate_30_to_31_adds_contract_template_scan_columns
    )


del DatabaseSchemaServiceTestCase
