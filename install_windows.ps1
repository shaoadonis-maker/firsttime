# 卷家 — video-autopilot-kit 一鍵安裝（Windows）
# 用法：在 PowerShell 執行
#   powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
# 可改安裝位置：-Root "D:\其他資料夾"
param(
    [string]$Root = "G:\影片製作\202608P4"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

# 1) Python 3.9+
Step "檢查 Python"
$py = $null
foreach ($c in @("py", "python")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
        try {
            & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { $py = $c; break }
        } catch { }  # Windows 市集的 python 假捷徑會丟錯，略過
    }
}
if (-not $py) {
    Write-Host "找不到 Python 3.9+，用 winget 安裝 Python 3.12…"
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $py = "py"
}
& $py --version

# 2) ffmpeg
Step "檢查 ffmpeg"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "找不到 ffmpeg，用 winget 安裝…"
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "ffmpeg 安裝後仍找不到。請關掉 PowerShell 重開，再執行一次本腳本。"
}
ffmpeg -version | Select-Object -First 1

# 3) 安裝 kit 到素材資料夾（官方安裝器，會驗證 SHA-256）
Step "安裝 video-autopilot-kit 到 $Root"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$installer = Join-Path $Root "install_or_upgrade.py"
Invoke-WebRequest "https://github.com/Hao0321/video-autopilot-kit/releases/latest/download/install_or_upgrade.py" -OutFile $installer
& $py $installer --install-root $Root --apply
if ($LASTEXITCODE -ne 0) { throw "kit 安裝失敗" }

# 4) Python 媒體套件
Step "安裝 Python 媒體套件"
& $py -m pip install -r (Join-Path $Root "requirements-media.txt")
if ($LASTEXITCODE -ne 0) { throw "pip 安裝失敗" }

# 5) 素材資料夾
Step "建立素材資料夾"
foreach ($d in @(
    "videos\_INBOX\直式-vertical-Shorts-Reels\1",
    "videos\_INBOX\橫式-landscape-YT長片",
    "assets\bgm\旅遊",
    "assets\bgm\走路散步",
    "profiles"
)) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }

# 6) 字幕字型：霞鶩文楷 TC（Reels 旅遊題材自動使用；安裝給目前使用者，不需管理員）
Step "安裝字型 LXGW WenKai TC"
$fontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$regKey = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
New-Item -ItemType Directory -Force -Path $fontDir | Out-Null
if (-not (Test-Path $regKey)) { New-Item -Path $regKey -Force | Out-Null }
foreach ($w in @("Regular", "Medium")) {
    $file = "LXGWWenKaiTC-$w.ttf"
    $dest = Join-Path $fontDir $file
    if (-not (Test-Path $dest)) {
        Invoke-WebRequest "https://github.com/lxgw/LxgwWenkaiTC/releases/download/v1.522/$file" -OutFile $dest
    }
    New-ItemProperty -Path $regKey -Name "LXGW WenKai TC $w (TrueType)" -Value $dest -PropertyType String -Force | Out-Null
}

# 7) 健檢
Step "執行健檢"
Push-Location $Root
try { & $py src\system_health.py --quick } finally { Pop-Location }

Write-Host "`n完成！接下來：" -ForegroundColor Green
Write-Host "  1. 把 brand.md 等 5 個 profile 放進 $Root\profiles\，config.py 放進 $Root\"
Write-Host "  2. Reels 片段放進 $Root\videos\_INBOX\直式-vertical-Shorts-Reels\1\"
Write-Host "  3. BGM 放進 $Root\assets\bgm\旅遊\"
Write-Host "  4. 在 $Root 執行： $py src\shorts_autopilot.py scan 1"
