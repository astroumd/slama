"""Sphinx configuration for the SLAMA developer documentation.

Build from the repository root (``slama/``) with::

    uv run sphinx-build -W -b html docs/source docs/_build/html
"""
import sys
from pathlib import Path

# Make ``import slama`` work for autodoc without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

project = "SLAMA"
author = "Marc Pound, Peter Teuben"
copyright = "SMA monitor, fault, alarm and web display"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "numpydoc",
]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"
exclude_patterns = ["_build"]

# MyST: ``:::`` fences for directives, and anchors so ``[](#heading)`` links
# resolve inside the design records pulled in with ``{include}``.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# numpydoc: the codebase documents everything numpydoc-style. Skip the
# per-class member tables, which otherwise warn about missing autosummary.
numpydoc_show_class_members = False
numpydoc_class_members_toctree = False

autodoc_member_order = "bysource"
autodoc_default_options = {"members": True, "show-inheritance": True}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "astropy": ("https://docs.astropy.org/en/stable/", None),
    "matplotib": ("https://matplotlib.org/stable", None),
    }

suppress_warnings = ["misc.highlighting_failure"]  # pseudo-JSON with "..." in the included design records

html_theme = "sphinx_book_theme"
html_static_path = ["static"]
