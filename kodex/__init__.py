"""KODEX — Spine Surgery (ADR) Cost-vs-Quality Decision Matrix.

A transparent, offline-friendly decision-support aggregator. KODEX pulls public
provider/cost/quality-signal data, normalizes it, scores it with configurable
weights, and prints an honest two-axis matrix (cost vs. a labeled quality
*proxy*) plus a procedure-evidence summary.

It is NOT an outcomes oracle. It never prints a fabricated per-surgeon success
rate. Every quality number is a clearly labeled proxy or a facility-level
measure. Unsourced fields render as UNKNOWN.
"""

__version__ = "1.0.0"
