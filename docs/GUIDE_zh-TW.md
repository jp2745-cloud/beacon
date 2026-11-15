# Beacon 操作指南（給你們兩位）

Beacon 是「離線緊急應變助手」：按住空白鍵說出狀況，Bonsai 判斷該開哪一張安全卡，Argmax 把步驟一句一句唸給你聽。關掉 Wi-Fi 照樣運作。

這份文件照時間順序寫：今天在 Windows 做什麼、明天在 Mac 做什麼、影片怎麼錄、怎麼提交。

---

## 0. 先知道的三件事

1. **比賽規定作品必須在 Mac、關掉 Wi-Fi 的狀態下執行，而且 Argmax 只能在 Apple Silicon 上跑。** 所以 Windows 只能用來開發和測試 Bonsai 的部分，最後一定要到主辦方提供的 Mac 筆電上跑一次並錄影（技術簡報第 3 頁有寫這條路）。**請今天就在 Discord 問主辦方：筆電什麼時候可以借、上面有沒有裝好 Xcode。** 這是整件事最大的時間風險。
2. **我測過的**：路由邏輯（14 個自動測試）、介面（用瀏覽器實際操作並截圖檢查）、麥克風錄音到語音播放的完整流程、Swift 程式的語法與通訊協定（用 Linux 版 Swift 編譯器對照 Argmax SDK 的函式簽名檢查過）。
3. **我沒辦法測的**：真正的 Bonsai 模型（這邊下載不到權重）和真正的 Argmax 模型（需要 Mac）。所以 Bonsai 的提示詞是第一次碰到真模型，下面第 1 步的 `--check` 就是用來驗證它的，結果請貼回來給我看。

---

## 1. 今天：在 Windows 上把 Bonsai 跑起來（約 20–30 分鐘）

### 為什麼 LM Studio 載入失敗

Bonsai 2 是三元量化模型，需要執行引擎支援它特殊的權重格式。PrismML 的文件寫明：`PQ2_0` 和 `PTQ1_0` 這兩種檔案目前只有 PrismML 自己的 llama.cpp 分支能跑；只有 `Q2_0` 檔能在夠新的官方 llama.cpp 上跑。LM Studio 內建自己的引擎，版本不夠新或檔案格式不對就會載入失敗。最穩的做法是不要透過 LM Studio，直接用 PrismML 官方的啟動腳本。

如果你們的錯誤訊息跟這個原因對不上，請把錯誤訊息原文貼給我。

### 步驟

開 PowerShell：

```powershell
git clone https://github.com/PrismML-Eng/Bonsai-demo.git
cd Bonsai-demo
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:BONSAI_MODEL = "4B"
$env:BONSAI_THINKING = "0"
.\setup.ps1
.\scripts\start_llama_server.ps1
```

看到伺服器在 `http://localhost:8080` 啟動就成功了。這個視窗不要關。

電腦比較慢（沒有獨立顯卡）的話，把 `"4B"` 換成 `"2B"`。

### 驗證 Bonsai 跟 Beacon 接得上

另開一個視窗，進到 `beacon` 資料夾：

```powershell
python server.py --check
```

理想結果是四行 `[ OK ]`，而且兩個測試句分別開出 Severe bleeding 和 Lost with no signal。**請把這段輸出貼給我**，不管成功或失敗。

### 啟動 Beacon

```powershell
python server.py
```

瀏覽器會自動開 `http://127.0.0.1:8765`。右上角第二顆燈應該顯示「Bonsai 2 4B on this laptop」。

在 Windows 上，第三顆燈會顯示「Development voice, not Argmax」，這是正常的。此時可以用右下角打字測試。想用講的，先裝語音辨識替代品：

```powershell
pip install faster-whisper
```

裝完重開 `python server.py`，就能按住空白鍵說話（英文）。

### 今天要試的東西

