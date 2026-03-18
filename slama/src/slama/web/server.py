"""FastAPI web server for SLAMA monitor displays.

Usage:
    cd src/slama
    uvicorn slama.web.server:app --reload --port 8000

Or:
    python -m slama.web.server
"""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from .data_bridge import DataBridge
from .display_config import (
    DisplayConfig,
    TableBlock,
    GridBlock,
    CellsBlock,
    load_display_config,
    list_display_configs,
)

logger = logging.getLogger(__name__)

# --- Paths ---
_WEB_DIR = Path(__file__).parent
_TEMPLATE_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"
_CONF_DIR = _WEB_DIR.parent / "conf"
_DISPLAYS_DIR = _CONF_DIR / "displays"
_MPDEFS_PATH = _CONF_DIR / "mpdefs.json"

# --- Jinja2 ---
jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

# --- FastAPI app ---
app = FastAPI(title="SLAMA Monitor Display")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# DataBridge uses lazy SMAX connection — no blocking at import/startup time
bridge = DataBridge(
    host="localhost",
    port=6380,
    mpdefs_path=_MPDEFS_PATH,
)


# ------------------------------------------------------------------
# HTTP routes
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """List all available display pages."""
    configs = list_display_configs(_DISPLAYS_DIR)
    template = jinja_env.get_template("index.html")
    return template.render(displays=configs)


@app.get("/display/{name}", response_class=HTMLResponse)
async def display_page(name: str):
    """Render a display page with initial data."""
    config_path = _DISPLAYS_DIR / f"{name}.json"
    if not config_path.exists():
        return HTMLResponse(f"Display '{name}' not found", status_code=404)

    config = load_display_config(config_path)

    # Try to fetch initial values, but render the page even if SMAX is down
    try:
        cells = await asyncio.wait_for(
            asyncio.to_thread(bridge.fetch_all, config),
            timeout=5.0,
        )
    except (asyncio.TimeoutError, Exception):
        logger.warning("Could not fetch initial data for '%s'", name)
        cells = {n: bridge._nodata_cell(n) for n in config.all_canonical_names()}

    template = jinja_env.get_template("display.html")
    return template.render(
        config=config,
        cells=cells,
        TableBlock=TableBlock,
        GridBlock=GridBlock,
        CellsBlock=CellsBlock,
    )


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------

@app.websocket("/ws/display/{name}")
async def ws_display(websocket: WebSocket, name: str):
    """Push live updates for a display page."""
    await websocket.accept()

    config_path = _DISPLAYS_DIR / f"{name}.json"
    if not config_path.exists():
        await websocket.close(code=4004, reason=f"Display '{name}' not found")
        return

    config = load_display_config(config_path)
    interval = config.update_interval

    try:
        while True:
            await asyncio.sleep(interval)

            # Fetch all values in a thread to avoid blocking the event loop
            cells = await asyncio.to_thread(bridge.fetch_all, config)

            # Render update fragments — one div per block with hx-swap-oob
            html_parts = []
            for i, block in enumerate(config.layout):
                block_html = _render_block(block, i, cells)
                html_parts.append(
                    f'<div id="block-{i}" hx-swap-oob="innerHTML">'
                    f'{block_html}</div>'
                )

            message = "\n".join(html_parts)
            await websocket.send_text(message)

    except WebSocketDisconnect:
        logger.debug("Client disconnected from display '%s'", name)
    except Exception:
        logger.exception("Error in WebSocket for display '%s'", name)


def _render_block(block, index: int, cells: dict) -> str:
    """Render the inner content of a layout block."""
    if isinstance(block, TableBlock):
        template = jinja_env.get_template("components/table.html")
    elif isinstance(block, GridBlock):
        template = jinja_env.get_template("components/grid.html")
    elif isinstance(block, CellsBlock):
        template = jinja_env.get_template("components/cells.html")
    else:
        return ""

    return template.render(block=block, cells=cells, block_index=index)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "slama.web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
