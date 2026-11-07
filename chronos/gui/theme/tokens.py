"""Design tokens + QSS generation.

A theme is a flat dict of named colors/metrics. `build_qss(theme)` interpolates
it into one stylesheet applied app-wide (the maintainable, cross-platform path:
a full QSS looks identical on every OS and avoids the broken native dark mode).
Swap the dict to reskin — the way CC/Nawishtar are themed.
"""

from __future__ import annotations

from typing import Dict

# --------------------------------------------------------------------------- #
# Themes. "dusk" is the default: cool charcoal + a single restrained brass
# accent (time / patina). "midnight" is a cooler alt, to prove reskinning.
# --------------------------------------------------------------------------- #
DUSK: Dict[str, str] = {
    "bg":          "#16181D",
    "surface":     "#1E2129",
    "surface_alt": "#262A34",
    "border":      "#333846",
    "text":        "#E6E8EE",
    "text_muted":  "#9AA1B2",
    "text_faint":  "#8B92A2",   # >= 4.5:1 on every surface (WCAG AA)
    "accent":      "#C8A15A",   # brass
    "accent_dim":  "#8A7038",
    "sel_bg":      "#2C3040",
    "link":        "#7FA8D6",
    "danger":      "#D68A7B",
    "radius":      "7px",
    "radius_sm":   "5px",
    "ui_font":     "'Segoe UI','SF Pro Text','Noto Sans','DejaVu Sans',sans-serif",
    "serif_font":  "'Georgia','Noto Serif','DejaVu Serif',serif",
}

MIDNIGHT: Dict[str, str] = {
    **DUSK,
    "bg":          "#15171E",
    "surface":     "#1A1B26",   # tokyo-night-ish
    "surface_alt": "#20222E",
    "border":      "#2A2E3E",
    "accent":      "#7AA2F7",   # cool blue accent
    "accent_dim":  "#3D5A99",
    "sel_bg":      "#283046",
    "link":        "#7DCFFF",
}

# High contrast: every text colour >= 9:1 on its surface; borders visible.
CONTRAST: Dict[str, str] = {
    **DUSK,
    "bg":          "#000000",
    "surface":     "#0B0B0D",
    "surface_alt": "#141518",
    "border":      "#8B92A2",
    "text":        "#FFFFFF",
    "text_muted":  "#D0D4DC",
    "text_faint":  "#B4BAC6",
    "accent":      "#F2C46D",
    "accent_dim":  "#B08A3E",
    "sel_bg":      "#2A2D36",
    "link":        "#9CC8FF",
    "danger":      "#FF9C8A",
}

THEMES = {"dusk": DUSK, "midnight": MIDNIGHT, "contrast": CONTRAST}
THEME_LABELS = {"dusk": "Dusk", "midnight": "Midnight", "contrast": "High contrast"}

TEXT_SIZES = {"small": 0.9, "default": 1.0, "large": 1.15, "larger": 1.3}


def scaled(t: Dict[str, str], px: int) -> int:
    return max(9, round(px * float(t.get("scale", 1.0))))


def with_scale(t: Dict[str, str], size: str) -> Dict[str, str]:
    """A theme copy carrying the user's text-size choice."""
    return {**t, "scale": str(TEXT_SIZES.get(size, 1.0))}


def build_qss(t: Dict[str, str]) -> str:
    """One app-wide stylesheet. Hierarchy rule: only the reader is a raised
    card; timeline and stream sit flat on the window. Labels are always
    transparent so they never paint the window colour inside a card."""
    return _scale_qss(_qss(t), t)


def _arrow_url(color: str) -> str:
    """A tiny down-arrow SVG in the theme colour, cached on disk (QSS can only
    draw arrows from images once a combo box is styled)."""
    import tempfile
    from pathlib import Path
    d = Path(tempfile.gettempdir()) / "chronos_icons"
    f = d / f"arrow_{color.lstrip('#')}.svg"
    if not f.exists():
        try:
            d.mkdir(parents=True, exist_ok=True)
            f.write_text(
                "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' "
                f"viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' fill='none' "
                f"stroke='{color}' stroke-width='1.6' stroke-linecap='round' "
                "stroke-linejoin='round'/></svg>", encoding="utf-8")
        except OSError:
            return ""
    return f.as_posix()


def _check_url(color: str) -> str:
    """A tick mark for checked boxes, in the given colour."""
    import tempfile
    from pathlib import Path
    d = Path(tempfile.gettempdir()) / "chronos_icons"
    f = d / f"check_{color.lstrip('#')}.svg"
    if not f.exists():
        try:
            d.mkdir(parents=True, exist_ok=True)
            f.write_text(
                "<svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' "
                f"viewBox='0 0 15 15'><path d='M3.5 7.8l2.6 2.6 5.4-5.6' fill='none' "
                f"stroke='{color}' stroke-width='2' stroke-linecap='round' "
                "stroke-linejoin='round'/></svg>", encoding="utf-8")
        except OSError:
            return ""
    return f.as_posix()


