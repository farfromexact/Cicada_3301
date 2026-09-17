"""Pure first-order ciphertext feedback transform for H017."""

from __future__ import annotations


MODULUS = 29


def _validate(values, name):
    if not isinstance(values, (list, tuple)) or any(
        type(value) is not int or not 0 <= value < MODULUS for value in values
    ):
        raise ValueError(f"{name} must contain rune indices 0..28")
    return tuple(values)


def difference_page(cipher):
    """Return P[0]=C[0], P[i]=C[i]-C[i-1] modulo 29."""
    cipher = _validate(cipher, "Cipher")
    previous = 0
    plaintext = []
    for value in cipher:
        plaintext.append((value - previous) % MODULUS)
        previous = value
    return plaintext


def cumulative_encrypt(plaintext):
    """Return the inverse cumulative ciphertext with C[-1]=0."""
    plaintext = _validate(plaintext, "Plaintext")
    previous = 0
    cipher = []
    for value in plaintext:
        previous = (previous + value) % MODULUS
        cipher.append(previous)
    return cipher
