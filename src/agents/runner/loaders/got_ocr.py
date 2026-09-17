"""
GOT-OCR2.0 loader (RFC 0022 §6): a specialised table/OCR model that reads a
page region from its PIXELS and returns LaTeX, instead of trusting whatever
text layer the PDF happens to carry.

This exists because of a measured failure, not a preference. On
tests/fixtures/z80_voltage_regulator_table.pdf the printed page is clean but
the embedded text layer is garbled OCR: the page shows `11.5`, `3.0`, `0.8`,
`P < 15 W`, `Quiescent Current`, while the layer the adapter reads says
`ii4`, `30`, `OS`, `K 15 W`, `Ou*ic«nt Current`. Every value, the column
count and the row spans are wrong at the source, so no amount of work in
the detector or the assembler can make the rebuilt table match the page -
the text has to come off the raster.

Unlike QwenVLLoader, which claims ALL_TASKS because a second model would not
fit beside it (RFC 0022 §9 inv.11), this one declares only what it actually
serves. It is the smaller model of the two, so a deployment can run it alone
for table work without reserving 15 GB for a general multimodal model.

Heavy dependencies (torch, transformers) are imported lazily inside load()
so this module imports on a CPU-only host; all model I/O runs off the event
loop via asyncio.to_thread, and generation honours a wall-clock deadline -
the runner sits behind a tunnel that cuts long requests.
"""

import asyncio
import logging
import os
import tempfile
import time
from typing import Any, List, Optional

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "stepfun-ai/GOT-OCR2_0"

# GOT-OCR is driven by a mode, not a free-text prompt: 'format' returns
# structured LaTeX (what a table needs), 'ocr' returns plain text.
_FORMATTED_TASKS = ("table", "formula")


class _DeadlineCriteria:
    """StoppingCriteria that fires when wall-clock time exceeds a deadline.

    Same guard as the Qwen loader: without it a long generation runs past
    the tunnel's own cut-off and the caller sees a dropped connection
    instead of a timeout it can act on.
    """

    def __init__(self, deadline: float) -> None:
        self._deadline = deadline

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        return time.monotonic() > self._deadline


class GotOcrLoader:
    """Concrete ModelLoader for GOT-OCR2.0.

    The constructor is cheap - no torch import - so the pool can register it
    at startup on a CPU-only host and materialise the model on the first
    ensure_loaded().
    """

    name: str
    tasks: List[str]
    vram_mb: int
    loaded: bool

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        vram_mb: int = 6_000,
        max_new_tokens: int = 4096,
    ) -> None:
        self.name = model_id.split("/")[-1]
        # Only what this model actually serves. A table region and a formula
        # region are the same problem for it; page transcription is 'ocr'.
        self.tasks = ["table", "formula", "ocr"]
        self.vram_mb = vram_mb
        self.loaded = False
        self._model_id = model_id
        self._max_new_tokens = max_new_tokens
        self._model: Any = None
        self._tokenizer: Any = None

    async def load(self) -> None:
        if self.loaded:
            return

        def _load_sync() -> None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "GotOcrLoader requires CUDA - torch.cuda.is_available()=False. "
                    "Run this loader inside the Runner (Kaggle/Colab GPU), not on CPU."
                )

            log.info("GOT-OCR: loading %s", self._model_id)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_id, trust_remote_code=True,
            )
            self._model = AutoModel.from_pretrained(
                self._model_id,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
                device_map="cuda",
                use_safetensors=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            self._model = self._model.eval().cuda()

        await asyncio.to_thread(_load_sync)
        self.loaded = True

    async def unload(self) -> None:
        if not self.loaded:
            return

        def _unload_sync() -> None:
            self._model = None
            self._tokenizer = None
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
        max_new_tokens: Optional[int] = None,
        timeout: int = 120,
    ) -> str:
        if not self.loaded:
            raise RuntimeError("GotOcrLoader.infer() called before load()")
        if image_png is None:
            # This model reads pixels; there is nothing it can do with a bare
            # prompt, and silently returning the prompt would look like a
            # recognition result downstream.
            raise ValueError(f"task '{task}' reached GOT-OCR with no image")

        limit = (
            min(max_new_tokens, self._max_new_tokens)
            if max_new_tokens else self._max_new_tokens
        )
        mode = "format" if task in _FORMATTED_TASKS else "ocr"
        deadline = time.monotonic() + timeout

        def _infer_sync() -> str:
            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, "wb") as fh:
                fh.write(image_png)
            try:
                import torch
                with torch.no_grad():
                    text = self._model.chat(
                        self._tokenizer,
                        tmp_path,
                        ocr_type=mode,
                        max_new_tokens=limit,
                        stopping_criteria=[_DeadlineCriteria(deadline)],
                    )
                if time.monotonic() > deadline:
                    log.warning("infer: %s hit %ds deadline", task, timeout)
                    raise TimeoutError(f"{task} inference exceeded {timeout}s")
                return str(text)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        return await asyncio.to_thread(_infer_sync)
