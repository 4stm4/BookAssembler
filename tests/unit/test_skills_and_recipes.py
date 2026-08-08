"""
Unit tests for Skills, Recipes, and ProfileResolver (RFC 0006).

Tests verify:
1. SkillLoader parsing of .md files with YAML Frontmatter and Markdown patterns/rules.
2. Skill.matches_context() against text samples with domain mnemonics vs neutral text.
3. ProfileResolver source auto-detection logic on KnowledgeDocument instances.
4. Loading directory of skills via SkillLoader.load_skills_from_dir().
"""

from pathlib import Path
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)
from src.skills.loader import ProfileResolver, SkillLoader
from src.skills.models import (
    Recipe,
    RecipeStep,
    SourceProfile,
)


def test_load_skill_from_markdown() -> None:
    """Verify loading and parsing of markdown skill file with frontmatter, patterns, and rules."""
    skill_path = Path("skills/intel/x86_asm_listings.md")

    skill = SkillLoader.load_skill_from_markdown(skill_path)

    assert skill.manifest.id == "skill.intel.x86_asm_listings"
    assert skill.manifest.name == "Intel x86 Assembly Listing Recognizer"
    assert skill.manifest.version == "1.0.0"
    assert skill.manifest.domain == "intel"
    assert skill.manifest.target_analyzer == "CodeSyntaxAnalyzer"
    assert skill.manifest.confidence_threshold == 0.85

    # Verify patterns categories
    assert "Registers" in skill.manifest.patterns
    assert "Mnemonics" in skill.manifest.patterns
    assert "Hex Numbers" in skill.manifest.patterns

    # Verify rules count
    assert len(skill.manifest.rules) == 2


def test_skill_matches_context() -> None:
    """Verify Skill.matches_context returns True for domain text and False for neutral text."""
    skill_path = Path("skills/intel/x86_asm_listings.md")
    skill = SkillLoader.load_skill_from_markdown(skill_path)

    # Assembly listing with mnemonics and registers
    asm_text_1 = "MOV AX, 0FFH\nADD BX, CX"
    asm_text_2 = "INT 21H instruction call"

    # Neutral non-code text
    neutral_text = "The user manual describes standard operating procedures for office workers."

    assert skill.matches_context(asm_text_1) is True
    assert skill.matches_context(asm_text_2) is True
    assert skill.matches_context(neutral_text) is False


def test_profile_resolver() -> None:
    """Verify ProfileResolver correctly matches document content to recommended recipe ID."""
    resolver = ProfileResolver()

    # Construct test document with Intel signatures
    doc = KnowledgeDocument(
        title="Intel 8086 Microprocessor Hardware Reference Manual",
        source_uri="https://intel.com/manuals/8086.pdf",
    )
    chapter = ContainerUnit(title="Chapter 1: Architecture")
    para = ParagraphBlock(
        inlines=[
            TextLineInline(
                spans=[
                    StyledTextSpan(text="The MOV AX, BX instruction copies registers.")
                ]
            )
        ]
    )
    chapter.children.append(para)
    doc.root_containers.append(chapter)

    # Define candidate profiles
    intel_profile = SourceProfile(
        profile_id="profile.intel",
        publisher_name="Intel Corporation",
        matching_keywords=["8086", "Microprocessor", "MOV"],
        matching_patterns=[r"(?i)\bIntel\b"],
        recommended_recipe_id="recipe.intel_technical_manual",
    )

    arm_profile = SourceProfile(
        profile_id="profile.arm",
        publisher_name="ARM Holdings",
        matching_keywords=["Cortex-M", "Thumb2"],
        matching_patterns=[r"(?i)\bARM\b"],
        recommended_recipe_id="recipe.arm_technical_manual",
    )

    resolved_recipe_id = resolver.resolve(doc, [intel_profile, arm_profile])

    assert resolved_recipe_id == "recipe.intel_technical_manual"


def test_load_skills_from_dir() -> None:
    """Verify loading all skill markdown files recursively from a directory."""
    skills_dir = Path("skills")
    skills_dict = SkillLoader.load_skills_from_dir(skills_dir)

    assert "skill.intel.x86_asm_listings" in skills_dict
    loaded_skill = skills_dict["skill.intel.x86_asm_listings"]
    assert loaded_skill.manifest.domain == "intel"


def test_recipe_model_instantiation() -> None:
    """Verify Recipe and RecipeStep data structure creation."""
    step1 = RecipeStep(analyzer_name="LayoutAnalyzer", skill_ids=["skill.intel.layout"])
    step2 = RecipeStep(analyzer_name="CodeSyntaxAnalyzer", skill_ids=["skill.intel.x86_asm_listings"])

    recipe = Recipe(
        recipe_id="recipe.intel_manual",
        name="Intel Manual Pipeline",
        version="1.0.0",
        pipeline=[step1, step2],
    )

    assert recipe.recipe_id == "recipe.intel_manual"
    assert len(recipe.pipeline) == 2
    assert recipe.pipeline[1].analyzer_name == "CodeSyntaxAnalyzer"
    assert "skill.intel.x86_asm_listings" in recipe.pipeline[1].skill_ids
