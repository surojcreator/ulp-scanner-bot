# ULP Merger & Error-Checker Telegram Bot

A high-performance Telegram bot built with **aiogram 3** (and optional **Telethon MTProto**) that stores forwarded combo files, merges them, deduplicates lines, deletes the original files to save server disk space, and validates the `url:user:password` format for errors.

---

## ⚡ Key Features

1. **File Storage & Batch Queue:**
   - Forward or upload multiple files (`.txt`, `.csv`, `.log`, or `.zip`).
   - Stores incoming files persistently per chat/user in `data/incoming/<chat_id>/`.
   - Real-time queue summary: file count, total size, file names.

2. **Streaming Merge & Fast Deduplication:**
   - Reads lines across all files in the batch without loading the entire dump into RAM.
   - 64-bit fingerprint hash set for high-speed single-pass deduplication.
   - Extracts and processes text files nested inside `.zip` archives automatically.

3. **Disk Space Auto-Cleanup:**
   - Once the merged & deduplicated file is written, the bot immediately deletes the original forwarded files from the server disk.

4. **Detailed `url:user:password` Error Checking:**
   - Verifies each unique record against the `url:user:password` schema:
     - Handles schemes (`http://`, `https://`, `ftp://`), URLs with custom ports (`:8080`), and passwords containing colons.
     - Supports alternative delimiters: `:` (colon), `|` (pipe), `;` (semicolon), or `\t` (tab).
     - Flags invalid URLs, missing usernames, empty passwords, null/binary corruption, or missing fields.
   - Produces two clean outputs:
     - `cleaned_ulp_<timestamp>.txt`: All valid records normalized to `url:user:password`.
     - `errors_ulp_<timestamp>.txt`: Every line that failed with line number and specific error reason.

5. **Large File Support (up to 2GB):**
   - Standard Bot API public server caps downloads at 20MB.
   - To handle big files:
     - **Option A (Self-hosted Bot API):** Set `TELEGRAM_API_SERVER=http://localhost:8081` in `.env` (2GB upload / unlimited download).
     - **Option B (Telethon MTProto):** Set `TELEGRAM_API_ID` & `TELEGRAM_API_HASH` in `.env` to download forwarded files up to 2GB directly through MTProto.

---

## 🚀 Setup & Installation

### 1. Requirements
Ensure Python 3.10+ is installed. All dependencies are in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 2. Configuration (`.env`)
Create a `.env` file from `.env.example`:
```env
# Required: Telegram Bot token from @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ

# (Optional) Local Bot API Server for >20MB files
# TELEGRAM_API_SERVER=http://localhost:8081

# (Optional) Telethon MTProto Client for >20MB downloads without local server
# TELEGRAM_API_ID=1234567
# TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
```

### 3. Run the Bot
```bash
python run.py
```

---

## 📱 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome screen and quick instructions |
| `/files` or `/queue` | View stored files currently queued in storage |
| `/merge` or `/clean` | Run the merge, deduplicate, delete sources, and check errors pipeline |
| `/clear` | Delete all queued files from the server |
| `/help` | Detailed syntax and delimiter guidance |

---

## 🧪 Testing

Run unit and integration tests:
```bash
python tests/test_validator.py
python tests/test_processor.py
```
Both test suites verify:
- Line parsing with edge-cases (ports, passwords with colons, different delimiters).
- End-to-end merging, deduplication, deletion of source files, error detection, and report generation.
