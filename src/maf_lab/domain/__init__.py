"""Domain-independent primitives and the simulated domains built on them.

`money`, `clock` and `canonical` are shared by every domain: integer minor units
with an ISO currency, an injected clock, and one canonical serialization used for
state hashes and request digests.
"""
