import pytest

from isrc_manager.invoicing import (
    VAT_TREATMENT_REVERSE_CHARGE,
    calculate_vat_minor,
    format_money,
    format_quantity,
    line_net_amount_minor,
    parse_money_minor,
    parse_quantity,
)


def test_money_uses_integer_minor_units_and_rejects_float():
    assert parse_money_minor("12.34") == 1234
    assert parse_money_minor("12,345") == 1235
    assert format_money(1234) == "EUR 12.34"

    with pytest.raises(TypeError):
        parse_money_minor(12.34)


def test_quantity_uses_value_and_scale_without_float_arithmetic():
    quantity = parse_quantity("1.250")

    assert quantity.value == 1250
    assert quantity.scale == 3
    assert format_quantity(quantity) == "1.25"
    assert line_net_amount_minor(999, parse_quantity("1.5")) == 1499


def test_vat_treatments_calculate_line_vat_explicitly():
    assert calculate_vat_minor(10_000, 2100) == 2100
    assert (
        calculate_vat_minor(
            10_000,
            2100,
            vat_treatment=VAT_TREATMENT_REVERSE_CHARGE,
        )
        == 0
    )

    with pytest.raises(ValueError):
        calculate_vat_minor(-1, 2100)
