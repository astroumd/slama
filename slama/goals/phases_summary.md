Phase 1
======

What was built in Phase 1:

  1. display_config.py - Loads JSON display configs and expands {var} templates (e.g., RM:acc{ant}:FOO - 8 canonical names). Supports three block types: table, grid, cells.
  2. data_bridge.py - Connects lazily to SMAX, pulls values, checks thresholds from mpdefs.json, and returns CellData with value + CSS class. Gracefully returns "---" when SMAX
   is down.
  3. server.py - FastAPI app with index page, display page (Jinja2-rendered), and WebSocket endpoint that pushes HTML fragments every N seconds. HTMX swaps them into the DOM by
   ID.
  4. Templates - base.html (layout + HTMX/WS scripts), display.html (connects WebSocket), and component templates for each block type.
  5. tracking.json - First display config with all the monitor points from fakeobs.py: observation info cells, 8 antenna table, weather grid.

  Key design choices:
  - The DataBridge does NOT use MonitorPoint objects - it does its own threshold checking, keeping the web module independent of the smax_type requirement in
  MonitorPoint.__init__.
  - Lazy SMAX connection + 5-second timeout on initial fetch means the server starts and renders pages even when SMAX is unavailable.


fakeobs.py
=======
 What changed and why:

  1. `MonitorPoint.__init__` - smax_type is now optional (defaults to None). When None, the SmaxVarBase parent class init is skipped. This is safe because MonitorPoint's own
  properties (value, validity, table, key) don't depend on the SmaxVarBase type initialization - they use canonical_name for SMAX addressing and `_smax_result` for value storage.

  2. units - unit alias - mpdefs.json uses "units" (plural) but the constructor had unit (singular). The extra key was silently captured by `**kwargs` and discarded. Now the constructor accepts both and prefers units when unit is not provided.

  3. fakeobs.py now uses the monitor API - Instead of raw smax_client.smax_share(table, key, value) calls scattered throughout, it uses MonitorPointWriter.write(value) and
  MonitorPointUpdater.update() via self.write(canonical_name, value) and self.read(canonical_name) helper methods. This means all SMAX I/O goes through the MonitorPoint
  abstraction - if you later add logging, validation, or caching to the API, fakeobs.py gets it for free.

Phase 2
===========

Phase 2 scope: Client controls + styling refinements. The key features are:
  1. Update interval slider - client sends desired interval over WebSocket, server adjusts push rate per-connection
  2. Field visibility toggles - client can show/hide rows, server filters what it sends
  3. UTC + HST time display - observatory convention (Hawaii Standard Time = UTC-10)
  4. Polish the CSS - responsive layout, better table readability

  The HTMX WebSocket extension supports bidirectional communication - the client can send messages back to the server via forms inside the ws-connect element. This is how we'll
   implement the controls without writing JavaScript.

 **Insight**

  Phase 2 implementation details:

  1. Bidirectional WebSocket - The handler now runs two concurrent asyncio tasks: send_updates() pushes HTML fragments at the configured interval, receive_messages() listens
  for JSON settings from the client. asyncio.wait(FIRST_COMPLETED) cleanly handles disconnection from either side.
  2. Client controls with minimal JS - I initially tried pure HTMX ws-send for the controls, but HTMX's ws-send is designed for form submissions and doesn't easily handle "send
   on slider change + combine with checkbox state." A small JavaScript function (~15 lines) captures the slider value and checkbox states, serializes to JSON, and sends
  directly over the WebSocket. This is the pragmatic choice for a team with limited JS experience - the JS is isolated and straightforward.
  3. Per-connection state - Each WebSocket connection has its own state dict with interval and hidden_rows. Different users can view the same display at different update rates
  and with different rows visible. This is important for the ~100 concurrent users requirement.
  4. Hidden rows - The table template filters rows using {% if row.label not in hidden_rows %}. When the server re-renders the table block for a WebSocket update, hidden rows
  are simply omitted from the HTML. No client-side show/hide needed.


