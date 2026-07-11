"""교정 사전 편집 다이얼로그 — corrections.txt를 표로 편집 (M6).

저장하면 파일이 갱신되고, 실행 중인 파이프라인은 mtime 감지로
다음 자막부터 자동 반영한다 (재시작 불필요).
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ..text.corrections import parse_rules
from .dialogs import FramelessDialog


class CorrectionsDialog(FramelessDialog):
    def __init__(self, path: Path, parent=None, prefill: str = "") -> None:
        super().__init__("교정 사전 — 잘못 인식되는 단어 바로잡기", parent)
        self._path = path
        self.resize(560, 420)

        layout = self.body
        hint = QLabel(
            "자막에서 반복해서 틀리는 표현을 등록하세요. 저장 즉시 적용됩니다.\n"
            "예)  노선 앱 → 노션 앱   /   SSD의 고유 아이디 → 에셋의 고유 아이디"
        )
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["잘못 인식된 표현", "올바른 표현"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 240)
        layout.addWidget(self._table)

        row_buttons = QHBoxLayout()
        add_btn = QPushButton("+ 규칙 추가")
        add_btn.clicked.connect(lambda: self._add_row("", ""))
        remove_btn = QPushButton("− 선택 삭제")
        remove_btn.clicked.connect(self._remove_selected)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()
        if prefill:
            # 자막에서 드래그해 넘어온 표현 — 오른쪽 칸에 바로 입력하도록
            self._add_row(prefill, "")
            row = self._table.rowCount() - 1
            self._table.setCurrentCell(row, 1)
            self._table.editItem(self._table.item(row, 1))

    def _load(self) -> None:
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError:
            return
        for wrong, right in sorted(parse_rules(content)):
            self._add_row(wrong, right)

    def _add_row(self, wrong: str, right: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(wrong))
        self._table.setItem(row, 1, QTableWidgetItem(right))

    def _remove_selected(self) -> None:
        for index in sorted(
            {i.row() for i in self._table.selectedIndexes()}, reverse=True
        ):
            self._table.removeRow(index)

    def _save(self) -> None:
        lines = [
            "# 인식 교정 사전 — 형식:  잘못 인식된 표현 -> 올바른 표현",
            "# 앱 실행 중에도 저장하면 다음 자막부터 즉시 반영됩니다.",
            "",
        ]
        for row in range(self._table.rowCount()):
            wrong = (self._table.item(row, 0) or QTableWidgetItem()).text().strip()
            right = (self._table.item(row, 1) or QTableWidgetItem()).text().strip()
            if wrong and right:
                lines.append(f"{wrong} -> {right}")
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.accept()
