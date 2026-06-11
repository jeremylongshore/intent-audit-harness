"""Deliberately high-complexity module for the crap-score golden fixture.

`tangle` carries many independent branches so a radon-equipped run scores it
high. The golden suite's CI environment has no complexity provider installed,
so the canonical golden captures the no-provider stdout shape; the fixture's
complexity matters only when a developer runs the suite with radon present.
"""


def tangle(a, b, c, d):  # noqa: C901 - intentional complexity for the fixture
    total = 0
    if a > 0:
        total += 1
    if b > 0:
        total += 2
    if c > 0:
        total += 3
    if d > 0:
        total += 4
    if a and b:
        total += 5
    if b and c:
        total += 6
    if c and d:
        total += 7
    if a or d:
        total += 8
    return total
