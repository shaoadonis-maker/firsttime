# 卷家 Reels 工作室

把 [video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit) 的 IG Reels 生產線包成圖形介面：
拖放影片、在表格裡打字幕、按一下輸出。不用打指令，也不用手寫 `_plan.py`。

## 開始使用（Windows）

1. 在 GitHub 這個分支按 **Code → Download ZIP**，解壓縮到任何資料夾。
2. 雙擊 **`啟動Reels工作室.bat`**。
   - 電腦沒有 Python 的話，會跳出視窗問你要不要安裝，按「是」才會安裝。
3. 瀏覽器會自動打開 Reels 工作室，照設定精靈回答 4 個問題（最後一題選素材資料夾，例如 `G:\影片製作\202608P4`）。
4. 「環境檢查」會列出缺少的軟體（ffmpeg、剪輯引擎、影像分析套件、霞鶩文楷字型），
   每一項都會先說明要做什麼，**同意後才安裝**。

macOS／Linux：在終端機執行 `./start.sh`。

## 做一支 Reels

1. **音樂庫**：先放幾首背景音樂，依情緒分類（例如「旅遊」）。
2. **新增 Reels**：填地點名稱，把同一個景點的 3–8 段影片拖進去，按「上傳並自動排片」。
3. **編輯**：
   - 片段時間軸可以點選、拖動調整長度。
   - 字幕打字時就會顯示每秒字數；右側「輸出前檢查」用的是 kit 自己的規則，紅色項目修好才能輸出。
   - 選背景音樂分類。
4. **輸出影片**：完成後可以直接播放、看品質分數、複製 IG 文案、開啟檔案位置。
5. 看過沒問題就按「我看過了，可以發布」。

原始影片會被**複製**進素材資料夾，你原本的檔案不會被修改或刪除。

## 檔案放在哪裡

| 內容 | 位置 |
|---|---|
| 每支 Reels 的素材與成品 | `<素材資料夾>\videos\_INBOX\直式-vertical-Shorts-Reels\<編號>\` |
| 成品影片 | 上面資料夾裡的 `_out\current.mp4` |
| 背景音樂 | `<素材資料夾>\assets\bgm\<分類>\` |
| Reels 工作室的設定 | `%USERPROFILE%\.reels-studio\config.json` |

## 運作方式

- `reels_studio/` 是只用 Python 標準函式庫寫的本機伺服器，只接受本機（127.0.0.1）連線，
  會改動檔案的要求都要帶每次啟動時產生的 token。
- 不修改 kit 的任何檔案：介面產生和手寫一樣的 `_plan.py`，再呼叫 kit 的
  `shorts_autopilot.py scan / build`；輸出前檢查呼叫 kit 的 `gate_shorts`。
- 長片與 Editkin：Editkin 目前沒有官方安裝檔，先列在「環境檢查」的選用項目。

## 測試

```bash
# 需要 ffmpeg，以及一個已安裝 kit 的資料夾
python tests/ci_prepare.py ./ci-workspace
REELS_TEST_WORKSPACE=./ci-workspace python -m pytest tests -v
```

GitHub Actions 會在 Windows 與 Ubuntu 上用 App 自己的安裝程式裝好 kit、套件和字型，
再透過 API 跑完整的出片流程。
