"""
REST API Package for Knowledge Assembly Engine (KAE).

Exports FastAPI app instance and create_app factory.
"""

from src.api.app import app, create_app

__all__ = ["app", "create_app"]
