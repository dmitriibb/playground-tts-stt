"""Run the backend: `python -m gateway` (reads HOST/PORT from .env)."""

import uvicorn

from gateway.config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("gateway.app:create_app", factory=True, host=settings.host, port=settings.port,
                log_level=settings.log_level.lower(), ws_max_size=16 * 1024 * 1024)
