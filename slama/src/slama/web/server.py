"""FastAPI web server for SMA monitor displays.

Usage:
    cd src/slama
    uvicorn slama.web.server:app --reload --port 8000

Or with CLI options (sets SMAX_HOST / SMAX_PORT before uvicorn starts):
    python -m slama.web.server [--smax-host HOST] [--smax-port PORT]
                               [--computed-max-age SECONDS]
                               [--faults-json PATH]
                               [--web-port PORT] [--reload]

Environment variables (used when launching via plain uvicorn):
    SMAX_HOST   SMAX/Redis server hostname (default: localhost)
    SMAX_PORT   SMAX/Redis server port     (default: 6380)
    SLAMA_COMPUTED_MAX_AGE_S   Computed-point no-data age, s (default: 6; inf = off)
    SLAMA_FAULTS_JSON          faults.json drawn by /display/faults (default: conf/faults.json)
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

from .data_bridge import DEFAULT_COMPUTED_MAX_AGE_S, DataBridge
from .display_config import (
    DisplayConfig,
    TableBlock,
    GridBlock,
    CellsBlock,
    load_display_config,
    list_display_configs,
)
from .fault_page import (
    PAGE_NAME as FAULT_PAGE_NAME,
    FaultPage,
    FaultPageData,
    FaultPageReader,
)

logger = logging.getLogger(__name__)

# --- Paths ---
_WEB_DIR = Path(__file__).parent
_TEMPLATE_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"
_CONF_DIR = _WEB_DIR.parent / "conf"
_DISPLAYS_DIR = _CONF_DIR / "displays"
_SMAX_JSON_PATH = _CONF_DIR / "smax.json"
_FAULTS_JSON_PATH = _CONF_DIR / "faults.json"

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

def _computed_max_age_from_env() -> float:
    """Read the computed-point freshness limit from the environment.

    Returns
    -------
    float
        ``SLAMA_COMPUTED_MAX_AGE_S`` in seconds (``inf`` allowed, meaning
        never stale), or :data:`~slama.web.data_bridge.DEFAULT_COMPUTED_MAX_AGE_S`
        when the variable is unset or empty.

    Raises
    ------
    ValueError
        If the value is not a number, is NaN, or is negative.
    """
    raw = os.environ.get("SLAMA_COMPUTED_MAX_AGE_S", "").strip()
    if not raw:
        return DEFAULT_COMPUTED_MAX_AGE_S
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"SLAMA_COMPUTED_MAX_AGE_S must be a number or 'inf', got {raw!r}"
        ) from None
    if value != value or value < 0:
        raise ValueError(
            f"SLAMA_COMPUTED_MAX_AGE_S must be >= 0, got {raw!r}"
        )
    return value


# DataBridge uses lazy SMAX connection — no blocking at import/startup time.
# Host/port are read from environment variables so they can be set by the
# __main__ CLI parser before uvicorn imports this module's app object.
bridge = DataBridge(
    host=os.environ.get("SMAX_HOST", "localhost"),
    port=int(os.environ.get("SMAX_PORT", "6380")),
    smax_path=_SMAX_JSON_PATH,
    computed_max_age_s=_computed_max_age_from_env(),
)

# Pages generated in code rather than from conf/displays/*.json, by URL
# name. Each has name/description/filename/update_interval for the index
# card, read() (blocking) and context(data) for its templates.
GENERATED_PAGES: dict[str, FaultPage] = {
    FAULT_PAGE_NAME: FaultPage(
        os.environ.get("SLAMA_FAULTS_JSON") or _FAULTS_JSON_PATH,
        FaultPageReader(bridge._get_client, bridge._computed_max_age_s),
    ),
}


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
        Rendered HTML page listing the generated pages
        (:data:`GENERATED_PAGES`) and then all display configurations, as
        clickable cards.
    """
    configs = list(GENERATED_PAGES.values()) + list_display_configs(_DISPLAYS_DIR)
    template = jinja_env.get_template("index.html")
    return template.render(displays=configs)


@app.get("/display/{name}", response_class=HTMLResponse)
async def display_page(name: str):
    """Render a display page with initial data.

    Parameters
    ----------
    name : str
        A :data:`GENERATED_PAGES` name (e.g. ``"faults"``), or a display
        config filename stem (e.g., ``"tracking"``) matching a JSON file
        in the displays directory.

    Returns
    -------
    HTMLResponse
        Rendered display page, or a 404 response if the config is not
        found. If SMAX is unreachable, the page renders with ``"---"``
        placeholder values.
    """
    if name in GENERATED_PAGES:
        return await _generated_page(GENERATED_PAGES[name])

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


