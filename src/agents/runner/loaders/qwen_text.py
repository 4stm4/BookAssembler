"""
Qwen2.5 text-only loader for translate / refine tasks.

Same family as the VL variant but without vision modules — all parameters
go to language, so translation quality is noticeably better on the same
7B budget.  VRAM is ~14 GB in fp16 on a single T4.

Heavy deps imported lazily so CPU-only environments can import this module.
"""

import asyncio
import logging
import time
from typing import Any, List, Optional

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"


class QwenTextLoader:

    name: str
    tasks: List[str]
    vram_mb: int
    loaded: bool

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        vram_mb: int = 14_000,
        max_new_tokens: int = 2048,
    ) -> None:
        self.name = model_id.split("/")[-1]
        self.tasks = ["translate", "refine"]
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
            from transformers import AutoModelForCausalLM, AutoTokenizer

            if not torch.cuda.is_available():
                raise RuntimeError(
                    "QwenTextLoader requires CUDA — torch.cuda.is_available()=False."
                )

            n_gpu = torch.cuda.device_count()
            log.info("QwenText: loading %s on %d GPU(s)", self._model_id, n_gpu)

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_id)
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_id,
                torch_dtype=torch.float16,
                device_map="auto",
            )

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
            raise RuntimeError("QwenTextLoader.infer() called before load()")
        if not prompt:
            raise ValueError(f"task '{task}' requires a prompt")

        limit = min(max_new_tokens, self._max_new_tokens) if max_new_tokens else self._max_new_tokens
        deadline = time.monotonic() + timeout

        def _infer_sync() -> str:
            from src.agents.runner.loaders.qwen_vl import _DeadlineCriteria
            messages = [{"role": "user", "content": prompt}]
            text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._tokenizer(
                text, return_tensors="pt", padding=True
            ).to("cuda")
            stopper = _DeadlineCriteria(deadline)
            out = self._model.generate(
                **inputs, max_new_tokens=limit,
                stopping_criteria=[stopper],
                repetition_penalty=1.15,
            )
            if time.monotonic() > deadline:
                log.warning("infer: %s hit %ds deadline", task, timeout)
                raise TimeoutError(f"{task} inference exceeded {timeout}s")
            trimmed = out[0][inputs.input_ids.shape[1]:]
            return self._tokenizer.decode(trimmed, skip_special_tokens=True)

        return await asyncio.to_thread(_infer_sync)
