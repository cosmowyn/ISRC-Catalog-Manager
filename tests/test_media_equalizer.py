import unittest

from isrc_manager.media.equalizer import (
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_MAX_FREQUENCY_HZ,
    EQ_MIN_FREQUENCY_HZ,
    _coerce_bool,
    _coerce_gain,
    _coerce_pan,
    _frequency_for_bin,
    default_equalizer_settings,
    equalizer_has_audible_gain,
    equalizer_response_db_at_frequency,
    equalizer_response_for_bins,
    load_equalizer_settings,
    normalize_equalizer_settings,
    save_equalizer_settings,
)


class _FakeSettings:
    def __init__(self, values: dict[str, object] | None = None, *, type_lookup: bool = True):
        self._values = dict(values or {})
        self._type_lookup = type_lookup
        self.sync_called = False
        self.stored: dict[str, object] = {}

    def value(self, key: str, default=None, type_=None, **kwargs):
        if "type" in kwargs:
            type_ = kwargs["type"]
        if self._type_lookup:
            return self._values.get(key, default)
        if type_ is not None:
            raise TypeError("type hints unsupported")
        return self._values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.stored[key] = value

    def sync(self) -> None:
        self.sync_called = True


class _TypeErrorSettings:
    def __init__(self, values: dict[str, object] | None = None):
        self._values = dict(values or {})

    def value(self, key: str, default=None, type_=None, **kwargs):
        if "type" in kwargs:
            type_ = kwargs["type"]
        if type_ is not None:
            raise TypeError("type lookup unsupported")
        return self._values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        raise RuntimeError("set failed")


class _RaisesSettings:
    def value(self, key: str, default=None, type_=None, **kwargs):
        raise RuntimeError("runtime error")

    def setValue(self, key: str, value: object) -> None:
        raise RuntimeError("set failed")


class MediaEqualizerTests(unittest.TestCase):
    def test_coerce_bool_handles_common_accepted_values(self):
        self.assertTrue(_coerce_bool(True))
        self.assertFalse(_coerce_bool(False))
        self.assertTrue(_coerce_bool("yes"))
        self.assertFalse(_coerce_bool("off"))
        self.assertFalse(_coerce_bool(None, default=False))

    def test_coerce_bool_uses_default_for_unknown_text(self):
        self.assertEqual(_coerce_bool("maybe", default=True), True)

    def test_coerce_gain_clamps_and_rounds(self):
        self.assertEqual(_coerce_gain("1.23"), 1.0)
        self.assertEqual(_coerce_gain("not-a-number"), 0.0)
        self.assertEqual(_coerce_gain(EQ_GAIN_MAX_DB + 10), EQ_GAIN_MAX_DB)
        self.assertEqual(_coerce_gain(EQ_GAIN_MIN_DB - 10), EQ_GAIN_MIN_DB)

    def test_coerce_pan_clamps_and_rounds(self):
        self.assertEqual(_coerce_pan("0.987"), 0.99)
        self.assertEqual(_coerce_pan("not-a-number"), 0.0)
        self.assertEqual(_coerce_pan(10), 1.0)
        self.assertEqual(_coerce_pan(-10), -1.0)

    def test_normalize_equalizer_settings_with_invalid_and_string_inputs(self):
        normalized = normalize_equalizer_settings({"enabled": "TRUE", "gains": "bad", "pan": 2})

        self.assertTrue(normalized["enabled"])
        self.assertEqual(normalized["gains"], [0.0 for _ in range(len(normalized["gains"]))])
        self.assertEqual(normalized["pan"], 1.0)

    def test_load_settings_falls_back_when_type_lookup_is_unavailable(self):
        settings = _FakeSettings(
            {
                "media_player/equalizer/enabled": True,
                "media_player/equalizer/gains_json": "[1,2]",
                "media_player/equalizer/pan": "0.5",
            },
            type_lookup=False,
        )

        loaded = load_equalizer_settings(settings)

        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["pan"], 0.5)
        self.assertEqual(loaded["gains"], [1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_load_settings_falls_back_on_type_lookup_exceptions(self):
        loaded = load_equalizer_settings(_TypeErrorSettings())
        self.assertFalse(loaded["enabled"])
        self.assertEqual(loaded["pan"], 0.0)
        self.assertEqual(loaded["gains"], [0.0 for _ in range(len(loaded["gains"]))])

    def test_load_settings_falls_back_on_other_settings_errors(self):
        loaded = load_equalizer_settings(_RaisesSettings())
        self.assertFalse(loaded["enabled"])
        self.assertEqual(loaded["pan"], 0.0)
        self.assertEqual(loaded["gains"], [0.0 for _ in range(len(loaded["gains"]))])

    def test_save_equalizer_settings_ignores_storage_errors(self):
        settings = _TypeErrorSettings()
        saved = save_equalizer_settings(
            settings,
            {"enabled": True, "gains": [0.0, 0.0], "pan": 0.0},
        )
        self.assertEqual(saved["enabled"], True)

    def test_save_equalizer_settings_stores_normalized_values_and_syncs(self):
        settings = _FakeSettings()
        saved = save_equalizer_settings(
            settings, {"enabled": "yes", "gains": [0.1, 0.2], "pan": 0.5}
        )

        self.assertTrue(saved["enabled"])
        self.assertTrue(settings.sync_called)
        self.assertEqual(settings.stored["media_player/equalizer/enabled"], True)
        self.assertEqual(settings.stored["media_player/equalizer/pan"], 0.5)
        self.assertTrue(settings.stored["media_player/equalizer/gains_json"].startswith("["))

    def test_equalizer_response_and_audible_gain(self):
        value = {
            "enabled": True,
            "gains": [0.0] * 8,
            "pan": 0.0,
        }
        self.assertFalse(equalizer_has_audible_gain(value))

        value = {
            "enabled": True,
            "gains": [0.0, 0.0, 0.0, 0.0, 2.5, 0.0, 0.0, 0.0],
            "pan": 0.0,
        }
        self.assertTrue(equalizer_has_audible_gain(value))
        self.assertIsNotNone(equalizer_response_db_at_frequency(1000, value))
        self.assertNotEqual(equalizer_response_db_at_frequency(0, value), 0.0)

    def test_frequency_for_bin_supports_linear_and_log_modes(self):
        linear = _frequency_for_bin(
            index=2,
            count=10,
            frequency_scale="linear",
            min_hz=EQ_MIN_FREQUENCY_HZ,
            max_hz=EQ_MAX_FREQUENCY_HZ,
        )
        log = _frequency_for_bin(
            index=2,
            count=10,
            frequency_scale="log",
            min_hz=EQ_MIN_FREQUENCY_HZ,
            max_hz=EQ_MAX_FREQUENCY_HZ,
        )

        self.assertGreater(linear, EQ_MIN_FREQUENCY_HZ)
        self.assertLess(linear, EQ_MAX_FREQUENCY_HZ)
        self.assertGreater(log, EQ_MIN_FREQUENCY_HZ)
        self.assertLess(log, EQ_MAX_FREQUENCY_HZ)
        self.assertNotEqual(linear, log)

    def test_equalizer_response_for_bins_handles_disabled_and_zero_count(self):
        self.assertEqual(equalizer_response_for_bins(0, default_equalizer_settings()), [])
        self.assertEqual(
            equalizer_response_for_bins(5, default_equalizer_settings()),
            [1.0, 1.0, 1.0, 1.0, 1.0],
        )


if __name__ == "__main__":
    unittest.main()
