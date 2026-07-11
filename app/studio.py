"""스튜디오 엔트리포인트 (M4~M6): 세션 관리 + 노트 + 자막 + 녹음/재생.

실행:  python -m app.studio
홈 화면에서 소스를 골라 새 세션을 시작하거나 지난 세션을 연다.
"""
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

# ctranslate2가 로드되기 전에 CUDA DLL 경로를 등록해야 하므로 가장 먼저 실행
from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

# QtWebEngine(노트 에디터)은 오프스크린 합성 때문에 서브픽셀 안티앨리어싱을
# 꺼서 작은 글씨가 픽셀져 보인다 — LCD 텍스트를 강제로 켠다.
# (QtWebEngine이 초기화되기 전, 즉 PySide6 임포트 전에 설정해야 한다)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-lcd-text")

from PySide6.QtWidgets import QApplication

from app import bootstrap
from app.audio.player import MixPlayer
from app.audio.recorder import SessionRecorder, audio_path
from app.core.clock import SessionClock
from app.core.models import AudioSource, TranscriptSegment
from app.settings import load_settings, save_settings
from app.sinks.console import ConsoleSink
from app.sinks.transforming import TransformingSink
from app.store.db import SessionStore
from app.stt.local_engine import (
    MicTranscriptionEngine,
    SystemTranscriptionEngine,
)
from app.stt.shared_whisper import SharedWhisper
from app.ui.qt_bridge import SegmentBridge
from app.ui.studio_window import StudioWindow
from app.ui.theme import build_qss

from app.paths import data_root

# 설정 파일은 항상 이 기본 위치 — 데이터(DB·녹음 등)는 data_root()가
# 가리키는 곳 (설정에서 클라우드 동기화 폴더로 바꿀 수 있다)
SETTINGS_DIR = bootstrap.PROJECT_ROOT / "data"

_ENGINE_FOR = {
    AudioSource.MIC: MicTranscriptionEngine,
    AudioSource.SYSTEM: SystemTranscriptionEngine,
}
_ICONS = {AudioSource.MIC: "\U0001F3A4", AudioSource.SYSTEM: "\U0001F50A"}


