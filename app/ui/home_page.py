"""홈 화면 — 폴더별 세션 정리 + 새 세션 시작 + 검색."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..store.db import SessionStore
from .dialogs import FramelessDialog
from .icons import FOLDER_COLORS, make_folder_icon, make_note_icon

_FOLDER_EMOJIS = [
    "", "\U0001F4D8", "\U0001F4DA", "\U0001F4BB", "\U0001F9EA", "\U0001F4D0",
    "\U0001F5FA", "\U0001F3A8", "\U0001F3B5", "\U0001F52C", "\U0001F4C8",
    "\U0001F30D", "\U0001F4A1", "\U0001F5C2", "⚙", "\U0001F4DD",
    "\U0001F520", "\U0001F9E0", "❤", "\U0001F525", "⭐", "\U0001F4CC",
]


def _friendly_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{dt.month}월 {dt.day}일 {dt:%H:%M}"


class _FolderDialog(FramelessDialog):
    """폴더 만들기/편집 — 이름·색·이모지."""

    def __init__(
        self, parent=None,
        name: str = "", color: str | None = None, emoji: str = "",
        title: str = "새 폴더",
    ) -> None:
        super().__init__(title, parent)
        self.setFixedWidth(360)
        layout = self.body
        form = QFormLayout()

        self._name = QLineEdit(name)
        self._name.setPlaceholderText("예: 운영체제")
        form.addRow("이름", self._name)

        # 이모지: 클릭하면 아래 그리드가 펼쳐진다
        self._emoji_value = emoji
        self._emoji_btn = QPushButton(
            f"{emoji}  선택됨" if emoji else "이모지 선택 (선택)"
        )
        self._emoji_btn.setProperty("cssClass", "pageTab")
        self._emoji_btn.setCursor(Qt.PointingHandCursor)
        self._emoji_btn.clicked.connect(self._toggle_emoji_grid)
        form.addRow("이모지", self._emoji_btn)

        self._emoji_grid = QWidget()
        grid = QGridLayout(self._emoji_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        for i, emoji in enumerate(_FOLDER_EMOJIS):
            cell = QPushButton(emoji or "∅")
            cell.setFixedSize(30, 30)
            cell.setCursor(Qt.PointingHandCursor)
            cell.setProperty("cssClass", "ghost")
            cell.setToolTip("없음" if not emoji else emoji)
            cell.clicked.connect(lambda _, e=emoji: self._pick_emoji(e))
            grid.addWidget(cell, i // 8, i % 8)
        self._emoji_grid.setVisible(False)

        color_row = QHBoxLayout()
        self._color_group = QButtonGroup(self)
        for i, swatch_color in enumerate(FOLDER_COLORS):
            swatch = QPushButton()
            swatch.setCheckable(True)
            swatch.setFixedSize(26, 26)
            swatch.setCursor(Qt.PointingHandCursor)
            swatch.setStyleSheet(
                f"background: {swatch_color};"
                " border-radius: 13px; border: 2px solid transparent;"
            )
            swatch.setProperty("folderColor", swatch_color)
            self._color_group.addButton(swatch, i)
            color_row.addWidget(swatch)
        color_row.addStretch()
        start = FOLDER_COLORS.index(color) if color in FOLDER_COLORS else 5  # 기본: 파랑
        self._color_group.button(start).setChecked(True)
        form.addRow("색", color_row)

        layout.addLayout(form)
        layout.addWidget(self._emoji_grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_emoji_grid(self) -> None:
        self._emoji_grid.setVisible(not self._emoji_grid.isVisible())
        self.adjustSize()

    def _pick_emoji(self, emoji: str) -> None:
        self._emoji_value = emoji
        self._emoji_btn.setText(f"{emoji}  선택됨" if emoji else "이모지 없음")
        self._emoji_grid.setVisible(False)
        self.adjustSize()

    def values(self) -> tuple[str, str, str]:
        color = self._color_group.checkedButton().property("folderColor")
        return self._name.text().strip(), color, self._emoji_value


_TYPE, _ID = Qt.UserRole, Qt.UserRole + 1  # 아이템 역할: 종류·id


class HomePage(QWidget):
    new_session_requested = Signal(str)   # kind: "note" | "pdf"
    session_opened = Signal(int)          # session_id

    def __init__(self, store: SessionStore) -> None:
        super().__init__()
        self.setObjectName("homePage")
        self._store = store
        self._current_folder: int | None = None  # None = 최상위(폴더+낱개 노트)
        self._in_trash = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)

        # 헤더: 제목/뒤로 + 검색 + [노트][PDF 노트][+ 폴더]
        header = QHBoxLayout()
        from .icons import make_ui_icon

        self._back_btn = QPushButton()
        self._back_btn.setIcon(make_ui_icon("back", 18))
        self._back_btn.setIconSize(QSize(20, 20))
        self._back_btn.setProperty("cssClass", "ghost")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setToolTip("상위로")
        self._back_btn.clicked.connect(lambda: self._enter_folder(None))
        self._back_btn.hide()
        header.addWidget(self._back_btn)
        self._title = QLabel("문서")
        self._title.setProperty("cssClass", "pageTitle")
        header.addWidget(self._title)
        header.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("\U0001F50D  검색")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(200)
        self._search.textChanged.connect(self._refresh_items)
        header.addWidget(self._search)

        note_btn = QPushButton("\U0001F4DD 노트")
        note_btn.setProperty("cssClass", "primary")
        note_btn.setCursor(Qt.PointingHandCursor)
        note_btn.setToolTip("노션형 노트 — 자막과 함께 자유롭게 필기")
        note_btn.clicked.connect(lambda: self.new_session_requested.emit("note"))
        pdf_btn = QPushButton("\U0001F4D5 PDF 노트")
        pdf_btn.setProperty("cssClass", "primary")
        pdf_btn.setCursor(Qt.PointingHandCursor)
        pdf_btn.setToolTip("PDF를 열어 위에 필기 — 페이지마다 노트가 따라옵니다")
        pdf_btn.clicked.connect(lambda: self.new_session_requested.emit("pdf"))
        folder_btn = QPushButton(" 폴더")
        folder_btn.setIcon(make_ui_icon("plus", 14))
        folder_btn.setProperty("cssClass", "ghost")
        folder_btn.setCursor(Qt.PointingHandCursor)
        folder_btn.clicked.connect(self._new_folder)
        header.addWidget(note_btn)
        header.addWidget(pdf_btn)
        header.addWidget(folder_btn)
        layout.addLayout(header)

        # 아이콘 그리드
        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.IconMode)
        self._grid.setIconSize(QSize(96, 96))
        self._grid.setGridSize(QSize(140, 150))
        self._grid.setSpacing(10)
        self._grid.setMovement(QListWidget.Static)
        self._grid.setResizeMode(QListWidget.Adjust)
        self._grid.setWordWrap(True)
        self._grid.setUniformItemSizes(True)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._grid.itemDoubleClicked.connect(self._on_double_click)
        self._grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._grid, stretch=1)

        self._empty = QLabel("아직 문서가 없습니다. 위에서 [노트] 또는 [PDF 노트]로 시작하세요.")
        self._empty.setProperty("cssClass", "subtitle")
        self._empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty)

        # 우측 하단: 휴지통
        bottom = QHBoxLayout()
        bottom.addStretch()
        self._empty_trash_btn = QPushButton("비우기")
        self._empty_trash_btn.setProperty("cssClass", "ghost")
        self._empty_trash_btn.setCursor(Qt.PointingHandCursor)
        self._empty_trash_btn.clicked.connect(self._empty_trash)
        self._empty_trash_btn.hide()
        bottom.addWidget(self._empty_trash_btn)
        self._trash_btn = QPushButton()
        self._trash_btn.setIcon(make_ui_icon("trash", 26))
        self._trash_btn.setIconSize(QSize(28, 28))
        self._trash_btn.setProperty("cssClass", "ghost")
        self._trash_btn.setCursor(Qt.PointingHandCursor)
        self._trash_btn.setToolTip("휴지통")
        self._trash_btn.clicked.connect(self._toggle_trash)
        bottom.addWidget(self._trash_btn)
        layout.addLayout(bottom)

    # --- 갱신 ---

    def refresh(self) -> None:
        self._refresh_items()

    def _refresh_items(self) -> None:
        self._grid.clear()
        search = self._search.text().strip()

        if self._in_trash:
            self._title.setText("휴지통")
            self._back_btn.show()
            sessions = self._store.trashed_sessions()
            if search:
                sessions = [s for s in sessions if search.lower() in s[1].lower()]
            self._add_session_items(sessions)
            self._empty_trash_btn.setVisible(self._grid.count() > 0)
            self._empty.setText("휴지통이 비어 있습니다.")
            self._empty.setVisible(self._grid.count() == 0)
            return
        self._empty_trash_btn.hide()
        self._empty.setText("아직 문서가 없습니다. 위에서 [노트] 또는 [PDF 노트]로 시작하세요.")

        # 유효하지 않은 폴더면 최상위로
        folders = self._store.folders()
        if self._current_folder is not None and self._current_folder not in {
            f[0] for f in folders
        }:
            self._current_folder = None

        if self._current_folder is None and not search:
            # 최상위: 폴더들 먼저
            self._title.setText("문서")
            self._back_btn.hide()
            for folder_id, name, color, emoji in folders:
                item = QListWidgetItem(make_folder_icon(color, emoji, 96), name)
                item.setData(_TYPE, "folder")
                item.setData(_ID, folder_id)
                item.setToolTip(name)
                self._grid.addItem(item)
            sessions = self._store.list_sessions(only_folderless=True)  # 낱개 노트
        elif self._current_folder is not None:
            folder = next((f for f in folders if f[0] == self._current_folder), None)
            self._title.setText(folder[1] if folder else "문서")
            self._back_btn.show()
            sessions = self._store.list_sessions(search, self._current_folder)
        else:  # 검색: 전체에서
            self._title.setText(f"'{search}' 검색")
            self._back_btn.show()
            sessions = self._store.list_sessions(search, None)

        self._add_session_items(sessions)
        self._empty.setVisible(self._grid.count() == 0)

    def _add_session_items(self, sessions: list[tuple]) -> None:
        for session_id, title, started_at, seg_count in sessions:
            is_pdf = self._store.get_session_pdf(session_id) is not None
            item = QListWidgetItem(make_note_icon(is_pdf, 96), title)
            item.setData(_TYPE, "session")
            item.setData(_ID, session_id)
            item.setToolTip(f"{title}\n{_friendly_date(started_at)} · 자막 {seg_count}개")
            self._grid.addItem(item)

    # --- 탐색 ---

    def _enter_folder(self, folder_id: int | None) -> None:
        self._current_folder = folder_id
        self._in_trash = False
        self._search.clear()
        self._refresh_items()

    def nav_state(self) -> tuple:
        """마우스 뒤로/앞으로용 현재 위치: ("trash"|"folder", 값)."""
        if self._in_trash:
            return ("trash", None)
        return ("folder", self._current_folder)  # None = 최상위

    def go_up(self) -> bool:
        """휴지통/폴더에서 최상위로. 이미 최상위면 False."""
        if self._in_trash or self._current_folder is not None:
            self._enter_folder(None)
            return True
        return False

    def open_view(self, state: tuple) -> None:
        kind, value = state
        if kind == "trash":
            if not self._in_trash:
                self._toggle_trash()
        else:
            self._enter_folder(value)

    def _toggle_trash(self) -> None:
        self._in_trash = not self._in_trash
        self._current_folder = None
        self._search.clear()
        self._refresh_items()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if self._in_trash:
            return
        if item.data(_TYPE) == "folder":
            self._enter_folder(item.data(_ID))
        else:
            self.session_opened.emit(item.data(_ID))

    # --- 폴더/세션 동작 ---

    def _new_folder(self) -> None:
        dialog = _FolderDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name, color, emoji = dialog.values()
        if name:
            self._store.create_folder(name, color, emoji)
            self.refresh()

    def _context_menu(self, pos) -> None:
        item = self._grid.itemAt(pos)
        if item is None:
            return
        if self._in_trash:
            self._trash_menu(item.data(_ID), self._grid.mapToGlobal(pos))
        elif item.data(_TYPE) == "folder":
            self._folder_menu(item.data(_ID), self._grid.mapToGlobal(pos))
        else:
            self._session_menu(item.data(_ID), self._grid.mapToGlobal(pos))

    def _folder_menu(self, folder_id: int, global_pos) -> None:
        menu = QMenu(self)
        open_action = menu.addAction("열기")
        edit_action = menu.addAction("이름·모양 바꾸기…")
        delete_action = menu.addAction("폴더 삭제 (안의 노트는 유지)")
        chosen = menu.exec(global_pos)
        if chosen == open_action:
            self._enter_folder(folder_id)
        elif chosen == edit_action:
            self._edit_folder(folder_id)
        elif chosen == delete_action:
            self._store.delete_folder(folder_id)
            self.refresh()

    def _edit_folder(self, folder_id: int) -> None:
        row = next(
            (f for f in self._store.folders() if f[0] == folder_id), None
        )
        if row is None:
            return
        _, name, color, emoji = row
        dialog = _FolderDialog(
            self, name=name, color=color, emoji=emoji, title="폴더 편집"
        )
        if dialog.exec() != QDialog.Accepted:
            return
        new_name, new_color, new_emoji = dialog.values()
        if new_name:
            self._store.update_folder(folder_id, new_name, new_color, new_emoji)
            self.refresh()

    def _session_menu(self, session_id: int, global_pos) -> None:
        menu = QMenu(self)
        move_menu = menu.addMenu("폴더로 이동")
        none_action = move_menu.addAction("(폴더 없음)")
        folder_actions = {}
        for folder_id, name, color, emoji in self._store.folders():
            action = move_menu.addAction(make_folder_icon(color, emoji), name)
            folder_actions[action] = folder_id
        menu.addSeparator()
        delete_action = menu.addAction("휴지통으로 이동")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == none_action:
            self._store.set_session_folder(session_id, None)
        elif chosen in folder_actions:
            self._store.set_session_folder(session_id, folder_actions[chosen])
        elif chosen == delete_action:
            self._store.trash_session(session_id)
        self._refresh_items()

    # --- 휴지통 ---

    def _trash_menu(self, session_id: int, global_pos) -> None:
        menu = QMenu(self)
        restore_action = menu.addAction("복원")
        purge_action = menu.addAction("영구 삭제…")
        chosen = menu.exec(global_pos)
        if chosen == restore_action:
            self._store.restore_session(session_id)
        elif chosen == purge_action:
            title = (self._store.get_session(session_id) or (0, session_id))[1]
            answer = QMessageBox.question(
                self,
                "영구 삭제",
                f"'{title}'을(를) 영구 삭제할까요?\n"
                "노트·자막·녹음·PDF 필기가 모두 지워지며 되돌릴 수 없습니다.",
            )
            if answer == QMessageBox.Yes:
                self._purge_session(session_id)
        self._refresh_items()

    def _empty_trash(self) -> None:
        trashed = self._store.trashed_sessions()
        if not trashed:
            return
        answer = QMessageBox.question(
            self,
            "휴지통 비우기",
            f"휴지통의 {len(trashed)}개 세션을 영구 삭제할까요?\n되돌릴 수 없습니다.",
        )
        if answer != QMessageBox.Yes:
            return
        for session_id, *_ in trashed:
            self._purge_session(session_id)
        self._refresh_items()

    def _purge_session(self, session_id: int) -> None:
        self._store.delete_session(session_id)
        # 딸린 파일(녹음 트랙, PDF)도 정리 — 잠긴 파일이 있어도 계속 진행
        from ..paths import data_root

        data_dir = data_root()
        targets = list((data_dir / "audio").glob(f"{session_id}_*.ogg"))
        targets.append(data_dir / "pdf" / f"{session_id}.pdf")
        for path in targets:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        # 지운 노트가 참조하던 이미지도 함께 정리
        self._store.cleanup_orphan_attachments(data_dir / "attachments")

    # --- 내부 ---

    def _on_open(self, item: QListWidgetItem) -> None:
        self.session_opened.emit(item.data(Qt.UserRole))
