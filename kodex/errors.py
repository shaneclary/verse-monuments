"""KODEX exceptions.

Connectors must FAIL LOUDLY (Spec §3): distinguish "no data" (a legitimate empty
result) from "fetch failed" (an error). These exceptions carry that distinction
so the pipeline never silently treats a network failure as "this surgeon has no
data."
"""

from __future__ import annotations


class KodexError(Exception):
    """Base for all KODEX errors."""


class FetchError(KodexError):
    """A network fetch failed (HTTP error, timeout, transport). NOT the same as
    'the source legitimately returned no rows.'"""


class CacheMiss(KodexError):
    """Offline mode was requested but the required data is not in the SQLite
    cache. The pipeline cannot fabricate it (Spec §4 offline guarantee)."""


class SchemaError(KodexError):
    """A source returned data in a shape KODEX could not parse. Surfaced rather
    than guessed-around (Spec §11 MRF schema drift)."""
