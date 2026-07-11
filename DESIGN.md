# JotThatDown — 설계 문서

실시간 음성 자막 + 타임라인 동기화 노트 앱 (Windows).
강의를 들으며 노트를 쓰면, 각 자막과 노트 블록에 시각이 기록되어
"이 메모를 쓸 때 무슨 말이 나왔는지"를 나중에 소리까지 되짚을 수 있다.

## 확정된 결정

| 항목 | 결정 |
|---|---|
| 오디오 소스 | 마이크 + 시스템 사운드(WASAPI 루프백), **동시 캡처** 지원 |
| STT | 로컬 faster-whisper, 모델은 하드웨어에 맞춰 자동 선택(bootstrap.resolve_config): 인스턴스당 VRAM 2.2GB↑ → `large-v3`, 1.2GB↑ → `large-v3-turbo`, GPU 없음 → CPU `small`. 노트북 이식 대비 (2026-07-09) |
| 언어 | 한국어 고정(ko) — 혼용 영어는 ko 모드가 영문으로 받아씀. 자동 감지는 제3언어 오감지 때문에 배제 (2026-07-09 사용자 결정) |
| 스택 | Python 3.10 + PySide6 |
| 에디터 | 노션식 블록 에디터 — QWebEngineView에 Editor.js 임베드 (Milkdown에서 변경: 빌드 체인 불필요 + 블록 id 기본 제공이 타임스탬프 기능과 정합, 2026-07-09) |
| 화면 구성 | 좌: 노트 에디터 / 우: 실시간 자막 타임라인 (접으면 컴팩트 오버레이) |
| 녹음 | 세션 오디오를 OGG로 저장, 타임스탬프 클릭 시 해당 시점 재생 |
| 자막 표시 | 발화 종료 시 확정 문장 표시 (지연 ~1–2초) |
| 저장 | SQLite (세션·자막·블록 타임스탬프) + 순수 마크다운 내보내기 |

## 구현 전략: 기존 오픈소스 조립

밑바닥 구현 대신 검증된 오픈소스를 조립하고, 차별점(타임라인 동기화)만 직접 만든다.