def _scale_qss(qss: str, t: Dict[str, str]) -> str:
    import re
    return re.sub(r"font-size:\s*(\d+)px",
                  lambda m: f"font-size: {scaled(t, int(m.group(1)))}px", qss)


def _qss(t: Dict[str, str]) -> str:
    return f"""
    * {{
        font-family: {t['ui_font']};
        font-size: 13px;
        color: {t['text']};
        outline: 0;
    }}
    QMainWindow, #Root {{ background: {t['bg']}; }}
    QLabel {{ background: transparent; }}
    #BodyWrap, #ActionBar, #TopBar, #PaneHead {{ background: transparent; }}

    /* Top bar: wordmark + search, no strip of chrome */
    #Brand {{ color: {t['accent']}; font-family: {t['serif_font']};
              font-size: 18px; font-weight: 600; padding: 0 4px 0 2px; }}
    #SearchBox {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: {t['radius']};
        padding: 8px 12px;
        selection-background-color: {t['accent_dim']};
    }}
    #SearchBox:focus {{ border: 1px solid {t['accent']}; }}

    /* Pane titles: sentence case, quiet */
    #PaneTitle {{ color: {t['text']}; font-size: 13px; font-weight: 600;
                  padding: 2px 4px; }}
    #PaneCount {{ color: {t['text_faint']}; font-size: 12px; padding: 2px 4px; }}

    /* Timeline (flat) */
    #Spine {{ background: transparent; border: 0; padding: 2px; }}
    QTreeWidget {{ background: transparent; border: 0;
                   selection-background-color: transparent;
                   show-decoration-selected: 0; }}
    QTreeWidget::item {{ padding: 5px 4px; border-radius: {t['radius_sm']}; }}
    QTreeWidget::item:hover {{ background: {t['surface']}; }}
    QTreeWidget::item:selected, QTreeWidget::item:selected:active {{
        background: transparent; color: {t['accent']}; }}
    QTreeWidget::branch, QTreeWidget::branch:selected {{ background: transparent; }}

    /* Stream (flat; rows are painted by the delegate) */
    #Stream {{ background: transparent; border: 0; }}

    /* Reader: the one raised surface */
    #Reader {{ background: {t['surface']}; border: 1px solid {t['border']};
               border-radius: {t['radius']}; }}
    #ReaderTitle {{ font-size: 22px; font-weight: 600; color: {t['text']};
                    font-family: {t['serif_font']}; }}
    #Byline {{ color: {t['text_muted']}; font-size: 12px; }}
    #FetchNote {{ color: {t['text_muted']}; font-size: 12px; padding: 6px 10px;
                 border-left: 3px solid {t['accent']}; background: {t['surface_alt']}; }}
    #Provenance {{ color: {t['text_muted']}; font-size: 12px; }}
    #Tags {{ color: {t['text_faint']}; font-size: 12px; }}
    #ReaderMeta {{ color: {t['text_muted']}; font-size: 12px; }}
    #Danger {{ color: {t['danger']}; font-size: 12px; }}
    #SubHead {{ color: {t['text_muted']}; font-size: 12px; font-weight: 600;
                padding-top: 4px; }}
    QTextBrowser {{
        background: transparent; border: 0;
        font-family: {t['serif_font']}; font-size: 15px;
        color: {t['text']}; padding: 2px 0;
        selection-background-color: {t['accent_dim']};
    }}

    /* Related list */
    #RelatedList {{ background: transparent; border: 0; }}
    #RelatedList::item {{ padding: 4px 6px; border-radius: {t['radius_sm']};
                          color: {t['link']}; }}
    #RelatedList::item:hover {{ background: {t['surface_alt']}; }}
    #RelatedList::item:selected {{ background: {t['surface_alt']};
                                   color: {t['accent']}; }}

    /* Buttons: one primary, the rest quiet */
    QPushButton, QToolButton {{
        background: transparent; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; padding: 6px 12px; color: {t['text']};
    }}
    QPushButton:hover, QToolButton:hover {{ background: {t['surface_alt']};
                                            border-color: {t['accent_dim']}; }}
    QPushButton:focus, QToolButton:focus {{ border-color: {t['accent']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t['text_faint']};
                                                  border-color: {t['surface_alt']}; }}
    #PrimaryButton {{ background: {t['accent']}; border: 1px solid {t['accent']};
                      color: {t['bg']}; font-weight: 600; }}
    #PrimaryButton:hover {{ background: {t['text']}; border-color: {t['text']}; }}
    #PrimaryButton:disabled {{ background: transparent; color: {t['text_faint']};
                               border-color: {t['surface_alt']}; }}
    #FavButton {{ padding: 5px 10px; font-size: 15px; color: {t['text_muted']}; }}
    #FavButton:checked {{ color: {t['accent']}; border-color: {t['accent_dim']}; }}
    #MoreButton {{ padding: 5px 10px; }}
    #MoreButton::menu-indicator {{ image: none; width: 0; }}

    QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']};
                 border-radius: {t['radius_sm']}; padding: 5px 26px 5px 9px;
                 color: {t['text']}; min-height: 18px; }}
    QComboBox:hover {{ border-color: {t['accent_dim']}; }}
    QComboBox:focus {{ border-color: {t['accent']}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{_arrow_url(t['text_muted'])}");
                             width: 10px; height: 6px; }}
    QComboBox QAbstractItemView {{ background: {t['surface_alt']};
        border: 1px solid {t['border']}; selection-background-color: {t['sel_bg']};
        color: {t['text']}; padding: 4px; outline: 0; }}
    #SelBar {{ background: {t['surface_alt']}; border: 1px solid {t['border']};
               border-radius: {t['radius']}; }}
    #SelCount {{ color: {t['text']}; font-size: 13px; font-weight: 600; }}
    #AIAnswer {{ background: {t['surface']}; border: 1px solid {t['border']};
                 border-radius: {t['radius_sm']}; padding: 10px;
                 font-family: {t['serif_font']}; font-size: 14px; }}
    QPlainTextEdit {{ background: {t['surface']}; border: 1px solid {t['border']};
                 border-radius: {t['radius_sm']}; padding: 6px; }}
    QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 3px;
        border: 1px solid {t['text_muted']}; background: {t['surface']}; }}
    QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']};
        image: url("{_check_url(t['bg'])}"); }}
    QCheckBox::indicator:disabled {{ border-color: {t['border']}; background: transparent; }}
    QRadioButton {{ color: {t['text']}; spacing: 8px; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px;
                              border: 1px solid {t['text_muted']}; background: {t['surface']}; }}
    QRadioButton::indicator:hover {{ border-color: {t['accent']}; }}
    QRadioButton::indicator:checked {{ border-color: {t['accent']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {t['accent']}, stop:0.55 {t['accent']},
                    stop:0.62 {t['surface']}, stop:1 {t['surface']}); }}
    QRadioButton::indicator:disabled {{ border-color: {t['border']}; }}
    QCheckBox:disabled {{ color: {t['text_faint']}; }}
    #GroupTitle {{ color: {t['text']}; font-size: 14px; font-weight: 600; }}
    #Outcome {{ color: {t['text']}; font-size: 12px; }}
    QMenu {{ background: {t['surface_alt']}; border: 1px solid {t['border']};
             padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: {t['radius_sm']}; }}
    QMenu::item:selected {{ background: {t['sel_bg']}; }}
    QMenu::item:disabled {{ color: {t['text_faint']}; }}
    QMenuBar {{ background: {t['bg']}; }}
    QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background: {t['surface']}; }}

    /* Splitter, scrollbars, status */
    QSplitter::handle {{ background: {t['bg']}; }}
    QSplitter::handle:horizontal {{ width: 10px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px;
                                   min-height: 28px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px;
                                     min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {t['accent_dim']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QStatusBar {{ background: {t['bg']}; color: {t['text_faint']}; font-size: 12px; }}
    QStatusBar::item {{ border: 0; }}
    QToolTip {{ background: {t['surface_alt']}; color: {t['text']};
                border: 1px solid {t['border']}; padding: 5px 7px; }}
    QDialog {{ background: {t['bg']}; }}
    QLineEdit {{ background: {t['surface']}; border: 1px solid {t['border']};
                 border-radius: {t['radius_sm']}; padding: 5px 8px; }}
    """


def apply_palette(app, t: Dict[str, str]) -> None:
    """Palette floor under the stylesheet, so any widget the QSS doesn't name
    (dialogs, combo popups, native message boxes) is still dark on every OS."""
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    for role, key in (
        (QPalette.Window, "bg"), (QPalette.Base, "surface"),
        (QPalette.AlternateBase, "surface_alt"), (QPalette.Button, "surface_alt"),
        (QPalette.ToolTipBase, "surface_alt"), (QPalette.Text, "text"),
        (QPalette.WindowText, "text"), (QPalette.ButtonText, "text"),
        (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "text_faint"),
        (QPalette.Highlight, "accent_dim"), (QPalette.HighlightedText, "text"),
        (QPalette.Link, "link"),
    ):
        p.setColor(role, QColor(t[key]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["text_faint"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["text_faint"]))
    app.setPalette(p)
