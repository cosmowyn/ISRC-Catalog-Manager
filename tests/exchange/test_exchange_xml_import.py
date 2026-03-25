from tests.exchange._support import ExchangeServiceTestCase


class ExchangeXmlImportTests(ExchangeServiceTestCase):
    test_import_xml_uses_governed_workflow_and_creates_missing_custom_fields = (
        ExchangeServiceTestCase.case_import_xml_uses_governed_workflow_and_creates_missing_custom_fields
    )


del ExchangeServiceTestCase