class LiveRuntime:
    """라이브 세션의 실행 자원(시계·엔진·녹음기) 묶음.

    소스는 세션 중 켜고 끌 수 있다: 처음 켤 때 엔진·트랙을 지연 생성하고,
    그 뒤로는 음소거/해제만 하므로 즉시 반응한다.
    """

    def __init__(
        self,
        sources: list[AudioSource],
        store: SessionStore,
        bridge: SegmentBridge,
        settings,
        session_id: int | None = None,
        offset_ms: int = 0,
        resume_audio: bool = False,
    ) -> None:
        if session_id is None:
            self.session_id = store.create_session(
                datetime.now().strftime("%Y-%m-%d %H:%M 세션")
            )
        else:
            self.session_id = session_id  # 지난 세션에 이어서 녹음
        self.clock = SessionClock(offset_ms)
        self._store = store
        self._bridge = bridge
        self._stopped = False
        self._lock = threading.Lock()

        # 세션 중 두 번째 소스가 켜질 수 있으므로 항상 2개 기준으로 모델 선택
        self._config, reason = bootstrap.resolve_config("both", settings)
        print(f"모델 선택: {reason}")

        self._sink = TransformingSink(
            bootstrap.build_transforms(), [ConsoleSink(), bridge]
        )
        self._shared = SharedWhisper(self._config)  # 소스들이 모델 하나 공유
        self._engines: dict[AudioSource, object] = {}
        self._recorder = SessionRecorder(
            data_root(), self.session_id, self.clock, resume=resume_audio
        )
        self.active: set[AudioSource] = set()
        self.loading = bool(sources)  # 모델 로딩 중 (녹음 경과 표시 억제)
        # 첫 소스가 켜진 시각 — 경과는 여기부터 센다 (소스 없이 시작하면 미정)
        self._rec_started_ms: int | None = None

        def start() -> None:
            for src in sources:
                self._enable(src)
            if sources:
                self._rec_started_ms = self.clock.now_ms()
            self.loading = False
            self._emit_status()

        threading.Thread(target=start, name="live-start", daemon=True).start()

    def set_source_active(self, source: AudioSource, active: bool) -> None:
        if self._stopped:
            return
        if active:
            # 첫 활성화는 모델 로딩(수십 초)일 수 있으므로 워커 스레드에서
            threading.Thread(
                target=lambda: (self._enable(source), self._emit_status()),
                name=f"enable-{source.value}",
                daemon=True,
            ).start()
        else:
            with self._lock:
                engine = self._engines.get(source)
                if engine is not None:
                    engine.set_active(False)
                self._recorder.set_active(source, False)
                self.active.discard(source)
            self._emit_status()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for engine in self._engines.values():
            engine.stop()
        self._shared.stop()  # 모델 언로드 + GPU 캐시 반환
        self._recorder.stop()
        self._store.end_session(self.session_id)

    def status(self) -> dict:
        """UI 폴링용: 로딩 여부·경과 시간·활성 소스·소스별 소리 감지."""
        heard = {}
        for source in (AudioSource.MIC, AudioSource.SYSTEM):
            engine = self._engines.get(source)
            heard[source] = bool(
                engine and source in self.active and engine.heard_recently()
            )
        elapsed = (
            0
            if self.loading or self._rec_started_ms is None
            else max(0, self.clock.now_ms() - self._rec_started_ms)
        )
        return {
            "loading": self.loading,
            "elapsed_ms": elapsed,
            "active": set(self.active),
            "heard": heard,
            "stopped": self._stopped,
            "audio_bytes": self._audio_bytes(),
        }

    def _audio_bytes(self) -> int:
        total = 0
        for source in (AudioSource.MIC, AudioSource.SYSTEM):
            path = audio_path(data_root(), self.session_id, source)
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    # --- 내부 ---

    def _enable(self, source: AudioSource) -> None:
        with self._lock:
            if self._stopped:
                return
            engine = self._engines.get(source)
            if engine is None:
                notice = bootstrap.model_download_notice(self._config.model)
                self._bridge.status_changed.emit(
                    notice
                    or f"{_ICONS[source]} 모델 로딩 중… ({self._config.model})"
                )
                engine = _ENGINE_FOR[source](self._config, self.clock, self._shared)
                engine.add_sink(self._sink)
                engine.start()
                self._engines[source] = engine
            else:
                engine.set_active(True)
            self._recorder.set_active(source, True)
            self.active.add(source)
            if self._rec_started_ms is None:
                self._rec_started_ms = self.clock.now_ms()

    def _emit_status(self) -> None:
        if self._stopped:
            return
        if not self.active:
            # 아직 아무것도 켠 적 없으면 조용히, 켰다 끈 상태면 일시정지 표시
            self._bridge.status_changed.emit("일시정지" if self._engines else "")
        else:
            icons = "+".join(_ICONS[s] for s in sorted(self.active, key=lambda s: s.value))
            self._bridge.status_changed.emit(f"듣는 중 · {icons} · 녹음 중")