| 부분 | 출처 | 비고 |
|---|---|---|
| 캡처+VAD+실시간 STT | [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) (MIT) | faster-whisper GPU, 콜백 API. 마이크는 기본 지원, 루프백은 `use_microphone=False` + `feed_audio()`로 두 번째 인스턴스에 주입 |
| 루프백 캡처 | PyAudioWPatch | [savander/real-time-captions](https://github.com/savander/real-time-captions)(PyQt6+faster-whisper 자막 앱) 배선 참고 |
| 에디터 | Milkdown | 블록 타임스탬프 플러그인만 자작 |
| UX 참고 | [Hyprnote/anarlog](https://github.com/fastrepl/anarlog) | 가장 유사한 완성 앱이나 Tauri/Rust 스택이라 포크하지 않음 (2026-07 조사 결정) |
| 타임라인 동기화 | **직접 구현** | 어느 저장소에도 없는 핵심 차별점 |

## 아키텍처

```
[마이크 캡처 스레드]  ──┐  각각 Silero VAD로
[루프백 캡처 스레드]  ──┤  발화 청크 분리      ──> [공유 Whisper GPU 워커(큐)]
        │              └─> [세션 녹음기: 믹스 → OGG]           │
        │                                                     ▼
        └──────────── 세션 타이머 (elapsed ms) ───> [SQLite 세션 저장소]
                                                              │
                                              ┌───────────────┴──────────────┐
                                              ▼                              ▼
                                     [메인 창 (PySide6)]            [컴팩트 오버레이]
                                      노트 에디터 ‖ 자막 패널          항상 위, 클릭 통과,
                                      (QWebChannel 브리지)            최근 2–3줄 자막
```

- 캡처 → VAD → 인식 → UI 는 전부 큐로 연결된 별도 스레드. GPU 인식이 오디오
  캡처나 UI를 절대 블로킹하지 않는다.
- (설계 변경, 2026-07-09) 당초 "공유 Whisper 워커 1개" 계획이었으나 RealtimeSTT는
  레코더 인스턴스마다 자체 모델을 띄운다 → 소스별 인스턴스 2개로 변경.
  실측 VRAM 5.6GB/8GB (large-v3 int8_float16 × 2)로 문제없이 수용됨.
- 인식 결과는 싱크로 가기 전에 **교정 사전**(corrections.txt)을 통과한다:
  "잘못 인식된 표현 -> 올바른 표현" 규칙으로 고유명사(노션, 다이소 등) 오인식을
  결정적으로 치환. 실행 중 파일 수정 시 자동 재로딩. M6에서 편집 UI 제공.
- 두 소스는 파이프라인을 섞지 않고 자막에 출처(🎤/🔊)를 표시한다.
- Whisper 모델 인스턴스는 하나를 두 스트림이 큐로 공유한다.

## 타임라인 동기화 (핵심 기능)

- 세션 시작 시 단조 타이머 시작. 모든 데이터는 `t_ms`(세션 경과 밀리초) 기준.
- 자막 세그먼트: 발화의 시작/끝 `t_ms` 기록.
- 노트 블록: 에디터에서 새 블록 생성 순간의 `t_ms`를 블록 속성으로 기록,
  블록 왼쪽 여백(gutter)에 `14:23` 형태로 흐리게 표시.
- 노트 블록 타임스탬프 클릭 → 자막 패널이 해당 시각으로 스크롤.
  자막 클릭 → 그 시각의 노트 블록으로 점프. (양방향)
- 타임스탬프 옆 ▶ 버튼 → 세션 OGG를 해당 시점부터 재생 (QMediaPlayer seek).
- 자막 세그먼트 "노트로 인용" 버튼 → 에디터에 인용 블록으로 삽입.

## 데이터 모델 (SQLite)

```sql
sessions(id, title, started_at, ended_at, audio_path)
segments(id, session_id, t_start_ms, t_end_ms, source /* mic|system */, text)
notes(session_id, doc_md, updated_at)            -- 문서 전체 (마크다운)
block_times(session_id, block_id, t_ms)          -- 블록별 타임스탬프
```

- 에디터 문서는 마크다운으로 저장(블록 id는 문서 내 안정적 식별자로 유지),
  타임스탬프는 별도 테이블. MD 내보내기 시 `[00:14:23]` 형태로 인라인 병합.

## 모듈 구조

```
jotthatdown/
├─ app/
│  ├─ main.py               # 엔트리포인트
│  ├─ session.py            # 세션 상태·타이머·컴포넌트 조율
│  ├─ audio/
│  │  ├─ capture.py         # PyAudioWPatch: 마이크/루프백 스트림, 16kHz 모노 리샘플
│  │  ├─ segmenter.py       # Silero VAD(onnxruntime) 발화 청크 분리
│  │  └─ recorder.py        # 두 소스 믹스 → OGG 스트리밍 기록 (soundfile)
│  ├─ stt/
│  │  ├─ engine.py          # faster-whisper GPU 워커 (인식 큐 소비)
│  │  └─ glossary.py        # 용어집 파일 → hotwords/initial_prompt
│  ├─ store/
│  │  ├─ db.py              # SQLite 접근
│  │  └─ export.py          # 타임스탬프 포함 MD 내보내기
│  └─ ui/
│     ├─ main_window.py     # 좌우 분할 메인 창
│     ├─ editor_view.py     # QWebEngineView + QWebChannel 브리지
│     ├─ transcript_panel.py# 자막 타임라인 패널
│     ├─ overlay.py         # 컴팩트 자막 오버레이 (frameless, 클릭 통과)
│     ├─ player.py          # 오디오 재생/seek
│     └─ tray.py            # 트레이 아이콘, 소스 선택, 시작/정지
├─ web-editor/              # Milkdown 기반 에디터 번들 (npm 빌드 산출물 포함)
├─ glossary.txt             # 사용자 편집 용어집
├─ requirements.txt
└─ DESIGN.md
```

## 주요 의존성

- `RealtimeSTT` (faster-whisper·Silero/WebRTC VAD 포함; + `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` — CUDA DLL을 pip로 해결)
- `PyAudioWPatch` (WASAPI 루프백), `numpy`, `soundfile`
- `PySide6` (+ WebEngine, Multimedia)
- web-editor: Milkdown (ProseMirror 기반, MD-first) — 블록 타임스탬프 속성 플러그인 자작

## 기술 리스크와 대응

1. **에디터 브리지 (최대 난제)**: Milkdown 커스텀 플러그인으로 블록 생성 이벤트를
   QWebChannel로 파이썬에 전달, 타임스탬프 gutter 렌더링. → M4에서 최소 동작
   (블록 생성 시각 기록 + gutter 표시)부터 검증하고 살을 붙인다.
2. **한영 혼용 인식**: `large-v3` + 언어 자동 감지 기본, 설정에서 한국어 고정 옵션.
   용어집 hotwords로 보강. 품질 미달 시 세그먼트별 언어 힌트 전략 조정.
3. **CUDA 환경**: ctranslate2가 요구하는 cuBLAS/cuDNN을 pip 패키지로 동봉하여
   시스템 CUDA 설치 없이 동작하게 한다. GPU 불가 시 CPU `small` 모델 폴백.
4. **동시 캡처 부하**: 인식 큐 공유로 해결. 두 소스가 계속 겹치면 지연이 늘 수
   있으나 강의 시나리오(주로 한쪽만 활성)에서는 문제 없음.

## UX/테마 (2026-07-09 개편)

- 노션 팔레트 기반 디자인 토큰: 본문 #37352F, 웜그레이 #787774/#9B9A97,
  종이색 #F7F6F3, 액센트 #2383E2, 다크 #191919/#202020.
- 토큰의 단일 출처는 `app/ui/theme.py`(Qt QSS 생성)이며 `web/editor.css`의
  CSS 변수와 값이 같아야 한다 — 한쪽 수정 시 양쪽 동기화.
- 설정(data/settings.json, `app/settings.py`): 테마(라이트/다크), 인식 모델
  (자동/수동), 발화 종료 대기, 에디터 글꼴 크기. 테마·글꼴은 즉시 적용,
  모델·대기는 다음 세션부터.
- 로딩 대기: 상태 메시지에 "로딩"이 포함되면 상태바에 인디터미네이트
  프로그레스가 표시된다.

## 마일스톤

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| M1 | RealtimeSTT 통합 스파이크 (마이크 → 콘솔) | 말하면 터미널에 한영 혼용 텍스트 출력, large-v3 GPU 확인 |
| M2 | 컴팩트 오버레이 자막 | 화면 위 자막 실시간 표시, 클릭 통과 |
| M3 | 루프백 feed_audio + 동시 모드 | 유튜브 소리와 내 말이 출처 구분되어 표시 |
| M4 | 메인 창 + Milkdown 에디터 + 타임스탬프 동기화 | 블록별 시각 기록, 양방향 점프 |
| M5 | 세션 녹음 + 클릭 재생 | 타임스탬프 ▶로 해당 시점 소리 재생 |
| M6 | 세션 목록/검색, MD 내보내기, 용어집·교정 사전 편집 UI, 트레이, 마감 | 일상 사용 가능 |
