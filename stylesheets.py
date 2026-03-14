"""Centralized Qt stylesheets for light and dark workstation themes."""

from __future__ import annotations

from string import Template


_THEME_TEMPLATE = Template(
    """
QMainWindow {
    background: $window_bg;
    color: $text;
}
QWidget#MainWindowCentral {
    background: $window_bg;
}
QDialog,
QMessageBox {
    background: $window_bg;
    color: $text;
}
QToolTip {
    background: $tooltip_bg;
    color: $tooltip_fg;
    border: 1px solid $tooltip_border;
    padding: 5px 7px;
}
QMenuBar {
    background: $menu_bg;
    color: $text;
    border: none;
    border-bottom: 1px solid $border;
    margin: 0px;
    padding: 0px;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: $hover_bg;
}
QMenu {
    background: $menu_bg;
    color: $text;
    border: 1px solid $border;
}
QMenu::item {
    padding: 6px 18px;
}
QMenu::item:selected {
    background: $selection_bg;
    color: $selection_fg;
}
QToolBar {
    background: $menu_bg;
    border: none;
    border-bottom: 1px solid $border;
    spacing: 8px;
    padding: 7px 8px;
}
QMainWindow::separator {
    background: $border;
    width: 1px;
    height: 1px;
}
QStatusBar {
    background: $status_bg;
    color: $muted;
}
QFrame#PageHeader {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#ControlPanel,
QFrame#TablePanel,
QFrame#ImagePanel {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#CommandBar,
QFrame#SubtlePanel,
QFrame#SummaryCard {
    background: $subtle_surface;
    border: 1px solid $subtle_border;
    border-radius: 10px;
}
QFrame#SummaryStrip {
    background: transparent;
    border: none;
}
QScrollArea#WizardScrollArea {
    background: transparent;
    border: none;
}
QWidget#WizardScrollViewport,
QWidget#WizardScrollContent {
    background: $window_bg;
}
QPlainTextEdit#WizardReviewEditor {
    background: $canvas_bg;
    border: 1px solid $field_border;
    border-radius: 8px;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QWidget#WizardReviewViewport {
    background: $canvas_bg;
}
QGroupBox {
    background: transparent;
    border: 1px solid $subtle_border;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: $heading;
    font-weight: 600;
    background: $window_bg;
}
QLabel {
    color: $text;
    font-weight: 400;
}
QLabel#PageHeaderTitle {
    color: $heading;
    font-size: 20px;
    font-weight: 650;
}
QLabel#PageHeaderSubtitle {
    color: $muted;
    font-size: 12px;
}
QLabel#SectionTitle {
    color: $heading;
    font-weight: 600;
    font-size: 12px;
}
QLabel#MutedLabel {
    color: $muted;
}
QLabel#SummaryValue {
    color: $heading;
    font-size: 16px;
    font-weight: 650;
}
QLabel#SummaryLabel {
    color: $muted;
    font-size: 11px;
}
QLabel#StatusChip {
    background: $chip_bg;
    border: 1px solid $chip_border;
    border-radius: 999px;
    color: $heading;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 650;
}
QLabel#StatusChip[statusLevel="neutral"] {
    background: $chip_bg;
    border-color: $chip_border;
    color: $heading;
}
QLabel#StatusChip[statusLevel="info"] {
    background: $info_bg;
    border-color: $info_border;
    color: $info_fg;
}
QLabel#StatusChip[statusLevel="success"] {
    background: $success_bg;
    border-color: $success_border;
    color: $success_fg;
}
QLabel#StatusChip[statusLevel="warning"] {
    background: $warning_bg;
    border-color: $warning_border;
    color: $warning_fg;
}
QLabel#StatusChip[statusLevel="error"] {
    background: $error_bg;
    border-color: $error_border;
    color: $error_fg;
}
QFrame#SummaryCard[statusLevel="info"] {
    border-color: $info_border;
}
QFrame#SummaryCard[statusLevel="success"] {
    border-color: $success_border;
}
QFrame#SummaryCard[statusLevel="warning"] {
    border-color: $warning_border;
}
QFrame#SummaryCard[statusLevel="error"] {
    border-color: $error_border;
}
QLabel#ImagePreview {
    background: $canvas_bg;
    border: 1px solid $border;
    border-radius: 10px;
    color: $muted;
    padding: 8px;
}
QLineEdit,
QDoubleSpinBox,
QSpinBox,
QComboBox {
    background: $field_bg;
    border: 1px solid $field_border;
    border-radius: 8px;
    padding: 5px 7px;
    color: $text;
    font-weight: 400;
}
QLineEdit:focus,
QDoubleSpinBox:focus,
QSpinBox:focus,
QComboBox:focus {
    border: 1px solid $focus_border;
}
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $field_border;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QFileDialog,
QFileDialog QWidget {
    background: $window_bg;
    color: $text;
}
QFileDialog QListView,
QFileDialog QTreeView {
    background: $surface;
    border: 1px solid $field_border;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QFileDialog QHeaderView::section {
    background: $header_bg;
    color: $text;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px;
    font-weight: 500;
}
QFileDialog QToolButton {
    background: $subtle_surface;
    border: 1px solid $field_border;
    border-radius: 6px;
    padding: 3px;
    color: $text;
}
QFileDialog QToolButton:hover {
    background: $hover_bg;
}
QCheckBox {
    color: $text;
    spacing: 6px;
    font-weight: 400;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $checkbox_border;
    border-radius: 4px;
    background: $canvas_bg;
}
QCheckBox::indicator:checked {
    background: $accent;
    border: 1px solid $accent;
}
QPushButton {
    background: $button_bg;
    border: 1px solid $button_border;
    border-radius: 8px;
    padding: 6px 12px;
    color: $text;
    font-weight: 500;
}
QPushButton:hover {
    background: $hover_bg;
}
QToolButton#DisclosureButton {
    background: $button_bg;
    border: 1px solid $button_border;
    border-radius: 8px;
    padding: 6px 10px;
    color: $text;
    font-weight: 500;
    text-align: left;
}
QToolButton#DisclosureButton:hover {
    background: $hover_bg;
}
QToolButton#DisclosureButton:checked {
    background: $selection_bg;
    border: 1px solid $focus_border;
    color: $selection_fg;
}
QPushButton#AccentButton {
    background: $accent;
    border-color: $accent;
    color: #ffffff;
    font-weight: 650;
}
QPushButton#AccentButton:hover {
    background: $accent_hover;
    border-color: $accent_hover;
}
QTabWidget::pane {
    background: $window_bg;
    border-left: 1px solid $border;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
    border-top: 0px;
    border-radius: 8px;
    top: -1px;
}
QTabBar {
    background: transparent;
}
QTabBar::base {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: $tab_bg;
    color: $text;
    border: 1px solid $border;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 12px;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background: $surface;
    color: $heading;
    font-weight: 650;
}
QTableWidget,
QTableView {
    background: $surface;
    alternate-background-color: $alt_surface;
    gridline-color: $gridline;
    border: none;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QTreeWidget,
QTreeView {
    background: $surface;
    alternate-background-color: $alt_surface;
    border: 1px solid $border;
    border-radius: 8px;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QWidget#EbusInspectTreeViewport {
    background: $surface;
}
QListWidget,
QListView {
    background: $surface;
    alternate-background-color: $alt_surface;
    border: 1px solid $border;
    border-radius: 8px;
    color: $text;
    selection-background-color: $selection_bg;
    selection-color: $selection_fg;
}
QListWidget::item,
QListView::item {
    padding: 4px 6px;
}
QTableView::item {
    padding: 4px;
}
QTableCornerButton::section {
    background: $header_bg;
    border: none;
    border-bottom: 1px solid $border;
}
QHeaderView {
    background: $header_bg;
}
QHeaderView::section {
    background: $header_bg;
    color: $text;
    border: none;
    border-bottom: 1px solid $border;
    padding: 8px;
    font-weight: 600;
}
QWidget#EbusInspectTreeHeaderViewport {
    background: $header_bg;
}
QTreeWidget#EbusInspectTree QScrollBar:vertical,
QTreeWidget#EbusInspectTree QScrollBar:horizontal {
    background: $surface;
    border: 1px solid $border;
    border-radius: 6px;
}
QTreeWidget#EbusInspectTree QScrollBar::handle:vertical,
QTreeWidget#EbusInspectTree QScrollBar::handle:horizontal {
    background: $field_border;
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}
QTreeWidget#EbusInspectTree QScrollBar::add-line:vertical,
QTreeWidget#EbusInspectTree QScrollBar::sub-line:vertical,
QTreeWidget#EbusInspectTree QScrollBar::add-line:horizontal,
QTreeWidget#EbusInspectTree QScrollBar::sub-line:horizontal {
    background: $surface;
    border: none;
}
QTreeWidget#EbusInspectTree QScrollBar::add-page:vertical,
QTreeWidget#EbusInspectTree QScrollBar::sub-page:vertical,
QTreeWidget#EbusInspectTree QScrollBar::add-page:horizontal,
QTreeWidget#EbusInspectTree QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""
)


def _build_theme(palette: dict[str, str]) -> str:
    """Render one stylesheet from a semantic palette."""
    return _THEME_TEMPLATE.substitute(palette)


LIGHT_THEME = _build_theme(
    {
        "window_bg": "#f3f6fb",
        "surface": "#ffffff",
        "subtle_surface": "#eef3fb",
        "alt_surface": "#f8fbff",
        "canvas_bg": "#f8fbff",
        "menu_bg": "#ffffff",
        "header_bg": "#eef3fb",
        "status_bg": "#eef3fb",
        "text": "#1f2937",
        "heading": "#0f172a",
        "muted": "#5f6b7a",
        "border": "#dce5f2",
        "subtle_border": "#e4ebf7",
        "field_bg": "#ffffff",
        "field_border": "#c7d6ea",
        "checkbox_border": "#94a3b8",
        "button_bg": "#eef3fb",
        "button_border": "#d4e0f0",
        "hover_bg": "#e4ebf7",
        "tab_bg": "#eef3fb",
        "gridline": "#edf2f9",
        "selection_bg": "#dbeafe",
        "selection_fg": "#1f2937",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "focus_border": "#3b82f6",
        "tooltip_bg": "#ffffff",
        "tooltip_fg": "#1f2937",
        "tooltip_border": "#c7d6ea",
        "chip_bg": "#eef3fb",
        "chip_border": "#d4e0f0",
        "info_bg": "#e0f2fe",
        "info_border": "#7dd3fc",
        "info_fg": "#0c4a6e",
        "success_bg": "#dcfce7",
        "success_border": "#86efac",
        "success_fg": "#166534",
        "warning_bg": "#fef3c7",
        "warning_border": "#fcd34d",
        "warning_fg": "#92400e",
        "error_bg": "#fee2e2",
        "error_border": "#fca5a5",
        "error_fg": "#991b1b",
    }
)


DARK_THEME = _build_theme(
    {
        "window_bg": "#111827",
        "surface": "#1f2937",
        "subtle_surface": "#273548",
        "alt_surface": "#243140",
        "canvas_bg": "#0f172a",
        "menu_bg": "#1f2937",
        "header_bg": "#2b3a4d",
        "status_bg": "#0f172a",
        "text": "#e5e7eb",
        "heading": "#f3f4f6",
        "muted": "#9ca3af",
        "border": "#334155",
        "subtle_border": "#3b4c61",
        "field_bg": "#1f2937",
        "field_border": "#475569",
        "checkbox_border": "#64748b",
        "button_bg": "#334155",
        "button_border": "#475569",
        "hover_bg": "#3f5065",
        "tab_bg": "#2b3a4d",
        "gridline": "#334155",
        "selection_bg": "#1d4ed8",
        "selection_fg": "#f3f4f6",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "focus_border": "#60a5fa",
        "tooltip_bg": "#1f2937",
        "tooltip_fg": "#f3f4f6",
        "tooltip_border": "#475569",
        "chip_bg": "#334155",
        "chip_border": "#475569",
        "info_bg": "#082f49",
        "info_border": "#0ea5e9",
        "info_fg": "#e0f2fe",
        "success_bg": "#052e16",
        "success_border": "#22c55e",
        "success_fg": "#dcfce7",
        "warning_bg": "#451a03",
        "warning_border": "#f59e0b",
        "warning_fg": "#fef3c7",
        "error_bg": "#450a0a",
        "error_border": "#ef4444",
        "error_fg": "#fee2e2",
    }
)