PHASE3 - add plotting time series
======================

 Phase 3 Plan: Interactive Time Series Plots                      
  The core challenge
  SMAX stores only current values, not history. We need to accumulate time series data somewhere.
  Proposed approach: Server-side ring buffer + Plotly.js modal                                                                                                                  

  1. Server-side history buffer (data_bridge.py)                                            
    - Add a collections.deque per canonical name (max ~1800 entries = 1 hour at 2s interval)   
    - Each fetch_cell() call appends (timestamp, numeric_value) to the deque                                                                                                     
    - Shared across all WebSocket connections - history starts when the server starts                                                                                      
  2. New HTTP endpoint (server.py)                                                                                                                                              
    - GET /api/history/{canonical_name} returns JSON: {"times": [...], "values": [...], "thresholds": {...}} 
    - Includes warn/error thresholds from mpdefs.json for overlay lines                                     
                          
  3. Click-to-plot interaction (display.html + new plot-modal component)                               
    - Make each data cell clickable (CSS cursor: pointer)                                              
    - Click fetches history from the HTTP endpoint and opens a Plotly.js chart in a modal overlay       
    - Plotly loaded from CDN (like HTMX), no server-side plotly dependency                            
    - Chart shows: time series line, horizontal threshold bands (warn=yellow, error=red)             
    - Modal has a close button; only one plot open at a time                                        
                                                                                                                                                                                
  4. Live plot updates                                                                                                                                                          
   - While a modal is open, the WebSocket update cycle also pushes the latest value for the plotted  point    
  - JavaScript appends the new point to the Plotly trace via Plotly.extendTraces()                                                                                              
                                                                                                                                                                                
  Files to create/modify     
------------------------                                                                        
                                                                                                         
  - data_bridge.py - add history deque, record values on fetch                                            
  - server.py - add /api/history/{name} endpoint, include plot data in WS messages                      
  - templates/display.html - add modal markup, Plotly CDN, click handlers                              
  - templates/base.html - add Plotly.js CDN link                                                      
  - static/style.css - modal overlay and plot container styles                                       
  - templates/components/table.html, grid.html, cells.html - make cells clickable                   
                                                                                                                                                                                
  What this does NOT include      
------------------------------                         
                                                                                                                                                                                
  - Persistent history (database/file storage) - that's a Phase 4+ concern                                      
  - Multi-point overlay plots - keep it to one point per plot for now                                            
                                                                                                                                                                                
  Does this plan look right, or would you like to adjust anything before I start implementing?                 
                                                                                                                                                                                
###  how much server-side memory per canonical name would be uses to store 1800 entries?                                                                                           
                                                                                                                                                                                
**Insight**

A Python collections.deque stores referencesdtoaobjects."Each entry would be a (timestamp, value) tuple. Let's estimate the memory per canonical name:
                                                                                                                                                                                
  - Each float in CPython: 28 bytes                                                                                                                  
  - Each 2-tuple of floats: 56 bytes (two floats) + 56 bytes (tuple overhead) = ~112 bytes                                                          
  - deque overhead per element: ~8 bytes (pointer in the block array)                                                                              
  - So ~120 bytes per entry                                                                                                                       
                                                                                                                                                 
  For 1800 entries: ~216 KB per canonical name                                                                                                  
                                                                                                                                               
  The tracking display has roughly 70 canonical names (56 in the table + 7 cells + 5 grid). That would be ~15 MB total for one display's worth of history - quite modest.      
                                                                                                                                                                              
  If you eventually have 10 display pages averaging 70 points each (with overlap), the worst case would be ~500 unique points : 216 KB = ~108 MB. Still reasonable for a server,
   but worth being aware of.                                                                                                                      
                                                                                                                                                                              
  In short: ~216 KB per canonical name for 1800 entries, or roughly 15 MB for the current tracking display. Very manageable. Want me to proceed with the implementation?   

Phase 3 implementation summary:
================

  - Server-side ring buffer - ``DataBridge._history`` is a dict of deque(maxlen=1800) that automatically records (timestamp, value) on every fetch_cell() call for numeric data. The
   deque is ideal here because it automatically evicts the oldest entries when full - no manual cleanup needed.                                                                 
  - Event delegation for click handling - Rather than attaching click listeners to each cell (which would break after HTMX swaps in new DOM elements), we use a single          
  document.addEventListener("click", ...) that checks evt.target.closest(".plotable"). This pattern survives DOM updates without needing to rebind handlers.                    
  - Live plot updates via htmx:wsAfterMessage - Instead of adding a separate data channel for plot updates, we piggyback on the existing WebSocket: after HTMX swaps the updated
   HTML, we read the new value from the DOM element and append it to the Plotly trace with Plotly.extendTraces(). This keeps the WebSocket protocol unchanged.                  

  Phase 3 is implemented across these files:                                                                                                                                    
========================

  - data_bridge.py - Added ``_history`` ring buffer, ``_record_history(), get_history(), has_history(), and CellData.is_numeric`` field                                                 
  - server.py - Added GET /api/history/{canonical_name:path} endpoint                                                                                                         
  - base.html - Added Plotly.js CDN script tag                                                                                                                                  
  - display.html - Added plot modal markup and ~100 lines of JavaScript for click-to-plot, Plotly rendering, live updates, and modal controls                                   
  - components/table.html, grid.html, cells.html - Added plotable class and data-canonical attribute on numeric cells                                                           
  - style.css - Added .plotable hover styles and plot modal overlay styles                                                                                                      
  - DESIGN.md - Documented Phase 3 architecture and design decisions                                                                                                            