def main() -> None:
    from app.paths import ensure_std_streams

    ensure_std_streams()  # windowed exe: sys.stdout이 None이라 먼저 보정

    qt_app = QApplication(sys.argv)
    from app.ui.fonts import load_fonts
    from PySide6.QtGui import QFont

    qt_app.setFont(QFont(load_fonts(), 10))  # 나눔스퀘어 전역 적용
    from PySide6.QtGui import QIcon

    from app.paths import resource_root

    qt_app.setWindowIcon(QIcon(str(resource_root() / "assets" / "app.ico")))
    settings = load_settings(SETTINGS_DIR)
    qt_app.setStyleSheet(build_qss(settings.theme))

    # 데이터 폴더 결정 (설정에서 클라우드 동기화 폴더를 지정했으면 그곳)
    from app.paths import set_data_root

    if settings.data_dir:
        custom = Path(settings.data_dir)
        if custom.is_dir():
            set_data_root(custom)
        else:
            settings.data_dir = ""  # 폴더가 사라졌으면 기본 위치로 복귀

    # 다른 기기에서 같은 데이터 폴더를 쓰고 있는지 (동기화 충돌 방지)
    import socket

    data_root().mkdir(parents=True, exist_ok=True)
    lock_path = data_root() / ".applock"
    me = socket.gethostname()
    try:
        other = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        other = ""
    if other and other != me:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.warning(
            None, "다른 기기에서 사용 중",
            f"데이터 폴더를 '{other}' 기기가 쓰고 있는 것 같습니다.\n"
            "동시에 열면 데이터가 깨질 수 있습니다. 그래도 열까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            raise SystemExit(0)
    try:
        lock_path.write_text(me, encoding="utf-8")
    except OSError:
        pass

    store = SessionStore(data_root() / "jotthatdown.db")
    store.cleanup_orphan_attachments(data_root() / "attachments")
    bridge = SegmentBridge()
    window = StudioWindow(store, bootstrap.corrections_path(), settings)
    runtime: list[LiveRuntime | None] = [None]  # 클로저에서 교체 가능하도록

    def on_settings_changed() -> None:
        save_settings(SETTINGS_DIR, settings)
        qt_app.setStyleSheet(build_qss(settings.theme))
        window.session_page.apply_theme()
        window.apply_window_theme()

    def session_audio_paths(session_id: int) -> list:
        return [audio_path(data_root(), session_id, s) for s in AudioSource]

    def stop_runtime() -> None:
        if runtime[0] is None:
            return
        stopped_sid = runtime[0].session_id
        runtime[0].stop()
        runtime[0] = None
        window.set_live_stopped()
        # 방금 정지한 세션을 계속 보고 있다면 바로 재생/이어녹음 가능하게
        if window.session_page.session_id == stopped_sid:
            window.set_playback(session_audio_paths(stopped_sid), offer_resume=True)

    def on_new_session(kind: str) -> None:
        # kind: "note"(노션형) | "pdf"(PDF 필기형). PDF는 먼저 파일을 고른다.
        pdf_path = None
        if kind == "pdf":
            from PySide6.QtWidgets import QFileDialog

            pdf_path, _ = QFileDialog.getOpenFileName(
                window, "필기할 PDF 열기", "", "PDF (*.pdf)"
            )
            if not pdf_path:
                return
        stop_runtime()
        # 소스는 꺼진 채 시작 — 토글을 켤 때 비로소 모델을 로딩한다 (시작이 즉시)
        runtime[0] = LiveRuntime([], store, bridge, settings)
        # 폴더 안에서 만들었으면 그 폴더 소속으로
        view_kind, folder_id = window.home.nav_state()
        if view_kind == "folder" and folder_id is not None:
            store.set_session_folder(runtime[0].session_id, folder_id)
        session = store.get_session(runtime[0].session_id)
        window.show_session(
            runtime[0].session_id, session[1], runtime[0].clock,
            active_sources=set(),
        )
        if pdf_path:
            window.session_page.import_pdf(pdf_path)

    def on_source_toggled(source: AudioSource, active: bool) -> None:
        if runtime[0] is not None:
            runtime[0].set_source_active(source, active)

    def on_archive_open(session_id: int) -> None:
        stop_runtime()
        session = store.get_session(session_id)
        if session:
            window.show_session(session_id, session[1], clock=None)
            window.set_playback(session_audio_paths(session_id), offer_resume=True)

    def on_resume() -> None:
        sid = window.session_page.session_id
        if sid is None or runtime[0] is not None:
            return
        existing = [p for p in session_audio_paths(sid) if p.exists()]
        offset = max(MixPlayer.total_ms(existing), store.max_time_ms(sid))
        sources = [
            s for s in AudioSource if audio_path(data_root(), sid, s).exists()
        ] or [AudioSource.SYSTEM]
        store.add_marker(sid, offset, "resume")  # 플레이바에 이어녹음 지점 표시용
        runtime[0] = LiveRuntime(
            sources, store, bridge, settings,
            session_id=sid, offset_ms=offset, resume_audio=True,
        )
        window.attach_live(runtime[0].clock, set(sources))

    bridge.segment_received.connect(window.on_segment)
    bridge.status_changed.connect(window.show_status)
    window.new_session_requested.connect(on_new_session)
    window.archive_open_requested.connect(on_archive_open)
    window.stop_requested.connect(stop_runtime)
    window.went_home.connect(stop_runtime)
    window.settings_changed.connect(on_settings_changed)
    window.source_toggled.connect(on_source_toggled)
    window.resume_requested.connect(on_resume)

    # 녹음 상태(경과·소리 감지)를 주기적으로 패널에 밀어준다
    from PySide6.QtCore import QTimer

    def poll_status() -> None:
        audio_bytes = 0
        if runtime[0] is not None:
            st = runtime[0].status()
            window.session_page.panel.update_recording_status(st)
            audio_bytes = st.get("audio_bytes", 0)
        window.set_debug_info(audio_bytes)

    status_timer = QTimer()
    status_timer.timeout.connect(poll_status)
    status_timer.start(300)

    window.show()
    window.apply_window_theme()  # winId가 유효해지는 show() 이후에
    exit_code = qt_app.exec()

    stop_runtime()
    store.close()  # WAL 체크포인트 포함 — 동기화가 DB 파일 하나만 옮기면 되게
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
    raise SystemExit(exit_code)


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()  # Windows 패키징(exe) 대비 안전장치
    main()

