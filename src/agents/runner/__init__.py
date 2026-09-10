"""
GPU Runner (RFC 0022 §2.2).

The heavy process that actually runs vision/OCR models on a GPU host (Kaggle
notebook, Colab, or local box). Exposes /health, /ready, /infer, /shutdown,
/models and self-terminates on idle so its Kaggle GPU quota is not wasted.
"""
