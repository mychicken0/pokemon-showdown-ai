#!/usr/bin/env python3
"""Modern local desktop dashboard for doubles decision audit graphs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsDropShadowEffect,
        QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
        QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
        QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QStyle,
        QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    )
except ImportError as exc:
    print(
        "PySide6 is required for the decision dashboard.\n"
        "Install it locally with: venv/bin/pip install 'PySide6>=6.7,<7'",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

from doubles_decision_graph_model import (
    DecisionStore,
    IncrementalJsonlTail,
    action_stories,
    build_turn_graph,
    calculate_graph_layout,
    describe_joint_order,
    inspector_sections,
    ranked_candidates,
    turn_summary,
)


PALETTE = {
    "root": ("#1e293b", "#94a3b8"),
    "context": ("#172554", "#3b82f6"),
    "opponent": ("#4c1d3d", "#ec4899"),
    "candidate": ("#172554", "#3b82f6"),
    "selected": ("#052e2b", "#10b981"),
    "action": ("#2e1065", "#8b5cf6"),
    "blocked": ("#450a0a", "#ef4444"),
    "warning": ("#451a03", "#f59e0b"),
    "reason": ("#083344", "#06b6d4"),
    "outcome": ("#042f2e", "#14b8a6"),
}

STYLE_SHEET = """
QWidget {
    background: #0b1120;
    color: #dbeafe;
    font-family: "Ubuntu Sans", "DejaVu Sans";
    font-size: 13px;
}
QMainWindow, QSplitter { background: #080d19; }
QFrame#header, QFrame#summaryBar, QFrame#panel {
    background: #111827;
    border: 1px solid #1f2937;
}
QFrame#header { border-radius: 12px; }
QFrame#panel { border-radius: 12px; }
QLabel#title { font-size: 19px; font-weight: 700; color: #f8fafc; }
QLabel#subtitle { color: #64748b; font-size: 11px; }
QLabel#panelTitle { font-size: 12px; font-weight: 700; color: #94a3b8; }
QLabel#cardValue { font-size: 22px; font-weight: 700; color: #f8fafc; }
QLabel#cardLabel { color: #64748b; font-size: 11px; }
QLabel#actorName { color: #f8fafc; font-size: 16px; font-weight: 700; }
QLabel#moveName { color: #c4b5fd; font-size: 17px; font-weight: 700; }
QLabel#reasonText { color: #94a3b8; font-size: 11px; }
QLabel#badge {
    background: #172554; color: #93c5fd; border: 1px solid #1d4ed8;
    border-radius: 10px; padding: 4px 10px; font-weight: 600;
}
QPushButton, QToolButton {
    background: #172033; color: #dbeafe; border: 1px solid #334155;
    border-radius: 8px; padding: 7px 12px; font-weight: 600;
}
QPushButton:hover, QToolButton:hover { background: #243148; border-color: #3b82f6; }
QPushButton:pressed, QToolButton:pressed { background: #1d4ed8; }
QComboBox, QSpinBox {
    background: #0f172a; border: 1px solid #334155; border-radius: 8px;
    padding: 6px 9px; color: #e2e8f0;
}
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView {
    background: #111827; border: 1px solid #334155; selection-background-color: #1d4ed8;
}
QCheckBox { spacing: 7px; color: #94a3b8; }
QSlider::groove:horizontal { height: 4px; background: #243148; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -5px 0; background: #3b82f6; border-radius: 7px;
}
QListWidget, QTreeWidget, QPlainTextEdit, QTabWidget::pane {
    background: #0f172a; border: 0; border-radius: 8px;
}
QListWidget::item { border: 0; padding: 0; }
QListWidget::item:selected { background: transparent; }
QTreeWidget { alternate-background-color: #111827; }
QTreeWidget::item { padding: 5px; border-bottom: 1px solid #1e293b; }
QHeaderView::section { background: #111827; color: #64748b; border: 0; padding: 6px; }
QTabBar::tab {
    background: #111827; color: #64748b; padding: 8px 11px; border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #dbeafe; border-bottom-color: #3b82f6; }
QProgressBar { background: #1e293b; border: 0; border-radius: 2px; height: 4px; }
QProgressBar::chunk { background: #3b82f6; border-radius: 2px; }
QScrollBar:vertical { background: #0f172a; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #334155; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _display_number(value, decimals=2):
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


class SummaryCard(QFrame):
    def __init__(self, label, accent="#3b82f6"):
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumHeight(82)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(2)
        self.label = QLabel(label.upper())
        self.label.setObjectName("cardLabel")
        self.value = QLabel("N/A")
        self.value.setObjectName("cardValue")
        self.accent = QFrame()
        self.accent.setFixedHeight(3)
        self.accent.setStyleSheet(f"background:{accent};border-radius:1px;")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addStretch()
        layout.addWidget(self.accent)

    def set_value(self, value, color=None):
        self.value.setText(str(value))
        if color:
            self.value.setStyleSheet(f"color:{color};")
        else:
            self.value.setStyleSheet("")


class ActionStoryCard(QFrame):
    clicked = Signal(object)

    def __init__(self, slot):
        super().__init__()
        self.story = {}
        self.setObjectName("panel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 11, 15, 11)
        layout.setSpacing(4)
        top = QHBoxLayout()
        slot_label = QLabel(f"SLOT {slot} DECISION")
        slot_label.setObjectName("cardLabel")
        self.score_label = QLabel("Score N/A")
        self.score_label.setObjectName("cardLabel")
        top.addWidget(slot_label)
        top.addStretch()
        top.addWidget(self.score_label)
        action_row = QHBoxLayout()
        self.actor_label = QLabel("No active Pokémon")
        self.actor_label.setObjectName("actorName")
        arrow = QLabel("  USES  ")
        arrow.setStyleSheet("color:#475569;font-size:10px;font-weight:700;")
        self.move_label = QLabel("Pass")
        self.move_label.setObjectName("moveName")
        self.target_label = QLabel("")
        self.target_label.setStyleSheet("color:#67e8f9;font-size:15px;font-weight:700;")
        action_row.addWidget(self.actor_label)
        action_row.addWidget(arrow)
        action_row.addWidget(self.move_label)
        action_row.addWidget(self.target_label)
        action_row.addStretch()
        self.reason_label = QLabel("")
        self.reason_label.setObjectName("reasonText")
        self.reason_label.setWordWrap(True)
        layout.addLayout(top)
        layout.addLayout(action_row)
        layout.addWidget(self.reason_label)

    def set_story(self, story):
        self.story = story
        self.actor_label.setText(story["actor"])
        self.move_label.setText(story["verb"])
        self.target_label.setText(f"  →  {story['target']}" if story["target"] else "")
        self.reason_label.setText("WHY: " + "  ·  ".join(story["reasons"]))
        self.score_label.setText(f"Score {_display_number(story['score'])}")

    def mousePressEvent(self, event):
        self.clicked.emit(self.story)
        super().mousePressEvent(event)


class GraphNodeItem(QGraphicsObject):
    clicked = Signal(object)

    def __init__(self, node, layout):
        super().__init__()
        self.node = node
        self.width = layout.width
        self.height = layout.height
        self.fill, self.accent = PALETTE.get(node.kind, PALETTE["context"])
        self.setPos(layout.x, layout.y)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hovered = False
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, _option, _widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect()
        outline = QColor(self.accent)
        if self.hovered:
            outline = outline.lighter(135)
        painter.setPen(QPen(outline, 2.2 if self.hovered else 1.4))
        painter.setBrush(QColor(self.fill))
        painter.drawRoundedRect(rect, 13, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.accent))
        painter.drawRoundedRect(QRectF(0, 0, 5, self.height), 2.5, 2.5)

        label = self.node.label.split("\n")
        painter.setPen(QColor("#f8fafc"))
        title_font = QFont("Ubuntu Sans", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        y = 22
        for index, line in enumerate(label[:4]):
            if index:
                painter.setPen(QColor("#94a3b8"))
                body_font = QFont("Ubuntu Sans", 8)
                painter.setFont(body_font)
            painter.drawText(QRectF(17, y - 13, self.width - 30, 19),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += 18

        if self.node.kind in ("context", "opponent"):
            value = self.node.detail.get("value")
            if isinstance(value, dict):
                hp = value.get("hp_fraction", value.get("hp"))
                if isinstance(hp, (int, float)):
                    bar = QRectF(17, self.height - 14, self.width - 34, 4)
                    painter.setBrush(QColor("#1e293b"))
                    painter.drawRoundedRect(bar, 2, 2)
                    painter.setBrush(QColor("#22c55e" if hp > .5 else "#f59e0b" if hp > .2 else "#ef4444"))
                    painter.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * max(0, min(1, hp)), 4), 2, 2)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self.clicked.emit(self.node)
        super().mousePressEvent(event)


class DecisionGraphView(QGraphicsView):
    node_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QColor("#080d19"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.node_items = {}

    def set_graph(self, nodes, edges):
        scene = self.scene()
        scene.clear()
        self.node_items = {}
        layouts = calculate_graph_layout(nodes)
        for edge in edges:
            source = layouts.get(edge.source)
            target = layouts.get(edge.target)
            if not source or not target:
                continue
            start = QPointF(source.x + source.width, source.y + source.height / 2)
            end = QPointF(target.x, target.y + target.height / 2)
            path = QPainterPath(start)
            distance = max(70.0, (end.x() - start.x()) * .48)
            path.cubicTo(start.x() + distance, start.y(), end.x() - distance, end.y(), end.x(), end.y())
            item = QGraphicsPathItem(path)
            color = "#34d399" if edge.kind == "selected" else "#334155"
            item.setPen(QPen(QColor(color), 2.2 if edge.kind == "selected" else 1.4))
            item.setZValue(-2)
            scene.addItem(item)
        for node in nodes:
            item = GraphNodeItem(node, layouts[node.node_id])
            item.clicked.connect(self.node_selected.emit)
            scene.addItem(item)
            self.node_items[node.node_id] = item
        if layouts:
            right = max(layout.x + layout.width for layout in layouts.values())
            bottom = max(layout.y + layout.height for layout in layouts.values())
            scene.setSceneRect(QRectF(0, 0, right + 45, bottom + 45))
        self.fit_graph()

    def fit_graph(self):
        if self.scene().items():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() < .72:
                self.resetTransform()
                self.scale(.72, .72)
                self.centerOn(self.scene().sceneRect().center())

    def reset_zoom(self):
        self.resetTransform()

    def focus_node(self, node_id):
        item = self.node_items.get(node_id)
        if item:
            self.centerOn(item)
            self.node_selected.emit(item.node)

    def wheelEvent(self, event):
        factor = 1.16 if event.angleDelta().y() > 0 else 1 / 1.16
        current = self.transform().m11()
        if 0.18 < current * factor < 4.5:
            self.scale(factor, factor)


class CandidateCard(QWidget):
    def __init__(self, rank, candidate, minimum, maximum):
        super().__init__()
        selected = candidate["selected"]
        self.setStyleSheet(
            "CandidateCard { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (("#052e2b", "#10b981") if selected else ("#111827", "#243148"))
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(5)
        header = QHBoxLayout()
        rank_label = QLabel("SELECTED" if selected else f"#{rank}")
        rank_label.setStyleSheet(f"color:{'#34d399' if selected else '#64748b'};font-size:10px;font-weight:700;")
        score = QLabel(_display_number(candidate["score"]))
        score.setStyleSheet("color:#f8fafc;font-weight:700;")
        header.addWidget(rank_label)
        header.addStretch()
        header.addWidget(score)
        action = QLabel(candidate.get("display") or candidate["label"])
        action.setWordWrap(True)
        action.setMaximumHeight(42)
        action.setStyleSheet("color:#cbd5e1;font-size:11px;")
        warnings = candidate.get("warnings") or []
        warning_badge = QLabel(f"⚠ {len(warnings)}" if warnings else "")
        warning_badge.setStyleSheet("color:#fbbf24;font-size:11px;font-weight:700;")
        progress = QProgressBar()
        progress.setTextVisible(False)
        progress.setRange(0, 1000)
        try:
            ratio = (float(candidate["score"]) - minimum) / max(.001, maximum - minimum)
        except (TypeError, ValueError):
            ratio = 0
        progress.setValue(int(max(0, min(1, ratio)) * 1000))
        if selected:
            progress.setStyleSheet("QProgressBar::chunk {background:#10b981;}")
        header.addWidget(warning_badge)
        layout.addLayout(header)
        layout.addWidget(action)
        layout.addWidget(progress)


class DecisionDashboard(QMainWindow):
    def __init__(self, replay=None, live=None, refresh_ms=500):
        super().__init__()
        self.setWindowTitle("Pokemon Showdown AI Decision Dashboard")
        self.resize(1680, 980)
        self.setMinimumSize(1180, 720)
        self.store = DecisionStore()
        self.tail = None
        self.source_path = ""
        self.refresh_ms = max(100, refresh_ms)
        self._build_ui()
        if live:
            self.open_live(live)
        elif replay:
            self.open_replay(replay)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_live)
        self.poll_timer.start(self.refresh_ms)

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 10)
        outer.setSpacing(10)
        self.setCentralWidget(root)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        title_box = QVBoxLayout()
        title = QLabel("Decision Intelligence")
        title.setObjectName("title")
        subtitle = QLabel("Local doubles battle reasoning audit")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box)
        self.source_badge = QLabel("NO SOURCE")
        self.source_badge.setObjectName("badge")
        header_layout.addWidget(self.source_badge)
        header_layout.addSpacing(8)

        replay_button = QPushButton("Open Replay")
        replay_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        replay_button.clicked.connect(self.choose_replay)
        live_button = QPushButton("Open Live")
        live_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        live_button.clicked.connect(self.choose_live)
        header_layout.addWidget(replay_button)
        header_layout.addWidget(live_button)
        header_layout.addSpacing(10)
        self.battle_box = QComboBox()
        self.battle_box.setMinimumWidth(330)
        self.battle_box.currentTextChanged.connect(self._battle_changed)
        header_layout.addWidget(self.battle_box, 1)
        self.prev_button = QToolButton()
        self.prev_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.prev_button.clicked.connect(lambda: self.step_turn(-1))
        self.next_button = QToolButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.next_button.clicked.connect(lambda: self.step_turn(1))
        header_layout.addWidget(self.prev_button)
        self.turn_slider = QSlider(Qt.Orientation.Horizontal)
        self.turn_slider.setMinimumWidth(140)
        self.turn_slider.valueChanged.connect(self._turn_control_changed)
        header_layout.addWidget(self.turn_slider)
        self.turn_spin = QSpinBox()
        self.turn_spin.setPrefix("Turn ")
        self.turn_spin.valueChanged.connect(self._turn_control_changed)
        header_layout.addWidget(self.turn_spin)
        header_layout.addWidget(self.next_button)
        self.live_follow = QCheckBox("Live follow")
        self.live_follow.setChecked(True)
        self.pause = QCheckBox("Pause")
        header_layout.addWidget(self.live_follow)
        header_layout.addWidget(self.pause)
        outer.addWidget(header)

        summary = QFrame()
        summary.setObjectName("summaryBar")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        self.score_card = SummaryCard("Selected score", "#10b981")
        self.gap_card = SummaryCard("Score gap", "#3b82f6")
        self.orders_card = SummaryCard("Legal orders", "#8b5cf6")
        self.signal_card = SummaryCard("Decision signal", "#f59e0b")
        for card in (self.score_card, self.gap_card, self.orders_card, self.signal_card):
            summary_layout.addWidget(card, 1)
        outer.addWidget(summary)

        story_row = QHBoxLayout()
        story_row.setSpacing(10)
        self.action_cards = [ActionStoryCard(1), ActionStoryCard(2)]
        for card in self.action_cards:
            card.clicked.connect(self._story_selected)
            story_row.addWidget(card, 1)
        outer.addLayout(story_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_candidates_panel())
        splitter.addWidget(self._build_graph_panel())
        splitter.addWidget(self._build_inspector_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([270, 980, 350])
        outer.addWidget(splitter, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Open a replay or live JSONL stream")
        self.status_label.setObjectName("subtitle")
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("subtitle")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.stats_label)
        outer.addLayout(status_row)

    def _build_candidates_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(235)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 12, 10, 10)
        label = QLabel("RANKED CANDIDATES")
        label.setObjectName("panelTitle")
        self.candidate_list = QListWidget()
        self.candidate_list.setSpacing(7)
        self.candidate_list.currentRowChanged.connect(self._candidate_selected)
        layout.addWidget(label)
        layout.addWidget(self.candidate_list, 1)
        return panel

    def _build_graph_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(1, 1, 1, 1)
        graph_header = QHBoxLayout()
        graph_header.setContentsMargins(11, 8, 8, 4)
        label = QLabel("DECISION GRAPH")
        label.setObjectName("panelTitle")
        fit_button = QToolButton()
        fit_button.setText("Fit")
        fit_button.clicked.connect(lambda: self.graph.fit_graph())
        reset_button = QToolButton()
        reset_button.setText("100%")
        reset_button.clicked.connect(lambda: self.graph.reset_zoom())
        graph_header.addWidget(label)
        graph_header.addStretch()
        graph_header.addWidget(fit_button)
        graph_header.addWidget(reset_button)
        self.graph = DecisionGraphView()
        self.graph.node_selected.connect(self.show_detail)
        layout.addLayout(graph_header)
        layout.addWidget(self.graph, 1)
        return panel

    def _build_inspector_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 12, 10, 10)
        label = QLabel("INSPECTOR")
        label.setObjectName("panelTitle")
        self.inspector_title = QLabel("Turn overview")
        self.inspector_title.setStyleSheet("font-size:16px;font-weight:700;color:#f8fafc;")
        self.tabs = QTabWidget()
        self.inspector_trees = {}
        for name in ("Summary", "Scoring", "Safety"):
            tree = QTreeWidget()
            tree.setHeaderLabels(["Field", "Value"])
            tree.setAlternatingRowColors(True)
            tree.setColumnWidth(0, 165)
            self.inspector_trees[name] = tree
            self.tabs.addTab(tree, name)
        self.raw_detail = QPlainTextEdit()
        self.raw_detail.setReadOnly(True)
        self.raw_detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.tabs.addTab(self.raw_detail, "Raw")
        layout.addWidget(label)
        layout.addWidget(self.inspector_title)
        layout.addWidget(self.tabs, 1)
        return panel

    def choose_replay(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open audit replay", "", "JSONL (*.jsonl);;All files (*)")
        if path:
            self.open_replay(path)

    def choose_live(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open live event stream", "", "JSONL (*.jsonl);;All files (*)")
        if path:
            self.open_live(path)

    def open_replay(self, path):
        self.store = DecisionStore()
        self.store.load_path(path)
        self.tail = None
        self.source_path = path
        self.source_badge.setText("REPLAY")
        self.source_badge.setStyleSheet(
            "background:#172554;color:#93c5fd;border:1px solid #1d4ed8;border-radius:10px;padding:4px 10px;"
        )
        self.status_label.setText(os.path.basename(path))
        self._refresh_battles(False)

    def open_live(self, path):
        self.store = DecisionStore()
        self.tail = IncrementalJsonlTail(path)
        self.source_path = path
        for record in self.tail.poll():
            self.store.apply_record(record)
        self.source_badge.setText("LIVE")
        self.source_badge.setStyleSheet(
            "background:#052e2b;color:#6ee7b7;border:1px solid #059669;border-radius:10px;padding:4px 10px;"
        )
        self.status_label.setText(os.path.basename(path))
        self._refresh_battles(True)

    def _refresh_battles(self, follow_latest=False):
        tags = self.store.battle_tags()
        current = self.battle_box.currentText()
        self.battle_box.blockSignals(True)
        self.battle_box.clear()
        self.battle_box.addItems(tags)
        target = tags[-1] if tags and (follow_latest or current not in tags) else current
        if target:
            self.battle_box.setCurrentText(target)
        self.battle_box.blockSignals(False)
        self._battle_changed(target, follow_latest)

    def _battle_changed(self, battle_tag=None, follow_latest=False):
        battle_tag = battle_tag or self.battle_box.currentText()
        turns = self.store.turn_numbers(battle_tag)
        if not turns:
            self.render_current()
            return
        minimum, maximum = turns[0], turns[-1]
        current = self.turn_spin.value()
        if follow_latest or current not in turns:
            current = maximum
        for widget in (self.turn_slider, self.turn_spin):
            widget.blockSignals(True)
            widget.setRange(minimum, maximum)
            widget.setValue(current)
            widget.blockSignals(False)
        self.render_current()

    def _turn_control_changed(self, value):
        sender = self.sender()
        other = self.turn_spin if sender is self.turn_slider else self.turn_slider
        other.blockSignals(True)
        other.setValue(value)
        other.blockSignals(False)
        self.render_current()

    def step_turn(self, delta):
        turns = self.store.turn_numbers(self.battle_box.currentText())
        if not turns:
            return
        current = self.turn_spin.value()
        index = min(range(len(turns)), key=lambda i: abs(turns[i] - current))
        self.turn_spin.setValue(turns[max(0, min(len(turns) - 1, index + delta))])

    def _poll_live(self):
        if not self.tail or self.pause.isChecked():
            return
        try:
            records = self.tail.poll()
            if not records:
                return
            for record in records:
                self.store.apply_record(record)
            self._refresh_battles(self.live_follow.isChecked())
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.status_label.setText(f"{os.path.basename(self.source_path)} · {len(records)} new events · {timestamp}")
        except Exception as exc:
            self.status_label.setText(f"Live read error: {exc}")

    def render_current(self):
        battle_tag = self.battle_box.currentText()
        turn_data = self.store.get_turn(battle_tag, self.turn_spin.value())
        if not turn_data:
            self.graph.scene().clear()
            self.candidate_list.clear()
            return
        nodes, edges = build_turn_graph(battle_tag, turn_data)
        self.graph.set_graph(nodes, edges)
        self._show_candidates(turn_data)
        self._show_summary(turn_data)
        self._show_action_stories(turn_data)
        summary = turn_summary(turn_data)
        self.show_detail({
            "turn": turn_data.get("turn"),
            "chosen_plan": describe_joint_order(turn_data.get("selected_joint_order"), turn_data),
            "selected_score": turn_data.get("selected_score"),
            "score_gap_selected_best_alt": turn_data.get("score_gap_selected_best_alt"),
            "total_legal_joint_orders": turn_data.get("total_legal_joint_orders"),
            "decision_signal": summary["signal"],
            "why": [reason for story in action_stories(turn_data) for reason in story["reasons"]],
        }, "Turn overview")
        self.stats_label.setText(
            f"{len(self.store.battle_tags())} battles  ·  Turn {turn_data.get('turn', '?')}  ·  "
            f"{len(nodes)} nodes / {len(edges)} links"
        )

    def _show_candidates(self, turn_data):
        self.candidate_list.clear()
        candidates = ranked_candidates(turn_data)
        numeric = [float(item["score"]) for item in candidates if isinstance(item["score"], (int, float))]
        minimum = min(numeric, default=0)
        maximum = max(numeric, default=1)
        for rank, candidate in enumerate(candidates, 1):
            item = QListWidgetItem()
            card = CandidateCard(rank, candidate, minimum, maximum)
            item.setSizeHint(card.sizeHint())
            self.candidate_list.addItem(item)
            self.candidate_list.setItemWidget(item, card)

    def _candidate_selected(self, row):
        if row == 0:
            self.graph.focus_node("selected")
        elif row > 0:
            self.graph.focus_node(f"candidate_{row - 1}")

    def _show_summary(self, turn_data):
        summary = turn_summary(turn_data)
        self.score_card.set_value(_display_number(summary["selected_score"]), "#34d399")
        self.gap_card.set_value(_display_number(summary["score_gap"]), "#60a5fa")
        self.orders_card.set_value(summary["legal_orders"] if summary["legal_orders"] is not None else "N/A")
        signal_color = "#fbbf24" if summary["signal_kind"] == "warning" else "#34d399"
        self.signal_card.set_value(summary["signal"], signal_color)
        self.signal_card.value.setStyleSheet(f"color:{signal_color};font-size:15px;font-weight:700;")

    def _show_action_stories(self, turn_data):
        for card, story in zip(self.action_cards, action_stories(turn_data)):
            card.set_story(story)

    def _story_selected(self, story):
        target = f" → {story['target']}" if story.get("target") else ""
        self.show_detail(story.get("detail", {}), f"{story['actor']}: {story['verb']}{target}")

    def show_detail(self, detail, title=None):
        title = title or getattr(detail, "label", "Node details").split("\n")[0]
        if hasattr(detail, "detail"):
            detail = detail.detail
        self.inspector_title.setText(title)
        sections = inspector_sections(detail)
        for name, tree in self.inspector_trees.items():
            tree.clear()
            for key, value in sections[name].items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                tree.addTopLevelItem(QTreeWidgetItem([key.replace("_", " ").title(), str(value)]))
            tree.resizeColumnToContents(0)
        self.raw_detail.setPlainText(json.dumps(sections["Raw"], indent=2, ensure_ascii=False, default=str))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--replay", help="Battle-level audit JSONL file")
    source.add_argument("--live", help="Append-only live event JSONL file")
    parser.add_argument("--refresh-ms", type=int, default=500)
    return parser.parse_args(argv)


def main():
    args = parse_args()
    replay = args.replay
    if not args.live and not replay and os.path.exists("logs/doubles_decision_audit.jsonl"):
        replay = "logs/doubles_decision_audit.jsonl"
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pokemon Showdown AI Decision Dashboard")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    try:
        window = DecisionDashboard(replay=replay, live=args.live, refresh_ms=args.refresh_ms)
        window.show()
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "Decision Dashboard", f"Unable to open dashboard:\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
