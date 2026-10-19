"""Deterministic HTML extraction domain (spec 0005).

Side-effect-free extractor plus a thin HTTP preview wrapper. No DB writes
and no LLMs in the path. Feature 7 provides the persistence shell around
`ExtractionService.run(...)`.
"""
