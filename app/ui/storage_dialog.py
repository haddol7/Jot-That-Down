"""용량 관리 — 녹음·첨부·PDF·DB·모델 캐시가 차지하는 공간을 보여주고 정리한다."""
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from ..paths import data_root
from .dialogs import FramelessDialog


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _fmt(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.2f} GB"
    if size >= 1024 ** 2:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024:.0f} KB"


def _model_cache_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".cache" / "huggingface" / "hub"


class StorageDialog(FramelessDialog):
    def __init__(self, settings, parent=None) -> None:
        super().__init__("용량 관리", parent)
        self._settings = settings
        self.setFixedWidth(460)
        self._build()

    def _build(self) -> None:
        layout = self.body
        form = QFormLayout()
        form.setVerticalSpacing(8)

        data = data_root()
        rows = [
            ("녹음", _dir_size(data / "audio")),
            ("첨부 이미지", _dir_size(data / "attachments")),
            ("PDF", _dir_size(data / "pdf")),
            ("노트 DB", _dir_size(data / "jotthatdown.db")),
        ]
        total = sum(size for _, size in rows)
        for label, size in rows:
            form.addRow(label, QLabel(_fmt(size)))
        total_label = QLabel(_fmt(total))
        total_label.setStyleSheet("font-weight: 700;")
        form.addRow("데이터 합계", total_label)

        open_btn = QPushButton("데이터 폴더 열기")
        open_btn.clicked.connect(lambda: os.startfile(str(data)))
        form.addRow("", open_btn)
        layout.addLayout(form)

        # 모델 캐시 (faster-whisper) — 안 쓰는 모델은 지워도 필요 시 재다운로드
        cache_form = QFormLayout()
        cache_form.setVerticalSpacing(8)
        cache = _model_cache_dir()
        models = sorted(cache.glob("models--*whisper*")) if cache.is_dir() else []
        if models:
            for model_dir in models:
                name = model_dir.name.split("--")[-1]
                row = QHBoxLayout()
                row.addWidget(QLabel(_fmt(_dir_size(model_dir))))
                delete_btn = QPushButton("삭제")
                delete_btn.setProperty("cssClass", "danger")
                delete_btn.setCursor(Qt.PointingHandCursor)
                delete_btn.clicked.connect(
                    lambda _, d=model_dir: self._delete_model(d)
                )
                row.addWidget(delete_btn)
                row.addStretch()
                cache_form.addRow(name, row)
        else:
            cache_form.addRow("모델 캐시", QLabel("없음"))
        header = QLabel("인식 모델 캐시 — 지워도 다음 사용 시 다시 내려받습니다")
        header.setProperty("cssClass", "rowMeta")
        layout.addWidget(header)
        layout.addLayout(cache_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _: self.reject())
        layout.addWidget(buttons)

    def _delete_model(self, model_dir: Path) -> None:
        answer = QMessageBox.question(
            self, "모델 삭제",
            f"'{model_dir.name.split('--')[-1]}' 캐시를 삭제할까요?\n"
            "다음에 이 모델을 쓰면 자동으로 다시 내려받습니다.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(model_dir)
        except OSError as error:
            QMessageBox.critical(self, "삭제 실패", str(error))
            return
        # 목록 갱신 — 본문을 다시 그린다
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._build()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
