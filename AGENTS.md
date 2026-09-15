# AGENTS.md — C:\Users\1\My Window Apps\JotThatDown

> ⚠️ **자동 생성 파일. 직접 고치지 말 것.**
> 원본: `C:\Users\1\.claude\projects\C--Users-1-My-Window-Apps-JotThatDown\memory`
> 재생성: `powershell -File C:\Users\1\HitTheBottom\_migration\sync-rules-to-agents.ps1`
> 생성: 2026-07-29 08:30

전체 맥락은 이 폴더의 `README.md` 참조.

---

## 규칙·컨텍스트 (준수)

---

## 배경 정보

### jotthatdown-project
_JotThatDown 앱의 목적과 확정된 설계 결정 (2026-07-09 설계 완료)_

JotThatDown = 강의용 실시간 음성 자막 + 타임라인 동기화 노션식 노트 앱 (Windows).
사용자는 경희대 학생(haddol010313@khu.ac.kr)이고 강의 수강 시 사용 목적.
프로젝트 위치: "C:\Users\1\My Window Apps\JotThatDown" (2026-07-10에 C:\Users\1\jotthatdown에서 이사, 메모리도 함께 이관됨).
경량화 완료·검증(2026-07-10): RealtimeSTT 제거 → 자체 파이프라인 app/stt/ = capture → segmenter(_StreamingVad — faster-whisper 내장 Silero ONNX를 onnxruntime 스트리밍 구동, v5 분리형/v6 단일세션 모두 지원, torch 완전 제거) → shared_whisper(모델 1개 공유, 자식 프로세스 0개). 실측(콘솔 both): RAM 3GB·3프로세스 → 690MB·1프로세스, VRAM 5.6GB → 3.5GB(데스크톱 포함), TTS 인식·교정 정상. venv는 torch 없이 재구축. 주의: PowerShell 백그라운드로 앱 실행 시 python -u 필요(stdout 파이프 버퍼링).
UX 잔손질(2026-07-10): 자막 더블클릭 수정 기능 제거(클릭=리플레이 즉시, 260ms 지연 삭제; edit_requested/apply_edit/segment_at 삭제). PDF 방향키: 스크롤에 먹히던 문제 → scroll NoFocus + viewport 클릭 시 뷰 setFocus(eventFilter). 위아래 맞춤 시 페이지 가로 중앙 정렬(_origin_x — paint/_draw/_hit 모두 사용). 형광펜 줄 병합(_merge_line_rects — 세로 50% 겹침=같은 줄, 공백 포함 연속 띠).
대량 UX 배치 B(2026-07-10):
- 폰트 전면 나눔스퀘어: assets/fonts + web/fonts에 NanumSquareR/B/EB.ttf 번들. ui/fonts.load_fonts()(QFontDatabase), qt_app.setFont, theme _FONT_STACK, editor.css @font-face, overlay 인라인 전부 교체. spec datas에 assets/fonts 추가.
- 로딩 중엔 '녹음 중' 대신 '준비 중…'(LiveRuntime.loading/_rec_started_ms — 경과는 로딩 후부터). 상단바 안 흔들림: 소스버튼 텍스트 고정+상태는 색(srcState off/on/listening), rec_label minWidth.
- 우측하단 디버그(RAM ctypes GetProcessMemoryInfo/VRAM nvidia-smi 3초 캐시/녹음 MB) set_debug_info.
- 자막 필러 필터: hallucinations에 _FILLERS(어/음/그… 전체가 필러면 드롭, 네/아니요 유지).
- 문장 이어붙이기: segmenter MAX 11s+partial(강제컷 표시), local_engine·models.partial, SessionPage.on_segment가 같은 소스 partial 1.5s내면 병합(update_segment_text+panel.update_last_segment).
- 홈: 소스선택 제거→[노트][PDF노트], DnD 다시 제거(사용자 변심), 폴더 그리드 유지.
- 이미지: toolbox:false(빈 '이미지 선택' 블록 제거, 붙여넣기만) → 이동 후 빈블록 버그 해결.
- 에디터: 코드블록 자동높이(box-sizing+지연fit), 슬래시 커스텀필터, 점6개+Backspace로 선택블록 삭제(멀티=일괄+undo 1회 shouldSaveHistory 토글), 멀티선택 하이라이트 간 여백, 자막 Ctrl±/휠 크기조절(패널 eventFilter).
- 전역 char아이콘→벡터(icons.make_ui_icon: back/plus/prev/next/stop/play/restore). 교정테이블 다크 색(QHeaderView/CornerButton/item text).
- 코드블록 C/C++ 하이라이트 완료: web/vendor/highlight.js(11.9 common, cpp 포함) + 커스텀 HljsCodeTool(editor.js) — 뒤 pre(색칠, 배경)+투명 textarea(캐럿) 레이어, 항상 language:'cpp', 자동높이. editor.css .hljs-code + hljs-* 토큰색(라이트/다크). 기존 {code} 데이터 호환.
- 이미지 이동 후 빈 로딩블록 버그: pruneStrayImageBlocks()(image-tool__image-picture 없는 image 블록 삭제, imageUploading>0이면 스킵), onChange의 block-moved 시 호출.
- 노트 이미지 크기조절·정렬 완료(2026-07-10): @editorjs/image → 자체 NoteImageTool(editor.js). 붙여넣기 전용(pasteConfig files/tags), 우하단 핸들 드래그로 폭% 조절(20~100), renderSettings에 좌/중/우 정렬. data는 {file:{url},url,width,align} — MD export(file.url) 호환. CSS .note-image(align-*)/__frame/__img/__handle. pruneStrayImageBlocks는 .note-image__img 기준. 45% 가운데 정렬 스크린샷 검증. (image.js 번들은 로드만 되고 미사용)
- 남은 요청 없음(2026-07-10 기준 전부 반영). 실타이핑 검증 필요 항목: 슬래시메뉴, 토글Enter, 코드입력 하이라이트, 이미지 붙여넣기/리사이즈.
DnD·슬래시·토글·녹음상태·최소화오버레이(2026-07-10):
- 홈 DnD: _GridList(드래그→폴더 위 드롭=이동, dropped_on_folder)·_DropOutZone(폴더 안에서만 보이는 '밖으로 빼기' #dropOut). list_sessions(only_folderless=True).
- 슬래시 메뉴: '/' 입력은 블록에 남고(keydown에서 stopPropagation만—네이티브 툴박스 차단, 문자는 입력됨), input에서 블록텍스트 /^\/([^\s/]*)$/ 매칭→커스텀 .slash-menu 필터(SLASH_COMMANDS), ↑↓/Enter/Esc 조작, chooseSlash→convertBlockTo.
- 토글 수정: convertBlockTo가 foreignKey/toggle-block__item 유지(토글 안 글머리 됨). 토글 자식 Enter=handleToggleChildEnter(내용 있으면 토글 안 새 줄, 빈 줄이면 밖으로).
- 녹음 상태: local_engine.heard_recently()(RMS>0.01), LiveRuntime.status(), studio QTimer 300ms→panel.update_recording_status. 상단바: ● MM:SS 녹음중(빨강), 소스버튼 sourceToggle ON/OFF 명확+listening시 초록.
- 최소화 오버레이: overlay.py 재설계(반투명 다크 카드, 흰 20px, 이전줄 흐림, 출처 색선, 복원버튼). StudioWindow.changeEvent에서 녹음 중 최소화 시 표시, on_segment가 오버레이에도 push.
홈 그리드 개편(2026-07-10): 리스트→아이콘 그리드(QListWidget IconMode, 96px, GoodNotes풍). 최상위=폴더들(큰 컬러 폴더아이콘+이모지, make_folder_icon 그라데이션 개선)+폴더없는 노트(list_sessions(only_folderless=True) — DB에 s.folder_id IS NULL 필터 추가). 폴더 더블클릭→진입(← 뒤로), 노트 더블클릭→열기, 우클릭 메뉴 유지. 노트 아이콘 make_note_icon(접힌 모서리 종이, PDF는 붉은 배지). 홈 상단 버튼 [📝 노트][📕 PDF 노트] — 소스선택(마이크/시스템 콤보) 제거(세션 안 상단바에서 토글). studio.on_new_session(kind): pdf면 파일다이얼로그→import_pdf. 툴바 📕 PDF 임포트 버튼 제거. 새폴더 이모지=버튼 클릭→그리드 펼침(_FOLDER_EMOJIS). 녹음 컨트롤(🎤🔊·정지·재생·이어녹음) 전부 자막패널 상단 #recordBar로. PDF 렌더 2x 슈퍼샘플+Antialiasing/SmoothPixmapTransform(계단현상 감소).
PDF 스타일 팝오버(2026-07-10): 도구 더블클릭 시 별도 다이얼로그 대신 버튼 바로 아래 가로 팝오버(_StylePopover, Qt.Popup — 색 점3+구분선+굵기3 한 줄, 265x33). 고르는 즉시 apply 콜백+close, 바깥 클릭 자동 닫힘. _ToolStyleDialog/FramelessDialog import 제거. 배치 검증 scripts/test_style_popover.py. QSS #stylePopover.
패키징(2026-07-10): PyInstaller onedir exe 완성 — packaging\build.cmd 또는 python -m PyInstaller packaging\JotThatDown.spec. 엔트리 run_app.py. 산출 dist\JotThatDown\JotThatDown.exe(2.67GB, 사용법.txt 동봉). app/paths.py로 경로 추상화: app_root()=쓰기(소스=프로젝트루트/exe=실행파일옆), resource_root()=번들(web/). 함정 2개 해결: (1) windowed exe는 sys.stdout=None → paths.ensure_std_streams()로 3개 엔트리 보정(print 크래시 방지); (2) NVIDIA DLL은 spec에서 datas로 nvidia/<pkg>/bin 구조 한 벌만(binaries로 넣으면 루트 복제 1GB 중복 → 3.6GB), cuda_dlls.py가 _internal/nvidia/*/bin 등록. corrections.txt/data는 exe 옆에 자동 생성. 앱 아이콘 assets/app.ico(scripts/make_icon.py). exe 기동·홈 렌더 스크린샷 검증됨. 모델은 미포함(첫 실행 시 HF서 자동 다운로드).
UX 9차(2026-07-10): 녹음 컨트롤(🎤/🔊 토글·■정지)을 툴바→자막 타임라인 헤더로 이동(panel.set_live_controls(visible, active), 시그널은 패널→창 포워딩, studio.py 배선 불변). 토글 Enter 수정: editorjs-toggle-block의 자체 Enter 처리가 죽어 있어(코어 2.29/2.30 모두) editor.js에서 직접 구현 — 토글 루트 wrapper.id=fk, 자식은 div[foreignKey=fk]+toggle-block__item 클래스; enterToggleContent()가 자식 생성/첫 줄 이동. 합성 KeyboardEvent 테스트 scripts/test_toggle_enter.py로 검증(activeInItem true). 참고: @editorjs/editorjs 2.30.8 패키지가 자체적으로 '2.31.0-rc.7' 배너를 찍음(공식 빌드 실수, 실제로는 2.30.8).
형광펜 v3 — 글줄 교차 방식(2026-07-10): getSelection은 시작/끝점이 글자 위여야만 동작해서 폐기. getAllText(page).bounds()로 글줄 지도(_text_lines, 페이지 캐시)를 만들고 드래그 rect와 교차 — 세로 겹침 35% 미만 줄 제외, 가로는 드래그∩글줄 clip. 글자 안 지나면 빈 목록(아무것도 안 그림, 폴백 직사각형 삭제). 자막 행 정렬 수정: preferred_height(heightForWidth 기반)+패널 resizeEvent 재계산, 라벨 AlignTop. 테스트 PDF는 수제 raw PDF(QPdfWriter는 텍스트 추출 불가!).
형광펜 텍스트 스냅(2026-07-10): QPdfDocument.getSelection(page, 포인트 좌표) → QPdfSelection.bounds() 폴리곤들의 boundingRect를 정규화해 줄 단위 형광펜으로 저장(_PdfCanvas.highlight_rects). 글자 없으면 띠 폴백. 드래그 미리보기도 스냅(_drag_highlights). 주의: _draw는 저장 좌표를 최종본으로 취급(변환 재적용 금지).
PDF 필기 v2(2026-07-10): 단일 페이지 모드(◀▶·←→·PgUp/Dn, page_changed 시그널) + PDF 페이지별 전용 노트(pages.pdf_page 컬럼, store.page_for_pdf → 'p.N' 루트 페이지, root_page/멀티루트 마이그레이션은 pdf_page IS NULL 필터 필수). 밑줄=자유 직선(대각선), 형광펜=글줄 높이 띠(_HIGHLIGHT_HALF=0.011, shape_rect로 저장 시 변환), 도구 버튼 더블클릭=색(검/파/빨)·굵기(1.2/2.4/4.0) 다이얼로그(settings.pdf_tool_styles 저장, style_saved→settings_changed), 지우개 드래그 연속 삭제, Ctrl+휠/Ctrl± 줌+좌우/위아래 맞춤(set_render_width), 아이콘 전용 툴바(icons.make_tool_icon), '이동' 버튼 제거(도구 재클릭=해제). pdf_annotations.width 컬럼 추가. 에디터: placeholder 제거, 블록메뉴 검색필드 복원(/ 필터링용, 컴팩트 스타일). 교정 사전은 설정 다이얼로그 안으로 이동(툴바 액션 제거). 홈 세션 우클릭: 폴더 이동+세션 삭제(DB 전체+녹음/PDF 파일).
PDF 필기 v1(GoodNotes 모티브, 2026-07-10): 세션 좌측이 상하 분할 [PDF 필기 / 노트]. 툴바 📕 PDF로 import(data/pdf/<sid>.pdf 복사, sessions.pdf_path). ui/pdf_view.py: QtPdf 렌더+주석 캔버스, 도구=이동/밑줄/형광펜/사각형/타원/지우개, 주석은 pdf_annotations 테이블(페이지 정규화 좌표, t_ms 저장—UI 미노출). 스모크 scripts/test_pdf_view.py(QPdfWriter로 PDF 생성) 통과.

**확정 결정** (상세는 리포의 DESIGN.md가 기준 문서):
- 마이크 + WASAPI 루프백 동시 캡처, 소스별 자막 구분
- 로컬 faster-whisper large-v3 GPU (RTX 3060 Ti 8GB, i5-13600KF, 16GB RAM, Python 3.10)
- 한영 혼용 인식 + 용어집(hotwords) 지원 필수
- PySide6 + QWebEngineView에 Milkdown 에디터 임베드 (노션식 WYSIWYG)
- 좌: 노트 / 우: 자막 타임라인, 접으면 컴팩트 오버레이
- 세션 오디오 OGG 녹음, 타임스탬프 클릭 재생
- SQLite 저장 + 순수 MD 내보내기

**Why:** 설계 단계에서 AskUserQuestion으로 사용자가 직접 고른 결정들 — 재논의 불필요.
**How to apply:** 구현 시 DESIGN.md의 마일스톤(M1~M6) 순서를 따른다.
2026-07-09 기준 M1 완료(사용자 라이브 마이크 테스트 통과) + 교정 사전 완료 + M3 완료(루프백 SYS 인식·both 모드·교정 적용까지 end-to-end 실증, VRAM 5.6/8GB). M2(오버레이) 완료 — PySide6 오버레이(python -m app.run_overlay), 스크린샷 검증됨. 공용 조립은 app/bootstrap.py.
M4 코드 완료(python -m app.studio) — 에디터는 Milkdown 대신 Editor.js(web/vendor에 번들 커밋, 빌드 불필요, 블록 id 기본 제공). 에디터↔QWebChannel↔SQLite 왕복은 사용자 실입력으로 검증됨(블록 타임스탬프 정확). 자막 패널·인용·양방향 점프는 미검증 — GPU 포화(large-v3 3개) 때문. 남은 검증: 사용자가 오버레이 끄고 studio 단독 실행.
언어는 ko 고정(사용자 지시) — 자동 감지의 제3언어 오감지 방지, 혼용 영어는 ko 모드가 처리.
주의: 8GB VRAM에 large-v3는 2개까지 — overlay both + studio 동시 실행 금지. studio에 자막 패널이 내장돼 있어 오버레이 병행 불필요.
M4는 사용자가 전 기능(자막·인용·점프 포함) 확인 완료. 모델 자동 선택 도입(노트북 대비): VRAM 기준 large-v3 / large-v3-turbo / CPU small — bootstrap.resolve_config(source).
M5+M6 코드 완료(2026-07-09): 스튜디오가 홈(세션 목록/검색/새 세션)+세션 페이지 구조로 개편. 세션 녹음(소스별 OGG, 세션 시계에 무음 패딩 정렬 — data/audio/<sid>_<src>.ogg), 자막 ▶ 다시 듣기(SnippetPlayer, soundfile+PyAudio 직접 재생), 지난 세션 열기/이어 편집, 제목 rename, MD 내보내기(export.py — Editor.js JSON→MD+타임스탬프+자막 부록), 교정 사전 편집 다이얼로그. 단위테스트 통과(export/db/트랙 정렬 1218ms=1218ms), 홈 화면 기동 확인.
UX 개편 완료(노션 팔레트): 테마 토큰은 app/ui/theme.py(QSS)와 web/editor.css(CSS 변수)에 이중 정의 — 동기화 필수. 설정 다이얼로그(테마 라이트/다크, 모델 수동 선택, 발화 대기, 에디터 글꼴) → data/settings.json. 로딩 프로그레스바. 홈(라이트)·세션(다크) 스크린샷 검증 완료. UI 프리뷰 도구: scripts/preview_ui.py [light|dark] — 엔진 없이 아카이브 모드로 창만 띄움.
함정: QToolBar.addWidget한 위젯은 반환된 QAction으로만 show/hide 가능.
세션 중 소스 전환 추가(2026-07-09): 마이크 엔진도 MicCapture→feed_audio로 통일(RealtimeSTT use_microphone=False 항상), engine.set_active()로 즉시 음소거. LiveRuntime이 소스별 엔진·녹음 트랙을 지연 생성(첫 활성화 때 모델 로딩), 툴바에 🎤/🔊 체크 토글. 모델 선택은 항상 2소스 기준. 녹음 트랙은 꺼진 동안 무음 패딩. Whisper 무음 환각 필터 추가(text/hallucinations.py, 정확 일치만 드롭) — 변환 체인은 bootstrap.build_transforms() = [환각필터, 교정사전]. feed 경로는 SYS로 검증됨, 마이크 육성 재검증은 사용자 대기.
에디터 대확장(사용자 명세, 2026-07-09): 이미지 붙여넣기(@editorjs/image + bridge.saveImage → data/attachments, file:// URL), 코드블럭/형광펜(Ctrl+Shift+H)/토글 플러그인, 인라인코드 Ctrl+E, 마크다운 단축입력(#/##/###/```/>토글/*/1./|인용 + 스페이스 — editor.js maybeConvertMarkdown), 괄호·따옴표 자동닫기, 리스트 깊이 마커 CSS(•◦▪). MD 내보내기에 code/image/toggle/mark(==) 반영. UMD 전역명: ImageTool, CodeTool, Marker, ToggleBlock. 키 입력 동작(변환·단축키·붙여넣기)은 사용자 실타이핑 검증 대기.
페이지 v2 — 노션식 중첩(2026-07-09, 탭 UI 폐기): pages.parent_page_id 추가, 에디터 커스텀 블록 PageLinkTool(+메뉴 '페이지' → py.createSubPage로 부모=현재 페이지 생성, 클릭 py.openPage로 진입, 렌더 시 py.pageTitle로 제목 동기화 — 브리지 핸들러 주입 방식: bridge.create_page_handler/page_title_handler). 탭바→브레드크럼(노트 › 하위, 현재 크럼 더블클릭 rename). 마이그레이션: 여분 루트 페이지→첫 페이지 하위 + 링크 블록 자동 삽입(실데이터 검증됨). 내보내기 pages_tree 깊이 우선, pageLink는 참조 표시. store: root_page/get_page/child_pages/pages_tree (pages_for/pages_with_docs 제거).
UX 8차(2026-07-09): 프레임리스 테마 다이얼로그 베이스(ui/dialogs.py FramelessDialog — 자체 제목줄+✕+드래그, QSS #framelessDialog) → 폴더/설정/교정 다이얼로그 적용. 플레이바 눈금: _TickSlider(paintEvent 오버레이) — 자막 위치=흐린 회색 |, 이어녹음 지점=주황 굵은 |. 이어녹음 지점은 session_markers 테이블(kind='resume')에 기록(과거 세션은 소급 불가). 픽셀 테스트 scripts/test_tick_slider.py.
UX 7차+폴더/페이지(2026-07-09): 리스트 들여쓰기 실측 해결 — 중첩 .cdx-list 자체에 padding-left:40px가 원인(자식컨테이너=중첩리스트 동일 요소라 하위 선택자 안 먹음), 요소 자신 padding 0 + margin 20px → 프로브 검증 20px/단계. Tab 범용 들여쓰기: IndentTune 블록 튠(editor.js 자작, tunes:["indent"], level*26px, 제목·리스트 제외, ⋮⋮메뉴에도 항목). 인용구 컴팩트+빈 캡션 숨김(:focus-within), 토글 자식 placeholder 숨김, 블록메뉴 검색필드 숨김+checklist toolbox:false(중복 제거). 재생 위치 자막 파스텔 하이라이트(playing_bg 토큰, PlayerBar.position_changed→bisect). 폴더 기능: folders 테이블+sessions.folder_id, 홈 폴더 칩(icons.make_folder_icon 색+이모지, 우클릭 삭제), 세션 우클릭 '폴더로 이동'. 페이지 기능: pages 테이블(+notes 마이그레이션, block_times.page_id), 에디터 위 페이지 탭(_PageTab 더블클릭 rename, + 추가, 전환 시 saveNow 후 200ms), MD 내보내기 다중 페이지. QWidget 탭바는 addWidget stretch 필수(웹뷰와 나눌 때).
UX 6차(2026-07-09): 상태바 아카이브 문구 제거+테마 토글 버튼(상태바 우측, settings_changed 재사용), 타이틀바 테마색(ui/native.py DwmSetWindowAttribute 20/35/36, show() 후 호출 필수), 자막 범례 제거, 자막 라벨 _SegmentLabel — 클릭(260ms 지연)=리플레이/더블클릭=수정(QInputDialog→store.update_segment_text, TranscriptSegment.db_id 필드 추가)/드래그 선택→[복사·교정 사전에 추가] 메뉴(CorrectionsDialog prefill 파라미터). 사용자가 이어녹음 계속 실사용 중(오디오 8:38까지 증가).
UX 5차(2026-07-09): 자막 행 단순화 — ▶/인용 버튼·소스 아이콘 제거, 소스는 색(마이크=파랑 segMic, 시스템=기본 segSys), 자막 클릭=그 시각 리플레이(녹음 있으면 play_from, 없으면 노트 점프). 인용 기능은 UI에서 제거됨(사용자 결정). 모델 로딩 대기는 타임라인 하단 애니메이션 배너(show_pending). 코드블럭 자동 높이(fitCodeArea, resize:none). 글머리 1.35em, 중첩 들여쓰기 축소(grid-template-areas child child + margin 18px). 이어녹음 실사용 검증됨(29초→1:58 증가 확인).
에디터 4차(2026-07-09): 블록 도구(+·⋮⋮ Click to tune)를 항상 본문 왼쪽 고정 — Editor.js narrow 모드(<650px)가 오른쪽으로 옮기는 것을 !important로 무효화(Editor.js는 스타일을 런타임 주입하므로 !important 필수). 왼쪽 여백 148px 차선: [타임스탬프 56px][도구][본문]. preview_ui.py --probe로 computed style 검증 가능.
세션 재생/이어녹음(2026-07-09): 자막 패널 하단 PlayerBar(ui/player_bar.py) — MixPlayer(audio/player.py, 트랙들 int32 합산 재생+seek+position_ms 폴링)로 전체 재생, [● 이어서 녹음]=resume. Resume 구조: SessionClock(offset_ms), TrackWriter(resume=True)가 기존 OGG를 .prev로 rename 후 새 파일 앞에 복사(OGG는 append 불가), offset = max(오디오 길이, DB max_time_ms). 아카이브 열기/정지 시 studio.py가 set_playback 호출. attach_live()로 리로드 없이 라이브 전환. 단위테스트: 이어녹음 보존+5초 정렬 통과.
에디터 3차 개선(2026-07-09): 닫힘문자 오버타입(자동 삽입분만 1회 스킵 — pendingCloses 스택, 클릭/Enter 시 초기화), 웹 스크롤바 테마화(::-webkit-scrollbar 트랙 투명), body overflow-x hidden, Qt QScrollBar add-page/sub-page 투명, QListWidget 가로 스크롤바 off.
에디터 2차 개선(2026-07-09): editorjs-undo(Ctrl+Z, boot 시 initialize로 기준점), editorjs-drag-drop(⋮⋮ 핸들 드래그 이동), 다크 선택영역 수정(::selection !important — Editor.js 코어가 #e1f2ff 강제하는 게 원인), 빈 여백 클릭→마지막 블록 캐럿(focusEnd), 화살표 자동변환(-> →, <- ←, ←+> ↔, 코드블럭 제외). 다크 모드에서 선택영역·핸들 렌더링 실확인. 공유 워커 대신 소스별 RealtimeSTT 인스턴스 2개 구조(DESIGN.md에 기록).
주의: torch는 반드시 CUDA 빌드(2.11.0+cu128, requirements.txt에 고정) — RealtimeSTT가 torch.cuda.is_available()로 GPU를 판단해서 CPU torch면 GPU가 있어도 CPU 강등됨. Silero VAD는 torch.hub 신뢰 등록 완료.
고유명사 오인식 대책: hotwords 대신 후처리 교정 사전(corrections.txt) 채택 — 사용자 선택. M6에서 편집 UI 필요.

### solid-principles
_사용자 지시 — 모든 코드는 SOLID 원칙을 지켜 유지보수 용이하게 작성할 것_

[[jotthatdown-project]] 코드 작성 시 SOLID 원칙을 준수하라는 명시적 지시 (2026-07-09).

**Why:** 유지보수성이 사용자의 우선순위. 혼자 오래 발전시킬 개인 프로젝트라 구조가 무너지면 안 됨.
**How to apply:** 엔진/싱크/저장소는 추상 인터페이스(ports)로 정의하고 구현체는 어댑터로 분리(DIP/OCP). 모듈은 한 가지 책임만(SRP). 인터페이스는 작게(ISP). 단, 개인 프로젝트 규모에 맞게 과도한 추상화는 피할 것.

