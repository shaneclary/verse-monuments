"""KODEX data connectors (Spec §3).

Each connector is a module that takes structured input, returns validated
records, and FAILS LOUDLY — it never silently returns empty on error, so the
pipeline can always tell "no data" apart from "fetch failed."
"""
