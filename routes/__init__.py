"""
Routes package for the GameStore application.
This package contains Flask route blueprints for the web and API interfaces.
"""

from .web import web_bp
from .api import api_bp

__all__ = ['web_bp', 'api_bp'] 