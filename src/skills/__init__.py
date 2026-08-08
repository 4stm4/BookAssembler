"""
Skills, Recipes, and Profiles package for Knowledge Assembly Engine (KAE).

Provides declarative domain skills models, skill loaders, pipeline recipe definitions,
and source auto-detection profile resolvers (RFC 0006).
"""

from src.skills.loader import ProfileResolver, SkillLoader
from src.skills.models import (
    Recipe,
    RecipeStep,
    Skill,
    SkillManifest,
    SourceProfile,
)

__all__ = [
    "ProfileResolver",
    "Recipe",
    "RecipeStep",
    "Skill",
    "SkillLoader",
    "SkillManifest",
    "SourceProfile",
]
