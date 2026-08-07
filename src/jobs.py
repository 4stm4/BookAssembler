"""pyjobkit executors and runtime for BookAssembler."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from pyjobkit.backends.sql import SQLBackend, JobTasks, metadata
from pyjobkit.contracts import Executor, ExecContext
from pyjobkit.engine import Engine
from pyjobkit.worker import Worker

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = Path(os.environ.get("BOOKASSEMBLER_PROJECT_DIR",
                                  str(PROJECT_ROOT / "project")))

DEFAULT_DSN = f"sqlite+aiosqlite:///{PROJECT_DIR / 'cache' / 'jobs' / 'bookassembler.sqlite3'}"


def _get_dsn() -> str:
    return os.environ.get("BOOKASSEMBLER_JOB_DSN", DEFAULT_DSN)


async def _make_backend() -> SQLBackend:
    dsn = _get_dsn()
    if dsn.startswith("sqlite"):
        db_path = dsn.split("///", 1)[1] if "///" in dsn else ""
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    return SQLBackend(engine)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

class TranslateBatchExecutor(Executor):
    kind = "translate-batch"

    async def run(self, *, job_id: UUID, payload: dict, ctx: ExecContext) -> dict:
        ch = payload["chapter"]
        start = payload["start"]
        end = payload["end"]
        pages = payload.get("pages")

        await ctx.log(f"Перевод главы {ch}, стр. {start}-{end}")

        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from translator import TranslatorClient, TranslationRequest, Glossary

        translations_dir = PROJECT_DIR / "claude_translations"
        translations_dir.mkdir(exist_ok=True)

        source_json = PROJECT_DIR / "cache" / "text" / f"pages_{start}_{end}.json"
        manifest_file = PROJECT_DIR / f"ch{ch}_manifest.json"
        manifest_data = None
        if manifest_file.exists():
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))

        glossary = Glossary.load(str(PROJECT_DIR / "glossary.json"))
        client = TranslatorClient.create("api", str(PROJECT_DIR / "glossary.json"))

        request = TranslationRequest.from_extracted_json(
            str(source_json), ch,
            page_range=(start, end),
            glossary=glossary,
            manifest=manifest_data,
        )
        if pages:
            page_set = set(pages)
            request.pages = [p for p in request.pages if p.page_number in page_set]

        if not request.pages:
            await ctx.log("Нет страниц для перевода")
            return {"translated": 0, "skipped": True}

        result = client.translate(request)

        if result.pages:
            pg_nums = [p.page_number for p in result.pages]
            output_name = f"ch{ch}_{pg_nums[0]}_{pg_nums[-1]}.json"
            output_path = translations_dir / output_name

            # Don't overwrite manual fixes
            if not output_path.exists():
                result.save(str(output_path))

            await ctx.set_progress(1.0, translated=result.valid_count)
            if result.failed_pages:
                fails = [f"стр.{p.page_number}: {'; '.join(p.issues)}"
                         for p in result.failed_pages[:5]]
                await ctx.log(f"Проблемы: {'; '.join(fails)}")

            return {
                "translated": result.valid_count,
                "failed": len(result.failed_pages),
                "output": str(output_path),
            }

        return {"translated": 0}


class AnalyzeFigureExecutor(Executor):
    kind = "analyze-figure"

    async def run(self, *, job_id: UUID, payload: dict, ctx: ExecContext) -> dict:
        fig_number = payload["figure_number"]
        page = payload["page"]
        pdf_file = payload.get("pdf_file", "")

        cache_key = f"fig_{fig_number.replace('.', '_')}.json"
        cache_dir = PROJECT_DIR / "cache" / "diagram_analysis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / cache_key

        if cache_path.exists():
            await ctx.log(f"Figure {fig_number}: уже в кеше")
            return {"figure": fig_number, "cached": True}

        await ctx.log(f"Анализ Figure {fig_number} (стр. {page})")

        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from diagram_extract import analyze_figure

        pdf_path = str(PROJECT_DIR / pdf_file) if pdf_file else ""

        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(
            None, lambda: analyze_figure(pdf_path, page, fig_number, save_debug=True)
        )
        result_data = analysis.to_dict()

        cache_path.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {"figure": fig_number, "cached": False}


class RenderFigurePageExecutor(Executor):
    kind = "render-figure-page"

    async def run(self, *, job_id: UUID, payload: dict, ctx: ExecContext) -> dict:
        page = payload["page"]
        chapter = payload["chapter"]
        pdf_file = payload.get("pdf_file", "")

        images_dir = PROJECT_DIR / f"ch{chapter}_figures"
        images_dir.mkdir(exist_ok=True)
        output_path = images_dir / f"page_{page}.png"

        if output_path.exists():
            await ctx.log(f"Страница {page}: уже отрендерена")
            return {"page": page, "cached": True, "output": str(output_path)}

        await ctx.log(f"Рендер страницы {page}")

        import fitz
        pdf_path = str(PROJECT_DIR / pdf_file) if pdf_file else ""
        loop = asyncio.get_event_loop()

        def _render():
            doc = fitz.open(pdf_path)
            pix = doc[page].get_pixmap(dpi=200)
            pix.save(str(output_path))
            doc.close()

        await loop.run_in_executor(None, _render)

        return {"page": page, "cached": False, "output": str(output_path)}


class BuildChapterExecutor(Executor):
    kind = "build-chapter"

    async def run(self, *, job_id: UUID, payload: dict, ctx: ExecContext) -> dict:
        ch = payload["chapter"]
        start = payload["start"]
        end = payload["end"]

        await ctx.log(f"Сборка LaTeX главы {ch}")

        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from build_latex import build_chapter

        loop = asyncio.get_event_loop()
        out = await loop.run_in_executor(
            None, lambda: build_chapter(ch, start, end)
        )

        output_path = PROJECT_DIR / "latex_output" / f"ch{ch:02d}.tex"
        if not output_path.exists():
            raise RuntimeError(f"build не создал {output_path}")

        return {"output": str(output_path)}


class CompileBookExecutor(Executor):
    kind = "compile-book"

    async def run(self, *, job_id: UUID, payload: dict, ctx: ExecContext) -> dict:
        ch = payload["chapter"]

        await ctx.log(f"Компиляция главы {ch}")

        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        os.chdir(PROJECT_DIR)

        from pipeline import stage_compile
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: stage_compile(ch, 0, 0))

        pdf_name = PROJECT_DIR / f"ch{ch}_compiled.pdf"
        book_pdf = PROJECT_DIR / "latex_output" / "book.pdf"
        if not pdf_name.exists() and not book_pdf.exists():
            raise RuntimeError("Компиляция не создала PDF")

        return {"pdf": str(pdf_name if pdf_name.exists() else book_pdf)}


ALL_EXECUTORS = [
    TranslateBatchExecutor(),
    AnalyzeFigureExecutor(),
    RenderFigurePageExecutor(),
    BuildChapterExecutor(),
    CompileBookExecutor(),
]


# ---------------------------------------------------------------------------
# Engine / worker helpers
# ---------------------------------------------------------------------------

async def create_engine() -> Engine:
    backend = await _make_backend()
    return Engine(backend=backend, executors=ALL_EXECUTORS)


async def _safe_enqueue(engine: Engine, **kwargs) -> UUID | None:
    """Enqueue with idempotency: return None if job already exists."""
    try:
        return await engine.enqueue(**kwargs)
    except IntegrityError:
        return None


async def enqueue_translate(engine: Engine, ch: int, start: int, end: int,
                            pages: list[int] | None = None) -> UUID | None:
    key = f"ch{ch}:translate:{start}-{end}"
    if pages:
        key += f":{pages[0]}-{pages[-1]}"
    return await _safe_enqueue(
        engine,
        kind="translate-batch",
        payload={"chapter": ch, "start": start, "end": end, "pages": pages},
        idempotency_key=key,
    )


async def enqueue_figure_render(engine: Engine, ch: int, page: int,
                                pdf_file: str) -> UUID | None:
    return await _safe_enqueue(
        engine,
        kind="render-figure-page",
        payload={"chapter": ch, "page": page, "pdf_file": pdf_file},
        idempotency_key=f"ch{ch}:figure-render:{page}",
    )


async def enqueue_figure_analyze(engine: Engine, ch: int, fig_number: str,
                                 page: int, pdf_file: str) -> UUID | None:
    return await _safe_enqueue(
        engine,
        kind="analyze-figure",
        payload={"figure_number": fig_number, "page": page, "pdf_file": pdf_file},
        idempotency_key=f"ch{ch}:figure-analyze:{fig_number}",
    )


async def enqueue_build(engine: Engine, ch: int, start: int, end: int) -> UUID | None:
    return await _safe_enqueue(
        engine,
        kind="build-chapter",
        payload={"chapter": ch, "start": start, "end": end},
        idempotency_key=f"ch{ch}:build",
    )


async def enqueue_compile(engine: Engine, ch: int) -> UUID | None:
    return await _safe_enqueue(
        engine,
        kind="compile-book",
        payload={"chapter": ch},
        idempotency_key=f"ch{ch}:compile",
    )


async def run_worker(*, once: bool = False) -> int:
    """Run worker. Returns nonzero if any jobs failed or got stuck.

    SQLite CURRENT_TIMESTAMP lacks sub-second precision, so a job
    enqueued in the same second may not be claimable immediately.
    For once=True we retry claim after a short sleep to work around this.
    """
    engine = await create_engine()
    if once:
        # SQLite timing workaround: wait 1.1s so scheduled_for <= CURRENT_TIMESTAMP
        await asyncio.sleep(1.1)
    async with engine:
        worker = Worker(engine, max_concurrency=4)
        await worker.run(once=once)

    if once:
        status = await get_jobs_status()
        failed = status["by_status"].get("failed", 0)
        running = status["by_status"].get("running", 0)
        if failed or running:
            print(f"  Jobs: {failed} failed, {running} stuck in running")
            return 1
    return 0


async def get_jobs_status(ch: int | None = None) -> dict:
    """Query job status counts, optionally filtered by chapter."""
    backend = await _make_backend()
    async with backend.sessionmaker() as session:
        query = select(
            JobTasks.c.status,
            JobTasks.c.kind,
            JobTasks.c.idempotency_key,
            JobTasks.c.created_at,
            JobTasks.c.finished_at,
        )
        if ch is not None:
            query = query.where(
                JobTasks.c.idempotency_key.like(f"ch{ch}:%")
            )
        rows = (await session.execute(query)).mappings().all()

    counts: dict[str, int] = {}
    for row in rows:
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1

    return {"total": len(rows), "by_status": counts, "jobs": [dict(r) for r in rows]}
