"""설정 다이얼로그 — 테마·모델·발화 대기·글꼴 크기.

테마와 글꼴은 저장 즉시 적용, 모델·발화 대기는 다음 세션부터.
"""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
)

from ..settings import AppSettings
from .dialogs import FramelessDialog

_THEMES = [("라이트", "light"), ("다크", "dark")]
_MODELS = [
    ("자동 (하드웨어에 맞춰 선택 · 권장)", "auto"),
    ("최고 품질 — large-v3 (VRAM 여유 필요)", "large-v3"),
    ("균형 — large-v3-turbo (노트북 권장)", "large-v3-turbo"),
    ("가벼움 — small", "small"),
]


class SettingsDialog(FramelessDialog):
    def __init__(
        self,
        settings: AppSettings,
        on_apply: Callable[[], None],
        corrections_path=None,
        parent=None,
    ) -> None:
        super().__init__("설정", parent)
        self._settings = settings
        self._on_apply = on_apply
        self._corrections_path = corrections_path
        self.setFixedWidth(440)

        layout = self.body
        form = QFormLayout()
        form.setVerticalSpacing(12)

        self._theme = QComboBox()
        for label, value in _THEMES:
            self._theme.addItem(label, value)
        self._theme.setCurrentIndex(
            next(i for i, (_, v) in enumerate(_THEMES) if v == settings.theme)
        )
        form.addRow("테마", self._theme)

        self._model = QComboBox()
        for label, value in _MODELS:
            self._model.addItem(label, value)
        self._model.setCurrentIndex(
            next(
                (i for i, (_, v) in enumerate(_MODELS) if v == settings.model_mode), 0
            )
        )
        form.addRow("인식 모델", self._model)

        self._silence = QDoubleSpinBox()
        self._silence.setRange(0.3, 2.0)
        self._silence.setSingleStep(0.1)
        self._silence.setSuffix(" 초")
        self._silence.setValue(settings.silence_sec)
        self._silence.setToolTip("짧을수록 자막이 빨리 확정되지만 문장이 잘게 쪼개집니다")
        form.addRow("발화 종료 대기", self._silence)

        self._font = QSpinBox()
        self._font.setRange(12, 24)
        self._font.setSuffix(" px")
        self._font.setValue(settings.editor_font_px)
        form.addRow("에디터 글꼴 크기", self._font)

        if self._corrections_path is not None:
            corrections_btn = QPushButton("교정 사전 편집…")
            corrections_btn.setToolTip("자주 틀리게 인식되는 표현을 바로잡는 규칙")
            corrections_btn.clicked.connect(self._open_corrections)
            form.addRow("인식 교정", corrections_btn)

        # 데이터 폴더 — 구글 드라이브/OneDrive 폴더로 지정하면 기기 간 동기화
        self._data_dir_btn = QPushButton(self._data_dir_label())
        self._data_dir_btn.setToolTip(
            "노트·녹음이 저장되는 폴더입니다. 클라우드 동기화 폴더로 옮기면\n"
            "다른 기기와 자동으로 공유됩니다 (한 번에 한 기기에서만 사용)."
        )
        self._data_dir_btn.clicked.connect(self._change_data_dir)
        form.addRow("데이터 폴더", self._data_dir_btn)

        gdrive_btn = QPushButton("구글 드라이브에 연결…")
        gdrive_btn.setToolTip(
            "드라이브의 '내 드라이브/JotThatDown' 폴더를 만들어 데이터를 옮깁니다.\n"
            "구글 드라이브 데스크톱 앱에 로그인돼 있어야 합니다."
        )
        gdrive_btn.clicked.connect(self._connect_gdrive)
        form.addRow("", gdrive_btn)

        storage_btn = QPushButton("용량 관리…")
        storage_btn.clicked.connect(self._open_storage)
        form.addRow("저장 공간", storage_btn)

        layout.addLayout(form)

        note = QLabel("모델·발화 대기는 다음 세션 시작부터 적용됩니다.")
        note.setProperty("cssClass", "rowMeta")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _open_corrections(self) -> None:
        from .corrections_dialog import CorrectionsDialog

        CorrectionsDialog(self._corrections_path, self).exec()

    def _data_dir_label(self) -> str:
        return self._settings.data_dir or "기본 위치 (변경…)"

    def _change_data_dir(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from ..paths import data_root
        from ..store.data_move import migrate_data_dir

        picked = QFileDialog.getExistingDirectory(
            self, "데이터 폴더 선택 (예: 구글 드라이브 안)", self._settings.data_dir
        )
        if picked:
            self._apply_data_dir(Path(picked))

    def _connect_gdrive(self) -> None:
        """드라이브 데스크톱을 찾아 '내 드라이브/JotThatDown'으로 연결한다."""
        from PySide6.QtWidgets import QMessageBox

        from ..gdrive import find_google_drive_root

        root = find_google_drive_root()
        if root is None:
            answer = QMessageBox.question(
                self, "구글 드라이브 설치",
                "구글 드라이브 앱이 아직 없습니다. 바로 설치할까요?\n"
                "설치 후 구글 계정으로 로그인하고 이 버튼을 다시 누르면\n"
                "연결이 끝납니다.",
            )
            if answer == QMessageBox.Yes:
                self._install_gdrive()
            return
        target = root / "JotThatDown"
        try:
            target.mkdir(exist_ok=True)
        except OSError as error:
            QMessageBox.critical(self, "연결 실패", f"폴더를 만들 수 없습니다:\n{error}")
            return
        self._apply_data_dir(target)

    def _install_gdrive(self) -> None:
        """공식 설치 파일을 내려받아 실행한다 — 사용자는 설치·로그인만 하면 된다."""
        import os
        import tempfile
        import urllib.request

        from PySide6.QtWidgets import QApplication, QMessageBox

        url = "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe"
        target = Path(tempfile.gettempdir()) / "GoogleDriveSetup.exe"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            urllib.request.urlretrieve(url, str(target))
        except OSError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, "다운로드 실패",
                f"설치 파일을 받지 못했습니다:\n{error}\n\n"
                "https://www.google.com/drive/download/ 에서 직접 설치해주세요.",
            )
            return
        QApplication.restoreOverrideCursor()
        os.startfile(str(target))
        QMessageBox.information(
            self, "설치 진행",
            "설치가 시작됐습니다. 설치를 마치고 구글 계정으로 로그인한 뒤,\n"
            "'구글 드라이브에 연결…' 버튼을 다시 눌러주세요.",
        )

    def _apply_data_dir(self, new_dir) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..paths import data_root
        from ..store.data_move import migrate_data_dir

        old_dir = data_root()
        if new_dir == old_dir:
            return
        if (new_dir / "jotthatdown.db").exists():
            # 이미 데이터가 있는 폴더 (다른 기기가 올려둔 것) — 덮어쓰면 안 된다
            answer = QMessageBox.question(
                self, "기존 데이터 발견",
                "선택한 폴더에 이미 JotThatDown 데이터가 있습니다.\n"
                "그 데이터를 그대로 사용할까요? (이 기기의 데이터는 복사하지 않음)",
            )
            if answer != QMessageBox.Yes:
                return
        else:
            try:
                migrate_data_dir(old_dir, new_dir)
            except OSError as error:
                QMessageBox.critical(self, "이동 실패", f"복사 중 오류:\n{error}")
                return
        self._settings.data_dir = str(new_dir)
        self._data_dir_btn.setText(self._data_dir_label())
        self._on_apply()  # 설정 즉시 저장
        QMessageBox.information(
            self, "데이터 폴더 변경",
            "앱을 다시 시작하면 새 폴더를 사용합니다.\n"
            f"(기존 폴더는 그대로 남아 있습니다: {old_dir})",
        )

    def _open_storage(self) -> None:
        from .storage_dialog import StorageDialog

        StorageDialog(self._settings, self).exec()

    def _save(self) -> None:
        self._settings.theme = self._theme.currentData()
        self._settings.model_mode = self._model.currentData()
        self._settings.silence_sec = round(self._silence.value(), 1)
        self._settings.editor_font_px = self._font.value()
        self._on_apply()
        self.accept()
