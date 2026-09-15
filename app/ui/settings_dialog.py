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

        # 실시간 자막(오버레이) — 최소화/패널 접힘 시 뜨는 자막 창
        self._overlay_font = QSpinBox()
        self._overlay_font.setRange(14, 32)
        self._overlay_font.setSuffix(" px")
        self._overlay_font.setValue(settings.overlay_font_px)
        form.addRow("자막 글자 크기", self._overlay_font)

        self._overlay_lines = QSpinBox()
        self._overlay_lines.setRange(1, 4)
        self._overlay_lines.setSuffix(" 줄")
        self._overlay_lines.setValue(settings.overlay_lines)
        form.addRow("자막 줄 수", self._overlay_lines)

        self._overlay_ttl = QSpinBox()
        self._overlay_ttl.setRange(3, 60)
        self._overlay_ttl.setSuffix(" 초")
        self._overlay_ttl.setValue(settings.overlay_ttl_sec)
        self._overlay_ttl.setToolTip("자막이 이 시간 동안 새 말이 없으면 사라집니다")
        form.addRow("자막 표시 시간", self._overlay_ttl)

        if self._corrections_path is not None:
            corrections_btn = QPushButton("교정 사전 편집…")
            corrections_btn.setToolTip("자주 틀리게 인식되는 표현을 바로잡는 규칙")
            corrections_btn.clicked.connect(self._open_corrections)
            form.addRow("인식 교정", corrections_btn)

        # 동기화 — 노트는 항상 이 컴퓨터에 저장된다. 드라이브는 백업·공유용 사본.
        self._sync_btn = QPushButton(self._sync_label())
        self._sync_btn.setToolTip(
            "노트·녹음은 언제나 이 컴퓨터에 저장됩니다.\n"
            "연결하면 드라이브에 사본을 두어 백업하고 다른 PC와 공유합니다.\n"
            "드라이브가 꺼져 있어도 앱은 평소대로 동작합니다."
        )
        self._sync_btn.clicked.connect(self._toggle_sync)
        form.addRow("구글 드라이브", self._sync_btn)

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

    def _sync_label(self) -> str:
        if self._settings.sync_dir:
            return f"연결됨 — {self._settings.sync_dir}  (해제…)"
        return "구글 드라이브에 연결…"

    def _toggle_sync(self) -> None:
        if self._settings.sync_dir:
            self._disconnect_sync()
        else:
            self._connect_gdrive()

    def _disconnect_sync(self) -> None:
        """동기화만 끈다 — 데이터는 이 컴퓨터에 그대로 있다."""
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, "동기화 해제",
            "구글 드라이브 동기화를 끌까요?\n\n"
            "노트·녹음은 이 컴퓨터에 그대로 남습니다.\n"
            "드라이브에 올려둔 사본도 지우지 않습니다.",
        )
        if answer != QMessageBox.Yes:
            return
        self._settings.sync_dir = ""
        self._settings.sync_revision = 0
        self._settings.sync_pushed_stamp = 0.0
        self._sync_btn.setText(self._sync_label())
        self._on_apply()

    def _connect_gdrive(self) -> None:
        """드라이브 데스크톱을 찾아 '내 드라이브/JotThatDown'을 사본 폴더로 삼는다."""
        from PySide6.QtWidgets import QMessageBox

        from ..sync import google_drive_target

        target = google_drive_target()
        if target is None:
            answer = QMessageBox.question(
                self, "구글 드라이브 설치",
                "구글 드라이브 앱이 아직 없습니다. 바로 설치할까요?\n\n"
                "진행 순서:\n"
                "  1. [예]를 누르면 공식 설치 파일을 받아 실행합니다\n"
                "  2. Windows 권한 창(파란 방패)이 뜨면 [예]로 허용\n"
                "  3. 설치가 끝나면 브라우저에서 구글 계정으로 로그인\n"
                "  4. 파일 탐색기에 'G:\\내 드라이브'가 생겼는지 확인\n"
                "  5. 이 버튼을 다시 누르면 연결이 끝납니다\n\n"
                "노트는 이 컴퓨터에 저장되고, 드라이브에는 사본이 올라갑니다.",
            )
            if answer == QMessageBox.Yes:
                self._install_gdrive()
            return
        try:
            root = target.root()
        except OSError as error:
            QMessageBox.critical(self, "연결 실패", f"폴더를 만들 수 없습니다:\n{error}")
            return

        self._settings.sync_dir = str(root)
        # 저쪽에 이미 데이터가 있으면 개정 번호를 0으로 둬서 '받아올 게 있음'으로
        # 판단하게 한다 — 다음 동기화 때 서비스가 상태를 다시 계산한다.
        self._settings.sync_revision = 0
        self._settings.sync_pushed_stamp = 0.0
        self._sync_btn.setText(self._sync_label())
        self._on_apply()
        QMessageBox.information(
            self, "연결됨",
            f"드라이브 폴더에 사본을 둡니다:\n{root}\n\n"
            "노트는 계속 이 컴퓨터에 저장됩니다.\n"
            "홈 화면의 동기화 버튼으로 언제든 주고받을 수 있습니다.",
        )

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
            "설치 파일을 실행했습니다. 이어서:\n\n"
            "  1. Windows 권한 창이 뜨면 [예]로 허용\n"
            "  2. 설치 완료 후 구글 계정으로 로그인 (브라우저가 열립니다)\n"
            "  3. 작업 표시줄 트레이의 드라이브 아이콘이 동기화 완료가 되면\n"
            "  4. '구글 드라이브에 연결…' 버튼을 다시 눌러주세요",
        )

    def _open_storage(self) -> None:
        from .storage_dialog import StorageDialog

        StorageDialog(self._settings, self).exec()

    def _save(self) -> None:
        self._settings.theme = self._theme.currentData()
        self._settings.model_mode = self._model.currentData()
        self._settings.silence_sec = round(self._silence.value(), 1)
        self._settings.editor_font_px = self._font.value()
        self._settings.overlay_font_px = self._overlay_font.value()
        self._settings.overlay_lines = self._overlay_lines.value()
        self._settings.overlay_ttl_sec = self._overlay_ttl.value()
        self._on_apply()
        self.accept()
