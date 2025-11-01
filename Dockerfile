# ----------------------------------------------------
# 階段 1: 建構階段 (Build Stage)
# 安裝編譯 PyNaCl 所需的系統依賴，並安裝 Python 函式庫
# ----------------------------------------------------
# 使用一個更完整的映像檔來進行建構
FROM python:3.12-slim as builder

# 設定環境變數，避免安裝過程中產生互動式提示
ENV DEBIAN_FRONTEND=noninteractive

# 安裝編譯 PyNaCl 所需的系統依賴：
# build-essential: 包含 C/C++ 編譯器 (gcc) 和 make 等工具
# libffi-dev: PyNaCl 的依賴
# libssl-dev: 確保 SSL/TLS 相關 Python 依賴可以正確編譯
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 將 requirements.txt 複製到工作目錄
# 假設您已在專案根目錄創建了 requirements.txt
COPY requirements.txt .
# 安裝 Python 依賴
RUN pip install --upgrade pip && \
    pip install -r requirements.txt --no-cache-dir && \
    pip install --upgrade yt-dlp


# ----------------------------------------------------
# 階段 2: 最終階段 (Final Stage)
# 使用最小化映像檔來執行程式，不包含建構工具
# ----------------------------------------------------
# 使用相同的 Python 輕量級映像檔，但這次不安裝編譯工具
FROM python:3.12-slim

# --- ✅ 新增：安裝 ffmpeg ---
# 設定環境變數，避免安裝過程中產生互動式提示
ENV DEBIAN_FRONTEND=noninteractive
# 安裝 ffmpeg (yt-dlp 會用到)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# --- ✅ 新增結束 ---

# 設定最終執行環境的工作目錄
WORKDIR /app

# 從建構階段複製已安裝的 Python 函式庫
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 複製您的專案程式碼
# 注意：這會將整個專案目錄複製到容器內
COPY . .

# 暴露的環境變數 (在 TrueNAS/Docker run 時必須傳入)
# 雖然不需要 EXPOSE 指令，但在註釋中提醒需要設定 ENV
# ENV DISCORD_TOKEN="<Your Token>"
# ENV CHANNEL_ID="<Your Channel ID>"

# 容器啟動時執行的預設指令
# 執行您的主程式檔案 bot.py
CMD ["python", "bot.py"]
