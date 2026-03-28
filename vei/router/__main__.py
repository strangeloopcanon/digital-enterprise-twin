from __future__ import annotations


from .api import create_router
from .server_fastmcp import create_mcp_server
from vei.config import Config


def main() -> None:
    cfg = Config.from_env()
    router = create_router(
        seed=cfg.seed, artifacts_dir=cfg.artifacts_dir, scenario=cfg.scenario
    )
    server = create_mcp_server(router, host=cfg.host, port=cfg.port)
    server.run("stdio")


if __name__ == "__main__":
    main()
