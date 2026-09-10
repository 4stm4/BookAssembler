"""
Skills, Recipes, and Profiles package for Knowledge Assembly Engine (KAE).

Provides declarative domain skills models, skill loaders, pipeline recipe definitions,
source auto-detection profile resolvers, DSL evaluator, and SkillsRunner (RFC 0006).
"""

from src.skills.dsl import DSLContext, DSLError, evaluate
from src.skills.loader import ProfileResolver, SkillLoader
from src.skills.models import (
    Recipe,
    RecipeStep,
    Skill,
    SkillManifest,
    SourceProfile,
)
from src.skills.runner import SkillPack, SkillsRunner

__all__ = [
    "DSLContext",
    "DSLError",
    "ProfileResolver",
    "Recipe",
    "RecipeStep",
    "Skill",
    "SkillLoader",
    "SkillManifest",
    "SkillPack",
    "SkillsRunner",
    "SourceProfile",
    "evaluate",
]
