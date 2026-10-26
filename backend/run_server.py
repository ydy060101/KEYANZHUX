"""Development server entry point.

psycopg's async driver cannot run on Windows' ProactorEventLoop, and
uvicorn 0.54 picks Proactor there regardless of the event-loop policy, so the
loop is chosen explicitly (see app/uvicorn_loop.py). app/db.py also sets the
policy for scripts and tests that never go through uvicorn.
"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        loop="app.uvicorn_loop:selector_loop_factory",
    )
