from tests.database._schema_support import DatabaseSchemaServiceTestCase


class DatabaseSchemaCurrentTargetTests(DatabaseSchemaServiceTestCase):
    test_init_db_and_migrate_schema_reach_current_target = (
        DatabaseSchemaServiceTestCase.case_init_db_and_migrate_schema_reach_current_target
    )
    test_current_schema_allows_multiple_blank_isrc_rows = (
        DatabaseSchemaServiceTestCase.case_current_schema_allows_multiple_blank_isrc_rows
    )
    test_init_db_tolerates_older_tracks_schema_before_migration = (
        DatabaseSchemaServiceTestCase.case_init_db_tolerates_older_tracks_schema_before_migration
    )


del DatabaseSchemaServiceTestCase
