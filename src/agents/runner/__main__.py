"""Run the Runner as `python -m src.agents.runner`."""

import logging

import uvicorn

from src.agents.runner.app import create_app
from src.agents.runner.config import RunnerConfig


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = RunnerConfig()
    # Real loaders are wired in Stage 3 (Kaggle notebook). Without them we ship
    # only EchoLoader so the runner can boot on any host.
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
