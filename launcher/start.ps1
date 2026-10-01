# Reels 工作室啟動程式（Windows）
# 檢查 Python；沒有的話先詢問，同意後才安裝。接著啟動 Reels 工作室並開啟瀏覽器。
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Root = Split-Path -Parent $PSScriptRoot
Add-Type -AssemblyName PresentationFramework

function Ask($text) {
    $r = [System.Windows.MessageBox]::Show($text, "Reels 工作室", "YesNo", "Question")
    return $r -eq "Yes"
}
function Say($text, $icon = "Information") {
    [System.Windows.MessageBox]::Show($text, "Reels 工作室", "OK", $icon) | Out-Null
}
function Find-Python {
    $candidates = @(
        @("py", "-3"), @("python"),
        @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
    )
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue) -and -not (Test-Path $exe)) { continue }
        try {
            $pyArgs = @($c | Select-Object -Skip 1) + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)")
            & $exe @pyArgs 2>$null
            if ($LASTEXITCODE -eq 0) { return ,$c }
        } catch { }  # 微軟市集的 python 假捷徑會丟錯，略過
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    if (-not (Ask "Reels 工作室需要 Python（約 30 MB）。`n`n要現在用 winget 安裝 Python 3.12 嗎？只會安裝給目前的使用者。")) {
        Say "沒有安裝 Python，Reels 工作室無法啟動。`n之後想用時再雙擊啟動檔即可。" "Warning"
        exit 1
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Say "這台電腦沒有 winget。請到 https://www.python.org/downloads/ 下載安裝 Python，安裝時勾選「Add python.exe to PATH」。" "Warning"
        exit 1
    }
    Write-Host "正在安裝 Python 3.12…"
    winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
    if (-not $py) {
        Say "Python 已安裝，但還找不到。請重新開機後再雙擊啟動檔。" "Warning"
        exit 1
    }
}

Set-Location $Root
Write-Host "啟動 Reels 工作室…（關閉這個視窗就會結束程式）"
$exe = $py[0]
$pyArgs = @($py | Select-Object -Skip 1) + @("-m", "reels_studio")
& $exe @pyArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Reels 工作室意外結束。請把上面的訊息截圖給協助你的人。"
    Read-Host "按 Enter 關閉"
}
