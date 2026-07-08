"""Knowledge retrieval domain.

Two concerns live here, kept apart:

- Governance metadata (``models`` + ``repository``): the MongoDB record of every
  approved source, its lifecycle, and the provider IDs it maps to.
- Retrieval (``search``): the boundary that queries the OpenAI Vector Store. It
  is to knowledge what ``app/agent/adapter.py`` is to chat — the only place a
  provider type is touched, and it never raises past its own edge.
"""
