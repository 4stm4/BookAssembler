"""Run the Manager as `python -m src.agents.manager` (RFC 0022 §10 step 1)."""

import logging

import uvicorn

from src.agents.manager.app import create_app
from src.agents.manager.config import ManagerConfig


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = ManagerConfig()
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