照著第 4 節的影片腳本完整走一遍，確認 Bonsai 的回答合理。有任何怪回答，把你說的句子和它的回答貼給我，我調提示詞。

---

## 2. 把程式碼放上 GitHub（今天就做，5 分鐘）

1. 到 github.com 建一個新的 public repository，名字例如 `beacon`，不要勾任何初始化選項。
2. 在 `beacon` 資料夾裡：

```powershell
git init
git add .
git commit -m "Beacon: offline emergency companion"
git branch -M main
git remote add origin https://github.com/你的帳號/beacon.git
git push -u origin main
```

這樣明天在 Mac 上只要 `git clone` 就能拿到程式。

---

## 3. 明天：在主辦方的 Mac 上（預留 90 分鐘，順利的話約 40 分鐘）

需要：Apple Silicon Mac、macOS 15 以上、Xcode 16 以上、有網路（只有安裝時需要）。

**終端機視窗一（Bonsai）：**

```bash
git clone https://github.com/PrismML-Eng/Bonsai-demo.git
cd Bonsai-demo
BONSAI_MODEL=4B ./setup.sh
BONSAI_MODEL=4B BONSAI_THINKING=0 ./scripts/start_llama_server.sh
```

如果那台 Mac 的 LM Studio 已經能載入 Bonsai，也可以直接在 LM Studio 開啟 Local Server，Beacon 會自動找到它（連接埠 1234）。

**終端機視窗二（Beacon）：**

```bash
git clone https://github.com/你的帳號/beacon.git
cd beacon
bash start_mac.sh
```

第一次會做三件事，都需要網路：
- 編譯 Argmax 橋接程式（幾分鐘）
- 下載 Whisper `small.en` 語音辨識模型
- 下載 TTSKit 語音合成模型（約 1 GB）

等右上角第三顆燈變成「**Argmax WhisperKit and TTSKit**」，瀏覽器跳出麥克風權限時按允許。

**然後關掉 Wi-Fi。** 第一顆燈會變成黃色的「Wi-Fi off. Running on this laptop」。建議關掉 Wi-Fi 後把兩個終端機的程式都停掉再重開一次，確認完全離線也能啟動，再開始錄影。

### 出問題時

| 狀況 | 處理 |
|---|---|
| `swift build` 編譯錯誤 | 把錯誤訊息整段貼給我，我改程式。這是我這邊無法實機驗證的部分。 |
| 編譯一直修不好，時間快到了 | 備案：`git clone https://github.com/argmaxinc/argmax-oss-swift.git && cd argmax-oss-swift && swift build -c release --product argmax-cli`，然後用 `BEACON_SPEECH=argmax-cli BEACON_ARGMAX_CLI=那個資料夾/.build/release/argmax-cli python3 server.py` 啟動。一樣是 Argmax，只是每句話會慢幾秒。 |
| 第三顆燈顯示「Argmax WhisperKit, system voice」 | TTSKit 沒載入成功（通常是 macOS 版本低於 15）。語音辨識仍然是 Argmax，可以照常 Demo。 |
| 第三顆燈一直是「Argmax is loading models」 | 第一次在下載模型，滑鼠移到燈上可以看進度訊息。 |
| 第二顆燈紅色「Bonsai is not running」 | 視窗一的伺服器沒開，或開在別的連接埠。可設定 `BEACON_LLM_URL=http://127.0.0.1:連接埠/v1`。 |
| Bonsai 回應很慢 | 改用 2B：`BONSAI_MODEL=2B`。 |
| 按空白鍵沒反應 | 先用滑鼠點一下頁面空白處；確認瀏覽器網址列的麥克風權限是允許。 |
| M5 Mac 啟動 Bonsai 出現 Metal 錯誤 | 在啟動指令前加 `GGML_METAL_TENSOR_DISABLE=1`（PrismML 的 FAQ 有寫）。 |

---

## 4. 兩分鐘影片腳本

