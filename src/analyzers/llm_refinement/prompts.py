"""llm_refinement: Prompt text sent to agents."""

CLASSIFICATION_PROMPT = """You are a document structure classifier. For each text block, determine its structural type.

Types:
- paragraph: narrative text, multiple sentences
- table_cell: short data from a table (numbers, labels, values)
- caption: figure/table caption ("Figure 1-5 ASCII code")
- toc_entry: table of contents entry ("Chapter Title 42")
- code: source code or assembly listing
- heading: section/chapter title
- formula: mathematical expression
- list_item: item from a numbered/bulleted list

Respond with ONLY a JSON array. Each element: {"id": N, "type": "...", "confidence": 0.0-1.0}

Blocks:
"""
