# JotThatDown 실행 전 자동 업데이트 — JotThatDown.bat이 호출한다.
# git 원격에 새 커밋이 있으면 받아오고, 업데이트 사실을 알린 뒤 앱을 켠다.
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Notify([string]$message) {
    # 8초 뒤 자동으로 닫히는 팝업 — 실행을 오래 막지 않는다
    (New-Object -ComObject WScript.Shell).Popup($message, 8, "JotThatDown", 64) | Out-Null
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "업데이트 확인 중..."
    git fetch --quiet 2>$null
    $behind = git rev-list --count "HEAD..@{u}" 2>$null
    if ($behind -match '^\d+$' -and [int]$behind -gt 0) {
        Write-Host "새 버전 $behind 건 적용 중..."
        git pull --quiet 2>$null
        if ($LASTEXITCODE -eq 0) {
            $changed = git diff --name-only "HEAD@{1}" HEAD 2>$null
            if ($changed -match 'requirements\.txt') {
                Write-Host "의존성 설치 중..."
                & "$root\.venv\Scripts\pip.exe" install -r requirements.txt --quiet
            }
            Notify "새 버전으로 업데이트되었습니다. ($behind 건 변경)"
        }
        else {
            Notify "업데이트를 받지 못했습니다 - 로컬 변경과 충돌했을 수 있습니다."
        }
    }
}

Start-Process -FilePath "$root\.venv\Scripts\pythonw.exe" -ArgumentList "run_app.py" -WorkingDirectory $root
