"""Gap #21: genanki declares `frozendict` (LGPLv3) as a dependency but its
0.13.1 source never imports it (verified: no `frozendict` reference anywhere
in the installed package). This shim satisfies that unused requirement
under the same distribution name with a permissively-licensed (MIT)
implementation instead, so the real LGPLv3 package is never installed.
"""

from immutabledict import immutabledict as frozendict

__all__ = ["frozendict"]
