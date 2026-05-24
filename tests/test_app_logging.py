import json
import logging
import unittest

from isrc_manager.app_logging import JsonLogFormatter


class JsonLogFormatterTests(unittest.TestCase):
    def test_format_emits_json_payload_with_standard_and_extra_fields(self):
        record = logging.LogRecord(
            name="ISRCManager.trace",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Trace message",
            args=(),
            exc_info=None,
        )
        record.event = "startup"
        record.action = "configure"
        record.empty_detail = ""

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "ISRCManager.trace")
        self.assertEqual(payload["message"], "Trace message")
        self.assertEqual(payload["event"], "startup")
        self.assertEqual(payload["action"], "configure")
        self.assertNotIn("empty_detail", payload)
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