### Please explain nginx reverse proxy

 Nginx as a reverse proxy means Nginx sits between the internet (or local network) and the Uvicorn/FastAPI server, forwarding requests on its behalf.

  - Without reverse proxy: Clients connect directly to Uvicorn on port 8000. Uvicorn is a Python application server - it works, but it's not designed to be the front-facing
  server for production.
  - With Nginx reverse proxy:
  Browser - Nginx (port 80/443) - Uvicorn (port 8000, localhost only)

  Why use it:
  - Static files - Nginx serves CSS, JS, and images much faster than Python. It's written in C and optimized for this.
  - TLS/HTTPS - Nginx handles SSL certificates so Uvicorn doesn't have to.
  - Connection buffering - Nginx absorbs slow clients, freeing Uvicorn worker threads. Important when ~100 users are connected.
  - WebSocket proxying - Nginx can forward WebSocket upgrade requests to Uvicorn while managing timeouts and keepalives.
  - Process management - If Uvicorn crashes, Nginx returns a clean 502 error instead of a connection refused.

  For the SMA control room use case (internal network, ~100 users), the biggest wins would be efficient static file serving and WebSocket connection management. If the server
  is only accessed on the local network and doesn't need HTTPS, the benefit is smaller - Uvicorn alone may be sufficient.

  In short: it's a production-hardened gateway that sits in front of the Python server. Whether it's worth setting up depends on how the SMA team plans to deploy this -
  internal-only vs. exposed to wider network. Want to discuss deployment options?

#### I will need to discuss this with the SMA team. However, please tell me more about deployment options.                                                                         

**Insight**

  Here are the main deployment options, roughly ordered from simplest to most production-hardened:

  1. Direct Uvicorn (current setup)
  Browser - Uvicorn :8000
    - What you have now - uvicorn slama.web.server:app --port 8000
    - Fine for development and small internal use
    - No automatic restart if it crashes
    - Static files served by Python (slower, but fine for <100 users)
    - No HTTPS

  2. Uvicorn + systemd service
  Browser - Uvicorn :8000 (managed by systemd)
    - Same as above, but systemd auto-starts on boot and restarts on crash
    - A .service file in /etc/systemd/system/ - about 15 lines of config
    - This is probably the sweet spot for an internal observatory tool
    - Still no HTTPS or static file optimization, but reliable
  
  3. Nginx + Uvicorn + systemd
  Browser - Nginx :80/443 - Uvicorn :8000 (localhost)
    - Nginx handles static files, TLS, and connection buffering
    - Uvicorn binds to localhost only (not exposed directly)
    - More moving parts to configure and maintain
    - Makes sense if you need HTTPS or expect heavy load

  4. Gunicorn + Uvicorn workers + Nginx
  Browser - Nginx - Gunicorn (managing multiple Uvicorn workers)
    - Gunicorn manages a pool of Uvicorn worker processes
    - Better CPU utilization on multi-core servers
    - Overkill unless you're hitting performance limits

  Recommendation for SMA:

  Option 2 (Uvicorn + systemd) is likely the right fit. The server is internal to the observatory network, the user count is modest (~100), and the team's priority is
  reliability, not scale. A systemd service gives you auto-start and crash recovery with minimal complexity. If HTTPS becomes a requirement later, you can add Nginx in front
  without changing the application code.

  Other considerations for the team discussion:

  - Which machine runs the server? It needs access to SMAX/Valkey on localhost:6380.
  - Should it start on boot? Systemd makes this trivial (systemctl enable).
  - Firewall/port access? Control room machines need to reach port 8000 (or 80 if behind Nginx).
  - Multiple environments? Dev vs. production configs (different ports, log levels, etc.).


  The application code itself doesn't change between these options - deployment is purely infrastructure configuration around the same slama.web.server:app entry point. When
  the team decides on an approach, I can help write the systemd service file and/or Nginx config.


#### Here's where things stand on the web-display branch:

  - Phase 1 - Core infrastructure (FastAPI, HTMX, display configs, SMAX bridge)
  - Phase 2 - Client controls, clock, collapsible settings, dark theme
  - Phase 3 - Plotly.js time series plots (draggable floating panel, history buffer, threshold bands)
  - Docstrings - Full numpydoc coverage on all web module Python files
  - DESIGN.md - Comprehensive documentation of all three phases

  All committed and pushed. When you're ready to discuss deployment with the team or start on Phase 4, just pick it back up.
                                                                                                                                                                                
Resume this session with:                                                                                                                                                       
claude --resume 1e7f9436-a761-49a6-8b60-79ae924617a8   
