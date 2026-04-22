"""Concrete detector implementations.

Keep imports lazy — most heavy ML deps live behind a conditional import so
the core FastAPI process can start without GPU libs installed.
"""
from idas.perception.stub import StubDetector

__all__ = ["StubDetector"]
