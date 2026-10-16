"""Linear source adapter: tickets of one workspace.

Why: Linear holds the planned work that GitHub history cannot show (who a ticket was for, what it
blocks). `fetch` pulls issues into a cache through the GraphQL API; `records` turns that cache into
canonical records without touching the network. See client.py and source.py.
"""

from brain.adapters.linear.source import LinearSource

__all__ = ["LinearSource"]
