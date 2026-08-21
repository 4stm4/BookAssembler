"""Run the Runner as `python -m src.agents.runner`."""

import logging

import uvicorn

from src.agents.runner.app import create_app
from src.agents.runner.config import RunnerConfig
from src.agents.runner.loaders import build_loaders


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = RunnerConfig()
    # cfg.loaders comes from KAE_RUNNER_LOADERS (e.g. "qwen_vl"). Empty →
    # EchoLoader default is picked inside create_app so a bare `python -m
    # src.agents.runner` still boots on a CPU-only host for smoke checks.
    loaders = build_loaders(cfg.loaders) if cfg.loaders else None
    app = create_app(cfg, loaders=loaders)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
