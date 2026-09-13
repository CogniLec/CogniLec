"""Gap #21: python-slugify falls back to `text-unidecode` (GPL/Artistic
dual-licensed) when the `unidecode` package (also GPL) isn't installed.
This shim satisfies that same import under the same distribution/module
name with a permissively-licensed (ISC) implementation: `anyascii`, which
provides an equivalent `unidecode(text) -> str` transliteration function.
"""

from anyascii import anyascii as unidecode

__all__ = ["unidecode"]
