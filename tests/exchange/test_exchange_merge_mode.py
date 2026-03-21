from tests.exchange._support import ExchangeServiceTestCase


class ExchangeMergeModeTests(ExchangeServiceTestCase):
    test_merge_mode_matches_case_only_title_and_artist_differences = (
        ExchangeServiceTestCase.case_merge_mode_matches_case_only_title_and_artist_differences
    )
    test_merge_mode_matches_case_only_upc_title_lookup = (
        ExchangeServiceTestCase.case_merge_mode_matches_case_only_upc_title_lookup
    )
    test_merge_mode_does_not_auto_merge_ambiguous_case_normalized_match = (
        ExchangeServiceTestCase.case_merge_mode_does_not_auto_merge_ambiguous_case_normalized_match
    )


del ExchangeServiceTestCase