錄影前：先按右上「Start over」清空紀錄；瀏覽器全螢幕；用 QuickTime 的螢幕錄製，音訊來源選內建麥克風，喇叭音量開大，這樣你的聲音和 Beacon 從喇叭播出的聲音都會被麥克風收進去。英文台詞照唸即可。

| 時間 | 畫面 | 你說的話（英文） |
|---|---|---|
| 0:00–0:12 | 點選單列把 Wi-Fi 關掉，Beacon 第一顆燈變黃 | 旁白："Out on a trail there's no signal. In an earthquake the network goes down. That's exactly when cloud AI stops working. Beacon doesn't need the cloud." |
| 0:12–0:35 | 按住空白鍵說話，黃色卡片出現，Beacon 開始唸 | 對 Beacon 說："My friend slipped on the rocks and cut his leg, it won't stop bleeding." |
| 0:35–0:48 | 步驟前進，計時器啟動 | "Next." 等它唸完，再說 "Start the timer." |
| 0:48–1:05 | Bonsai 根據卡片內容回答 | "Should I take the cloth off to check if it stopped?" |
| 1:05–1:25 | CPR 卡片瞬間出現，按幾次 Next 到第四步，節拍器開始響 | "He just collapsed, he's not breathing!" 然後 "Next." 三次 |
| 1:25–1:42 | 按「Write handoff report」，再按「Read aloud」 | 旁白："When help arrives, Bonsai turns the incident log into a handoff report." |
| 1:42–1:55 | 滑鼠指向右下「Work done on this laptop」和右上三顆燈 | 旁白："Argmax WhisperKit hears you. Bonsai 2 decides. Argmax TTSKit speaks. And simple commands like 'next' never wake the model at all." |
| 1:55–2:00 | 回到首頁大標題 | 旁白："Beacon. It works when the internet doesn't." |

總長請控制在 2 分鐘內，超過會不符規定。寧可刪掉計時器那一段。

---

## 5. 如果進決賽：4 分鐘現場 Demo 的重點

1. **一句話開場**：emergencies are when you lose the internet，所以這個 AI 應用「必須」是本機的，不是「剛好可以」本機。這正好回答簡報第 16 頁那個問題。
2. **現場關 Wi-Fi，再開始講話。**
3. **三個技術亮點**（評審是 PrismML、Argmax、LM Studio 的創辦人）：
   - 模型不寫急救步驟，只負責理解、選卡、回答卡片內的問題。小模型做選擇題很可靠，做開放式醫療建議很危險。
   - Right-sized inference：「next」這種指令用規則處理，不呼叫模型；「not breathing」直接開 CPR 卡，不等模型生成。畫面右下角有實際計數。
   - Argmax 的兩個模型常駐在一個 Swift 小程式裡，Python 透過標準輸入輸出跟它溝通。
4. **可以報名的獎項**：Main Track；也可以提 Accessibility（全程語音、免用手）和 Sustainability（只在需要時才呼叫模型）。

---

## 6. 提交到 #submissions 的文字

```
Team: （你們兩位的名字）

Beacon: a voice-first emergency companion that runs with Wi-Fi off. Argmax WhisperKit
hears what's happening, Bonsai 2 picks a vetted safety card and answers follow-up
questions from it, and Argmax TTSKit talks you through it step by step.

Code: https://github.com/你的帳號/beacon
Video: （影片連結）
```

截止時間是週日中午 12:00 整，請至少提前 30 分鐘送出。

---

## 7. 兩個要誠實面對的地方

- 這份程式是 AI（Claude）協助寫的，README 的 Credits 有註明。「Locally Made」子獎項要求全程用本機 AI 寫程式，這個作品不符合，請不要報那一項。
- 安全卡的內容是依照紅十字會、美國心臟協會、CDC、Ready.gov 等公開指引寫的，但沒有經過醫療專業人員審核。介面和 README 都有標示這是展示用內容。被評審問到時照實回答就好，這反而是加分的設計說明。
