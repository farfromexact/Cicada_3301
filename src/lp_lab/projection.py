"""Pure fourth-power projection for the H018 finite-field diagnostic."""

from __future__ import annotations


MODULUS = 29
SUBGROUP = (1, 12, 17, 28)


def fourth_power(values):
    if not isinstance(values, (list, tuple)) or any(
        type(value) is not int or not 0 <= value < MODULUS for value in values
    ):
        raise ValueError("Values must contain rune indices 0..28")
    return [pow(value, 4, MODULUS) for value in values]
