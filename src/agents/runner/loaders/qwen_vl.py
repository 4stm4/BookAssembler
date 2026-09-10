"""
Qwen2.5-VL loader (RFC 0022 §6): single multimodal model serving
every task of RFC 0022 §4.4 by swapping only the prompt: the image
ones (`ocr`, `vision`, `table`, `formula`) and the text ones
(`refine`, `translate`), which send no image at all.

Heavy dependencies (`torch`, `transformers`, `qwen_vl_utils`) are imported
lazily inside `load()` so unit tests and CPU-only environments can import
this module without a CUDA stack. All model I/O runs off the event loop
via `asyncio.to_thread`.

Ported from `colab/kae_multimodel_agent.ipynb` (fp16 + device_map='auto',
so 2×T4 on Kaggle shard the 7B automatically).
"""

from src.agents.tasks import ALL_TASKS
import asyncio
import base64
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional


log = logging.getLogger(__name__)


DEFAULT_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"


TASK_PROMPTS: Dict[str, str] = {
    "table": (
        "Convert the table in this image to a LaTeX tabular environment, "
        "preserving merged cells and all values. Output ONLY the LaTeX."
    ),
    "formula": (
        "Extract every mathematical formula from this image as LaTeX. "
        "Output ONLY the LaTeX."
    ),
    "ocr": (
        "This is a scanned page with no text layer. Transcribe every line of "
        "readable text in reading order. Output the text only."
    ),
    "vision": (
        "Reconstruct this block diagram as a LaTeX tikzpicture: boxes with "
        "their text, titles above boxes, and connecting arrows. "
        "Output ONLY the tikzpicture environment."
    ),
}


class QwenVLLoader:
    """
    Concrete ModelLoader for Qwen2.5-VL-7B-Instruct.

    Constructor is cheap (no imports of torch/transformers) so this can be
    registered in the pool at Runner startup on a CPU-only host; the model
    is materialized on the first `load()` from ModelPool.ensure_loaded().
    """

    name: str
    tasks: List[str]
    vram_mb: int
    loaded: bool

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        vram_mb: int = 15_000,
        max_new_tokens: int = 2048,
    ) -> None:
        self.name = model_id.split("/")[-1]
        # Every task in the registry: this model serves them all, and a
        # second one would not fit beside it (RFC 0022 §9 inv.11).
        self.tasks = list(ALL_TASKS)
        self.vram_mb = vram_mb
        self.loaded = False
        self._model_id = model_id
        self._max_new_tokens = max_new_tokens
        self._model: Any = None
        self._processor: Any = None
        self._process_vision_info: Any = None

    async def load(self) -> None:
        if self.loaded:
            return

        def _load_sync() -> None:
            import torch
            from transformers import (
                AutoProcessor,
                Qwen2_5_VLForConditionalGeneration,
            )
            from qwen_vl_utils import process_vision_info

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "QwenVLLoader requires CUDA — torch.cuda.is_available()=False. "
                    "Run this loader inside the Runner (Kaggle/Colab GPU), not on CPU."
                )

            n_gpu = torch.cuda.device_count()
            log.info("QwenVL: loading %s on %d GPU(s)", self._model_id, n_gpu)

            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self._model_id,
                torch_dtype=torch.float16,
                device_map="auto",
            )
            # 2×T4 → allow a bigger visual context; single T4 → smaller.
            max_pixels = (1280 if n_gpu >= 2 else 768) * 28 * 28
            self._processor = AutoProcessor.from_pretrained(
                self._model_id,
                min_pixels=256 * 28 * 28,
                max_pixels=max_pixels,
            )
            self._process_vision_info = process_vision_info

        await asyncio.to_thread(_load_sync)
        self.loaded = True

    async def unload(self) -> None:
        if not self.loaded:
            return

        def _unload_sync() -> None:
            self._model = None
            self._processor = None
            self._process_vision_info = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        await asyncio.to_thread(_unload_sync)
        self.loaded = False

    async def infer(
        self,
        image_png: Optional[bytes],
        task: str,
        prompt: Optional[str] = None,
    ) -> str:
        if not self.loaded:
            raise RuntimeError("QwenVLLoader.infer() called before load()")

        real_prompt = prompt or TASK_PROMPTS.get(task, TASK_PROMPTS["table"])
        if image_png is None and not prompt:
            # A text task is nothing but its prompt; a task default would ask
            # the model to describe an image that was never sent.
            raise ValueError(f"task '{task}' has no image and no prompt")

        def _infer_sync() -> str:
            # Text tasks (RFC 0022 §4.4) run on this same model with no image:
            # Qwen2.5-VL is multimodal, so dropping the image turns it into an
            # ordinary text model rather than requiring a second one.
            tmp_path = None
            if image_png is not None:
                fd, tmp_path = tempfile.mkstemp(suffix=".png")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(image_png)
            try:
                content = []
                if tmp_path is not None:
                    content.append({"type": "image", "image": tmp_path})
                content.append({"type": "text", "text": real_prompt})
                messages = [{"role": "user", "content": content}]
                text = self._processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                images, videos = self._process_vision_info(messages)
                inputs = self._processor(
                    text=[text],
                    images=images,
                    videos=videos,
                    padding=True,
                    return_tensors="pt",
                ).to("cuda")
                out = self._model.generate(
                    **inputs, max_new_tokens=self._max_new_tokens
                )
                trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, out)]
                decoded = self._processor.batch_decode(
                    trimmed, skip_special_tokens=True
                )[0]
                return str(decoded)
            finally:
                try:
                    if tmp_path is not None:
                        os.remove(tmp_path)
                except OSError:
                    pass

        return await asyncio.to_thread(_infer_sync)


