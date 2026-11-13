# watchkit

`watchkit` 是一個輕量、零外部相依（僅需 Python 3.10+ 標準庫）的開源框架，專為「公開資料監控 → 自選清單比對 → 每日 HTML 報表產出」設計。

它具備自動快取、重試退避機制、狀態差異比對（Diff）以及深色模式自適應的單一 HTML 報表產出能力。

---

## 主要特色

- **零外部依賴**：完全基於 Python 標準庫（`urllib`, `dataclasses`, `html`, `json` 等）。
- **Watcher 協議**：只需約 40 行程式碼即可快速擴充全新的公開資料來源。
- **狀態差異追蹤**：比對每次執行結果，清楚標記新增（New）、變更（Changed）與移除（Removed）項目。
- **安全自包含報表**：產出單一 HTML 檔案，所有動態資料皆嚴格轉義，不載入任何外部 JavaScript，內建自適應深色模式（Dark Mode）。
- **簡潔通知介面**：內建 stdout 與檔案記錄兩種模式，不硬編碼任何憑證或第三方通訊軟體連線。

---

## 安裝方式

目前可直接透過 GitHub 進行安裝：

```bash
pip install git+https://github.com/fish0119freelancer/watchkit
```

> **說明**：PyPI 正式發布仍在規劃中（目前尚未發布至 PyPI），現階段請自 GitHub 安裝使用。

---

## 快速開始（離線示範）

在未安裝或離線環境下，可直接透過 Python 模組執行內建的離線測試資料：

### 1. 執行 CISA KEV 漏洞監控離線展示

```bash
# 建立範例自選清單
cat << 'EOF' > watchlist_kev.txt
Microsoft: Windows 11
Synology
EOF

# 執行監控並輸出 HTML 報表（若從原始碼目錄執行，可設定 PYTHONPATH=src）
PYTHONPATH=src python -m watchkit run kev \
  --offline tests/fixtures/kev_sample.json \
  --watchlist watchlist_kev.txt \
  --out kev_report.html \
  --state-dir .watchkit
```

### 2. 執行 CPSC 消費品召回離線展示

```bash
# 建立範例自選清單（支援關鍵字與產地）
cat << 'EOF' > watchlist_cpsc.txt
product: power bank | manufacturer: China
toy
EOF

# 執行監控
PYTHONPATH=src python -m watchkit run cpsc_recalls \
  --offline tests/fixtures/cpsc_sample.json \
  --watchlist watchlist_cpsc.txt \
  --out cpsc_report.html \
  --state-dir .watchkit
```

執行完成後，使用瀏覽器開啟 `kev_report.html` 或 `cpsc_report.html` 即可瀏覽報表。

---

## 如何在 40 行內撰寫全新的 Watcher

任何實作 `fetch`、`parse` 與 `match` 三個方法的類別均可作為 Watcher：

```python
import json
from pathlib import Path
from typing import Any
from watchkit.core import Hit, Item, Source

class SimpleJsonWatcher:
    name = "simple_feed"

    def __init__(self, url: str = "https://example.invalid/feed.json"):
        self.source = Source(url=url, cache_path=Path(".cache/feed.json"))

    def fetch(self, offline_path: Path | None = None) -> str:
        return self.source.fetch(offline_path=offline_path)

    def parse(self, raw: str) -> list[Item]:
        records = json.loads(raw)
        return [
            Item(
                id=str(row.get("id")),
                title=str(row.get("title")),
                date=str(row.get("date", "")),
                data=row,
            )
            for row in records
        ]

    def match(self, items: list[Item], watchlist: Any) -> list[Hit]:
        keywords = [k.casefold() for k in watchlist if isinstance(k, str)]
        hits = []
        for item in items:
            title_lower = item.title.casefold()
            for kw in keywords:
                if kw in title_lower:
                    hits.append(Hit(
                        item=item,
                        matched_rule=f"keyword: {kw}",
                        reasons=[f"標題包含關鍵字 '{kw}'"],
                    ))
                    break
        return hits
```

---

## 通知整合（Notifiers）

`watchkit` 遵循安全優先原則，核心程式碼不包含任何 SMTP、LINE、Telegram 等憑證或特定供應商實作。內建兩種方式：

1. `--notify stdout`（預設）：直接輸出執行摘要至標準輸出，適合配合 cron 或 CI/CD 管道捕捉。
2. `--notify file --notify-file alerts.txt`：將摘要附加至指定檔案。

若需將報表轉發至特定 Webhook 或通訊軟體，可使用環境變數外包腳本。例如：

```bash
# 執行 watchkit 產出報表
python -m watchkit run kev --watchlist wl.txt --out report.html

# 透過外部腳本傳送（由環境變數讀取 WEBHOOK_URL）
if [ -n "$WEBHOOK_URL" ]; then
  curl -X POST -H "Content-Type: application/json" \
    -d "{\"text\": \"watchkit 監控完成，請檢視 report.html\"}" \
    "$WEBHOOK_URL"
fi
```

---

## 資料來源使用條款宣告

- **CISA KEV Catalog**：由美國網路安全暨基礎設施安全局（CISA）維護之公有領域公開資料（U.S. Government Work）。
- **CPSC SaferProducts**：由美國消費品安全委員會（CPSC）提供。請遵守官方 API 存取頻率規範，並核實原始召回公告。

---

## 需要客製化 Watcher？（自動化顧問服務）

需要針對貴公司內部系統、專屬供應商公告或特定公開資料源客製化監控與報表整合？

- 如有任何問題或建議，請至 GitHub 儲存庫提出 [Issue](https://github.com/fish0119freelancer/watchkit/issues)。
- 若需客製化 Watcher 開發或自動化服務（custom watchers / automation services）：請參閱作者的 Fiverr 個人檔案（連結位於 [GitHub 個人檔案](https://github.com/fish0119freelancer)）。

---

## 授權條款

本專案採用 [MIT License](LICENSE) 授權。
