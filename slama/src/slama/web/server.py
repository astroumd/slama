"""FastAPI web server for SMA monitor displays.

Usage:
    cd src/slama
    uvicorn slama.web.server:app --reload --port 8000

Or with CLI options (sets SMAX_HOST / SMAX_PORT before uvicorn starts):
    python -m slama.web.server [--smax-host HOST] [--smax-port PORT]
                               [--web-port PORT] [--reload]

Environment variables (used when launching via plain uvicorn):
    SMAX_HOST   SMAX/Redis server hostname (default: localhost)
    SMAX_PORT   SMAX/Redis server port     (default: 6380)
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .data_bridge import DataBridge
from .display_config import (
    DisplayConfig,
    TableBlock,
    MatrixBlock,
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
_SMAX_JSON_PATH = _CONF_DIR / "smax.json"

# Hawaii Standard Time (UTC-10, no daylight saving)
_HST = timezone(timedelta(hours=-10))

# --- Jinja2 ---
jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

# --- FastAPI app ---
app = FastAPI(title="SMA Monitor Display")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# DataBridge uses lazy SMAX connection — no blocking at import/startup time.
# Host/port are read from environment variables so they can be set by the
# __main__ CLI parser before uvicorn imports this module's app object.
bridge = DataBridge(
    host=os.environ.get("SMAX_HOST", "localhost"),
    port=int(os.environ.get("SMAX_PORT", "6380")),
    smax_path=_SMAX_JSON_PATH,
)


def _get_clock_html() -> str:
    """Return HTML fragment with current UTC, HST, and local times.

    Returns
    -------
    str
        ``<span>`` element with ``hx-swap-oob="innerHTML"`` containing
        formatted UTC, HST, and local server times.
    """
    now_utc = datetime.now(timezone.utc)
    now_hst = now_utc.astimezone(_HST)
    now_local = datetime.now().astimezone()
    local_abbr = now_local.strftime("%Z")
    # todo if local_abbr == "HST" don't even show it?
    return (
        f'<span id="clock" hx-swap-oob="innerHTML">'
        f'UTC {now_utc.strftime("%H:%M:%S")} &nbsp; '
        f'HST {now_hst.strftime("%H:%M:%S")} &nbsp; '
        f'Local ({local_abbr}) {now_local.strftime("%H:%M:%S")}'
        f'</span>'
    )


# ------------------------------------------------------------------
# HTTP routes
# ------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """List all available display pages.

    Returns
    -------
    str
        Rendered HTML page listing all display configurations as
        clickable cards.
    """
    configs = list_display_configs(_DISPLAYS_DIR)
    template = jinja_env.get_template("index.html")
    return template.render(displays=configs)


@app.get("/display/{name}", response_class=HTMLResponse)
async def display_page(name: str):
    """Render a display page with initial data.

    Parameters
    ----------
    name : str
        Display config filename stem (e.g., ``"tracking"``). Must match
        a JSON file in the displays directory.

    Returns
    -------
    HTMLResponse
        Rendered display page, or a 404 response if the config is not
        found. If SMAX is unreachable, the page renders with ``"---"``
        placeholder values.
    """
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

    # Collect all row labels for the visibility controls
    all_row_labels = []
    for block in config.layout:
        if isinstance(block, TableBlock):
            for row in block.rows:
                if row["label"] not in all_row_labels:
                    all_row_labels.append(row["label"])

    template = jinja_env.get_template("display.html")
    return template.render(
        config=config,
        cells=cells,
        all_row_labels=all_row_labels,
        hidden_rows=[],
        clock_html=Markup(_get_clock_html()),
        TableBlock=TableBlock,
        GridBlock=GridBlock,
        CellsBlock=CellsBlock,
    )


# ------------------------------------------------------------------
# History API endpoint — returns JSON for Plotly.js plots
# ------------------------------------------------------------------

@app.get("/api/history/{canonical_name:path}")
async def get_history(canonical_name: str):
    """Return time series history for a monitor point.

    The canonical_name is passed as a path parameter so that colons
    in names like ``RM:acc1:RM_TRACK_EL_F`` are preserved.

    Parameters
    ----------
    canonical_name : str
        SMAX canonical name (e.g., ``RM:acc1:RM_TRACK_EL_F``).

    Returns
    -------
    JSONResponse
        JSON with keys ``"canonical_name"``, ``"times"``,
        ``"values"``, and ``"thresholds"``.
    """
    history = bridge.get_history(canonical_name)
    if not history["times"]:
        return JSONResponse(history, status_code=200)
    return JSONResponse(history)


# ------------------------------------------------------------------
# WebSocket endpoint — bidirectional
# ------------------------------------------------------------------

@app.websocket("/ws/display/{name}")
async def ws_display(websocket: WebSocket, name: str):
    """Push live updates and receive client settings changes.

    Runs two concurrent asyncio tasks sharing per-connection state:
    ``send_updates`` pushes HTML fragments at the configured interval,
    and ``receive_messages`` listens for JSON settings from the client.

    Parameters
    ----------
    websocket : WebSocket
        FastAPI WebSocket connection.
    name : str
        Display config filename stem (e.g., ``"tracking"``).
    """
    await websocket.accept()

    config_path = _DISPLAYS_DIR / f"{name}.json"
    if not config_path.exists():
        await websocket.close(code=4004, reason=f"Display '{name}' not found")
        return

    config = load_display_config(config_path)

    # Per-connection state
    state = {
        "interval": config.update_interval,
        "hidden_rows": set(),
    }

    async def send_updates():
        """Push data updates at the configured interval."""
        while True:
            await asyncio.sleep(state["interval"])

            cells = await asyncio.to_thread(bridge.fetch_all, config)

            html_parts = [_get_clock_html()]
            for i, block in enumerate(config.layout):
                block_html = _render_block(block, i, cells, state["hidden_rows"])
                html_parts.append(
                    f'<div id="block-{i}" hx-swap-oob="innerHTML">'
                    f'{block_html}</div>'
                )

            await websocket.send_text("\n".join(html_parts))

    async def receive_messages():
        """Listen for client settings changes (interval, row visibility)."""
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if "interval" in data:
                new_interval = float(data["interval"])
                state["interval"] = max(0.5, min(30.0, new_interval))
                logger.debug("Client changed interval to %.1f", state["interval"])

            if "hidden_rows" in data:
                state["hidden_rows"] = set(data["hidden_rows"])
                logger.debug("Client changed hidden rows: %s", state["hidden_rows"])

    send_task = asyncio.create_task(send_updates())
    receive_task = asyncio.create_task(receive_messages())

    try:
        done, pending = await asyncio.wait(
            [send_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        # Re-raise any exceptions from completed tasks
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.debug("Client disconnected from display '%s'", name)
    except Exception:
        logger.exception("Error in WebSocket for display '%s'", name)
    finally:
        send_task.cancel()
        receive_task.cancel()


def _render_block(block, index: int, cells: dict,
                  hidden_rows: set = None) -> str:
    """Render the inner content of a layout block.

    Parameters
    ----------
    block : TableBlock, MatrixBlock, GridBlock, or CellsBlock
        Layout block to render.
    index : int
        Zero-based block index, used for the block's HTML id.
    cells : dict of str to CellData
        Mapping of canonical name to cell data for template rendering.
    hidden_rows : set of str or None, optional
        Row labels to hide in table blocks. Default is None (no rows
        hidden).

    Returns
    -------
    str
        Rendered HTML fragment for the block interior, or empty string
        if the block type is unrecognized.
    """
    if hidden_rows is None:
        hidden_rows = set()

    if isinstance(block, TableBlock):
        template = jinja_env.get_template("components/table.html")
    elif isinstance(block, MatrixBlock):
        template = jinja_env.get_template("components/matrix.html")
    elif isinstance(block, GridBlock):
        template = jinja_env.get_template("components/grid.html")
    elif isinstance(block, CellsBlock):
        template = jinja_env.get_template("components/cells.html")
    else:
        return ""

    return template.render(
        block=block, cells=cells, block_index=index,
        hidden_rows=hidden_rows,
    )


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="SMA Monitor web server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--smax-host",
        default=os.environ.get("SMAX_HOST", "localhost"),
        metavar="HOST",
        help="SMAX/Redis server hostname",
    )
    parser.add_argument(
        "--smax-port",
        type=int,
        default=int(os.environ.get("SMAX_PORT", "6380")),
        metavar="PORT",
        help="SMAX/Redis server port",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8000,
        metavar="PORT",
        help="Web server port to listen on",
    )
    parser.add_argument(
        "-r", "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print debugging info",
    )
    args = parser.parse_args()

    # Set env vars so the module-level DataBridge picks them up on import
    os.environ["SMAX_HOST"] = args.smax_host
    os.environ["SMAX_PORT"] = str(args.smax_port)
    if args.verbose:
        print(args)

    uvicorn.run(
        "slama.web.server:app",
        host="0.0.0.0",
        port=args.web_port,
        reload=args.reload,
        log_level="info",
    )
