"""동기화 조율 — 서비스(파일 작업)와 사용자(다이얼로그) 사이.

서비스는 Qt를 모르고, 이 클래스는 파일 복사를 모른다. 여기서 하는 일은
'언제 물어보고, 언제 조용히 넘어가는가'뿐이다.

드라이브가 꺼져 있으면 어떤 경로도 사용자를 막지 않는다 — 오프라인이 정상이다.
"""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from ..settings import AppSettings
from ..store.db import SessionStore
from ..sync import SyncAction, SyncService, SyncState, SyncStatus


class SettingsSyncState:
    """동기화 상태를 앱 설정에 얹어 저장한다 (SyncStateStore 구현)."""

    def __init__(self, settings: AppSettings, on_save) -> None:
        self._settings = settings
        self._on_save = on_save

    def load(self) -> SyncState:
        return SyncState(
            revision=self._settings.sync_revision,
            pushed_stamp=self._settings.sync_pushed_stamp,
        )

    def save(self, state: SyncState) -> None:
        self._settings.sync_revision = state.revision
        self._settings.sync_pushed_stamp = state.pushed_stamp
        self._on_save()


class SyncController(QObject):
    """홈의 동기화 버튼, 자동 push/pull, 충돌 문답."""

    status_changed = Signal(str)   # 상태 표시줄 문구
    reloaded = Signal()            # pull로 DB가 바뀜 → 화면을 다시 그려야 한다
    target_moved = Signal(str)     # 드라이브 문자가 바뀌어 폴더 경로가 달라짐

    def __init__(self, service: SyncService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._store: SessionStore | None = None
        self._pushing = threading.Lock()

    def _remember_target(self) -> None:
        """드라이브를 다시 찾아 경로가 바뀌었으면 설정에 적어 두게 알린다."""
        path = getattr(self._service.target, "path", None)
        if path is not None:
            self.target_moved.emit(str(path))

    def attach_store(self, store: SessionStore) -> None:
        """pull이 DB 파일을 갈아끼우려면 연결을 닫았다 열어야 한다."""
        self._store = store

    @property
    def enabled(self) -> bool:
        return self._service.target is not None

    # --- 앱 시작: 받아오기 ---

    def sync_on_start(self, parent=None) -> None:
        """드라이브에 새 게 있으면 받아온다. 꺼져 있으면 조용히 넘어간다.

        DB를 열기 전에 부르는 게 가장 안전하다 (파일을 통째로 갈아끼우므로).
        """
        status = self._service.status()
        if status.action is SyncAction.PULL:
            self._run_pull(parent, quiet=True)
        elif status.action is SyncAction.CONFLICT:
            self._resolve_conflict(parent, status)

    # --- 홈의 동기화 버튼 ---

    def sync_now(self, parent=None) -> None:
        status = self._service.status()
        if status.action is SyncAction.UNAVAILABLE:
            self._report_unavailable(parent)
            return
        if status.action is SyncAction.CONFLICT:
            self._resolve_conflict(parent, status)
            return
        if status.action is SyncAction.PULL:
            self._run_pull(parent)
            return
        if status.action is SyncAction.PUSH:
            self._run_push(parent)
            return
        self.status_changed.emit("이미 최신입니다")
        QMessageBox.information(
            parent, "동기화", "구글 드라이브와 이미 같은 상태입니다."
        )

    # --- 자동 저장(push) ---

    def push_async(self) -> None:
        """세션을 마쳤거나 홈으로 돌아올 때 — 조용히 백그라운드로 올린다."""
        if not self.enabled or self._pushing.locked():
            return
        if self._service.status().action is not SyncAction.PUSH:
            return  # 올릴 게 없거나, 충돌/오프라인 — 조용히 넘어간다

        def work() -> None:
            with self._pushing:
                try:
                    self._service.push()
                except OSError:
                    pass  # 드라이브가 도중에 꺼졌을 뿐 — 다음 기회에
            self.status_changed.emit("드라이브에 저장됨")

        threading.Thread(target=work, daemon=True, name="sync-push").start()

    def push_on_exit(self) -> None:
        """종료 직전 — 남은 변경을 올린다. 실패해도 종료를 막지 않는다."""
        if not self.enabled:
            return
        try:
            if self._service.status().action is SyncAction.PUSH:
                self._service.push()
        except OSError:
            pass

    # --- 내부 ---

    def _run_push(self, parent) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = self._service.push()
        except OSError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(parent, "동기화 실패", f"올리지 못했습니다:\n{error}")
            return
        QApplication.restoreOverrideCursor()
        self._remember_target()
        self.status_changed.emit("드라이브에 저장됨")
        QMessageBox.information(
            parent, "동기화", f"드라이브에 저장했습니다. (개정 {info.revision})"
        )

    def _run_pull(self, parent, quiet: bool = False) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        error: OSError | None = None
        info = None
        try:
            if self._store is not None:
                self._store.close()  # 파일을 갈아끼우는 동안 연결을 놓는다
            info = self._service.pull()
        except OSError as failure:  # FileNotFoundError 포함
            error = failure
        finally:
            if self._store is not None:
                self._store.reopen()  # 실패했어도 앱은 계속 돌아야 한다
            QApplication.restoreOverrideCursor()

        if error is not None:
            if not quiet:
                QMessageBox.warning(
                    parent, "동기화 실패", f"받아오지 못했습니다:\n{error}"
                )
            return

        self._remember_target()
        self.reloaded.emit()
        self.status_changed.emit("드라이브에서 받아옴")
        if not quiet:
            QMessageBox.information(
                parent, "동기화",
                f"드라이브의 데이터를 받아왔습니다.\n"
                f"({info.device or '다른 기기'}가 {info.when}에 저장)",
            )

    def _resolve_conflict(self, parent, status: SyncStatus) -> None:
        """양쪽 다 바뀜 — 어느 쪽을 쓸지는 사람이 정한다. 밀리는 쪽은 백업한다."""
        remote = status.remote
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("동기화 충돌")
        box.setText("이 기기와 드라이브 양쪽이 모두 바뀌었습니다.")
        box.setInformativeText(
            f"이 기기: {status.local_when}에 수정\n"
            f"드라이브: {remote.when}에 "
            f"{remote.device or '다른 기기'}가 저장\n\n"
            "어느 쪽을 쓸까요? 밀려나는 쪽은 백업 폴더에 보관합니다."
        )
        keep_local = box.addButton("이 기기 것으로 덮어쓰기", QMessageBox.AcceptRole)
        take_remote = box.addButton("드라이브 것 받아오기", QMessageBox.DestructiveRole)
        box.addButton("나중에", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() is take_remote:
            self._run_pull(parent)  # pull이 알아서 로컬을 백업한다
        elif box.clickedButton() is keep_local:
            self._service.adopt_remote_revision()  # 저쪽 변경을 봤다고 표시
            self._run_push(parent)

    def _report_unavailable(self, parent) -> None:
        if not self.enabled:
            QMessageBox.information(
                parent, "동기화 꺼짐",
                "구글 드라이브가 연결돼 있지 않습니다.\n"
                "설정 → '구글 드라이브에 연결…'에서 켤 수 있습니다.\n\n"
                "연결하지 않아도 앱은 이 컴퓨터에 정상적으로 저장합니다.",
            )
            return
        QMessageBox.information(
            parent, "드라이브 꺼짐",
            "구글 드라이브 앱이 꺼져 있거나 로그아웃 상태입니다.\n"
            "노트는 이 컴퓨터에 그대로 저장되고 있으니, 드라이브를 켠 뒤\n"
            "다시 동기화를 누르면 그때 올라갑니다.",
        )
