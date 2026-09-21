"""Tupelo Study Coach - deterministic coaching engine.

No LLM, no network, no third-party dependencies. Logic is pure: data in,
data out. Only `repository` touches a database.
"""

__all__ = ["rules", "copy", "diagnosis", "readiness", "planner", "router", "engine"]
VERSION = "1.0.0"