async def _generated_page(page) -> str:
    """Render a generated page (:data:`GENERATED_PAGES`) with initial data.

    Parameters
    ----------
    page : FaultPage
        The page.

    Returns
    -------
    str
        The rendered ``fault_page.html``. If the read fails or takes over
        5 s, the page renders with no data and the stale-heartbeat banners.
    """
    try:
        data = await asyncio.wait_for(asyncio.to_thread(page.read), timeout=5.0)
    except Exception:
        logger.warning("Could not fetch initial data for '%s'", page.filename,
                       exc_info=True)
        data = None
    if data is None and page.load_error is None:
        data = FaultPageData.unavailable("Could not read the fault state from SMAX")
    template = jinja_env.get_template("fault_page.html")
    return template.render(clock_html=Markup(_get_clock_html()), **page.context(data))


def _render_generated(page, data) -> str:
    """Render the WebSocket push of a generated page.

    Parameters
    ----------
    page : FaultPage
        The page.
    data : FaultPageData or None
        From ``page.read()``.

    Returns
    -------
    str
        The clock and the ``#fault-body`` out-of-band swap.
    """
    body = jinja_env.get_template("components/fault_sections.html").render(
        **page.context(data))
    return (_get_clock_html() + "\n"
            f'<div id="fault-body" hx-swap-oob="innerHTML">{body}</div>')


async def _ws_generated(websocket: WebSocket, page) -> None:
    """Push a generated page's body every ``page.update_interval`` seconds.

    Parameters
    ----------
    websocket : WebSocket
        Accepted connection.
    page : FaultPage
        The page. Client messages are read and ignored: the page has no
        settings (refreshing faster than the fault system ticks shows
        nothing new).
    """
    async def send_updates():
        while True:
            await asyncio.sleep(page.update_interval)
            try:
                data = await asyncio.to_thread(page.read)
            except Exception:
                # Never let one bad refresh end the socket: show a banner.
                logger.exception("Reading '%s' failed", page.filename)
                data = (None if page.load_error else
                        FaultPageData.unavailable("Could not read the fault state from SMAX"))
            await websocket.send_text(_render_generated(page, data))

    async def receive_messages():
        while True:
            await websocket.receive_text()

    send_task = asyncio.create_task(send_updates())
    receive_task = asyncio.create_task(receive_messages())
    try:
        done, pending = await asyncio.wait(
            [send_task, receive_task], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.debug("Client disconnected from display '%s'", page.filename)
    except Exception:
        logger.exception("Error in WebSocket for display '%s'", page.filename)
    finally:
        send_task.cancel()
        receive_task.cancel()


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
        A :data:`GENERATED_PAGES` name, or a display config filename
        stem (e.g., ``"tracking"``). Closes with code 4004 when neither
        matches.
    """
    await websocket.accept()

    if name in GENERATED_PAGES:
        await _ws_generated(websocket, GENERATED_PAGES[name])
        return

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
    block : TableBlock, GridBlock, or CellsBlock
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
        "--computed-max-age",
        type=float,
        default=os.environ.get("SLAMA_COMPUTED_MAX_AGE_S", DEFAULT_COMPUTED_MAX_AGE_S),
        metavar="SECONDS",
        help="Age after which a monitorsystem: point is shown as no-data; "
             "'inf' disables the check (use when viewing a replay)",
    )
    parser.add_argument(
        "--site-root",
        default=os.environ.get("SLAMA_SITE_ROOT"),
        metavar="DIR",
        help="Root that /global and /otherInstances paths resolve against "
             "(default: auto-detect, see slama.site_paths)",
    )
    parser.add_argument(
        "--faults-json",
        default=os.environ.get("SLAMA_FAULTS_JSON"),
        metavar="PATH",
        help="faults.json drawn by the Fault System page "
             "(default: conf/faults.json)",
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
    os.environ["SLAMA_COMPUTED_MAX_AGE_S"] = str(args.computed_max_age)
    if args.site_root:
        os.environ["SLAMA_SITE_ROOT"] = args.site_root
    if args.faults_json:
        os.environ["SLAMA_FAULTS_JSON"] = args.faults_json
    if args.verbose:
        print(args)

    uvicorn.run(
        "slama.web.server:app",
        host="0.0.0.0",
        port=args.web_port,
        reload=args.reload,
        log_level="info",
    )
