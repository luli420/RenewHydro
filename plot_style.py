"""
Shared matplotlib style for peer-review-journal-style figures, used by every
analysis_*.py script. Conventions follow common journal requirements
(AGU/Nature/Elsevier-style): embedded editable vector text, colorblind-safe
categorical colors, single/double-column figure widths, minimal chart junk,
panel labels, and consistent typography across all figures in the project.

Color: fixed-order Okabe & Ito (2008) categorical palette -- the standard
colorblind-safe qualitative palette used across the scientific literature
(distinguishable under deuteranopia/protanopia/tritanopia). Roles are
assigned by IDENTITY (period/scenario name), never by rank, and reused
consistently across all 5 analysis scripts so "Reference" is always black,
"rcp45" is always the same orange, etc.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless (Olivia has no display); safe as a library default too
import matplotlib.pyplot as plt

# Okabe & Ito (2008), "Color Universal Design"
OKABE_ITO = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "reddish_purple": "#CC79A7",
}

# Fixed identity -> color assignment (never cycled/reassigned by rank)
PERIOD_COLORS = {
    "Reference": OKABE_ITO["black"],
    "Near-future": OKABE_ITO["blue"],
    "Far-future": OKABE_ITO["vermillion"],
}
PERIOD_ORDER = ["Reference", "Near-future", "Far-future"]

SCENARIO_COLORS = {
    "hist": OKABE_ITO["black"],
    "rcp26": OKABE_ITO["blue"],
    "rcp45": OKABE_ITO["orange"],
    "ssp370": OKABE_ITO["vermillion"],
}
SCENARIO_ORDER = ["hist", "rcp26", "rcp45", "ssp370"]

# Figure widths (inches) matching common single/double-column journal layouts
SINGLE_COL_SIZE = (3.5, 2.6)
DOUBLE_COL_SIZE = (7.2, 3.0)
DOUBLE_COL_TALL_SIZE = (7.2, 5.2)


def apply_journal_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "legend.frameon": False,
            "axes.linewidth": 0.6,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.minor.width": 0.4,
            "ytick.minor.width": 0.4,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.linewidth": 0.4,
            "grid.alpha": 0.35,
            "grid.color": "#999999",
            "lines.linewidth": 1.2,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            # embed text as editable TrueType (not outlines/bitmaps) in
            # vector output -- required by most journals for PDF/EPS
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def new_figure(size: tuple[float, float] = SINGLE_COL_SIZE, ncols: int = 1, nrows: int = 1, **kwargs):
    """Create a figure sized so each panel keeps the intended per-panel width/height."""
    apply_journal_style()
    fig, axes = plt.subplots(nrows, ncols, figsize=(size[0] * ncols, size[1] * nrows), **kwargs)
    return fig, axes


def set_categorical_xticks(ax, labels: list[str], rotation: float = 20) -> None:
    """Explicitly fix tick positions before labeling (avoids matplotlib's
    'set_ticklabels() should only be used with a fixed number of ticks'
    warning on bar/boxplot axes)."""
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=rotation, ha="right")


def add_panel_label(ax, label: str) -> None:
    """Panel letter (a, b, c...) as a left-aligned axes title -- a dedicated
    layout slot above the axes that matplotlib's tight_layout keeps clear,
    unlike a manually-positioned ax.text at a negative x fraction, which can
    collide with a long/rotated y-axis label sitting in that same region."""
    ax.set_title(label, loc="left", fontsize=9, fontweight="bold", pad=6)


def save_figure(fig, out_path_stem: Path, formats: tuple[str, ...] = ("png", "pdf")) -> list[Path]:
    out_path_stem = Path(out_path_stem)
    out_path_stem.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in formats:
        path = out_path_stem.with_suffix(f".{fmt}")
        fig.savefig(path)
        written.append(path)
    return written
