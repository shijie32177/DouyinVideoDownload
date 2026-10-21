# <img src="assets/douyin_icon.png" width="32" height="32" style="vertical-align:middle"/> Douyin Video Downloader

> A PyQt5 + DrissionPage desktop client that drives your local Chrome browser to capture Douyin (TikTok China) videos and download them **watermark-free**.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15%2B-green?logo=qt&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)

[中文文档](README.zh.md)

---

## ✨ Features

### 📁 My Favorites
- Browse collections by folder with thumbnail previews and video duration labels
- **Drag-and-drop** to reorder your favorite folders freely
- Real-time **search bar** with auto-complete to filter folders instantly
- One-click sync: refresh folder list / fetch video metadata / download entire folder
- Clear local cache to force a full re-fetch; multi-select and batch download

### 🎬 My Posts / My Likes
- Automatically syncs all videos you have published or liked after login
- Configurable sync limits per category (0 = unlimited) in the Settings panel

### 🔍 Discover Users
- Enter a UID (`MS4wLjABAAAAxxx`) or profile URL to look up any user
- Displays nickname, follower count, and total video count
- User list is persisted locally — no need to re-search on next launch
- Select all / batch download from any user's video grid

### 🔗 Parse Share Links
- Paste Douyin App share text (containing a `v.douyin.com` short link) to extract the direct download URL automatically
- **History** of parsed links is retained across sessions; one-click preview or add to queue
- Clear list at any time

### ⬇️ Download Center
- Unified task manager for all sources: Favorites / Posts / Likes / Discover / Parse
- **Title search** bar to filter the task list instantly
- Columns: title, author, progress, file size, source, date added
- Global controls: Start All / Pause All / Clear / Delete Selected
- Per-task controls: Download / Pause / Resume / Cancel with **resume-on-pause** support
- Custom download directory; click "Open" to reveal the folder in your file manager

### 📋 Global Log Panel
- Real-time log at the bottom of the window shows fetch progress and errors
- Click the **collapse / expand** arrow on the splitter handle to hide the log without losing content space
- Log auto-collapses when switching between tabs

### ⚙️ Settings
- **Themes**: Dark (default) / Midnight Blue / Minimal Green / Warm Sand — live preview on selection
- Maximum concurrent downloads (1–10, recommended: 3)
- Sync limits for My Posts and My Likes

---

## 📸 Screenshots

### My Favorites — Video Grid + Folder Search
![My Favorites](assets/Screenshot01.png)

### Discover Users — Profile Info + Video List
![Discover Users](assets/Screenshot02.png)

### Download Center — Multi-Source Task Management
![Download Center](assets/Screenshot03.png)

### Parse Share Links
![Parse](assets/Screenshot04.png)

---

## 🚀 Quick Start

### Requirements

- Python 3.8+
- Google Chrome (version compatible with DrissionPage)

### Install Dependencies

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install PyQt5 PyQtWebEngine requests DrissionPage
```

### Run

```bash
python app.py
```

---

## 📖 Usage Guide

### 1. First-time Login

Launch the app and switch to the **"My"** tab. Click **"Open Douyin"** to log in via the embedded browser. After a successful login, click **"Update Cookie"** — your session is saved locally and will be reused on the next launch.

### 2. Syncing Favorites

1. Click **"Sync List"** to fetch your folder directory
2. Click any folder on the left — the video grid appears on the right
3. Click **"Sync Videos"** to fetch all video metadata for that folder
4. Check the videos you want, then click **"Batch Download"**, or use the Download button on individual video cards

> **Tip:** Type in the search box on the left to filter folders in real time. Drag rows to reorder them.

### 3. Discovering Users

Go to the **"Discover"** tab, enter a UID or profile URL, and click **"Search / Add User"**. The app resolves the profile and syncs their videos for batch download.

### 4. Parsing Share Links

Go to the **"Parse"** tab and paste the text copied from the Douyin App share sheet (it contains a short link like `https://v.douyin.com/…`). Click **"Parse Video"** to extract the real direct URL. The result is added to the history list automatically.

### 5. Managing Downloads

Switch to the **"Download"** tab to see all queued tasks. Use the search bar to filter by title, global buttons for bulk control, or operate tasks individually.

---

## 🏗️ How It Works

```
Share short-link → follow redirect → extract aweme_id
         ↓
Official API  /aweme/v1/feed/  (no login required)
         ↓  fails
DrissionPage drives Chrome → intercept aweme/detail network request
         ↓
requests multi-threaded download  (watermark parameter stripped automatically)
```

**Local data paths:**

| Item | Path |
|------|------|
| Session cookie | `~/.douyin_tool_cookie` |
| Chrome profile | `~/.douyin_drission_profile` |
| Video metadata cache | `.cache/` (deletable to force re-fetch) |

---

## 📦 Project Structure

```
.
├── app.py              # Main application
├── analyze_dom.py      # Debug tool: inspect scroll containers on the favorites page
├── requirements.txt    # Python dependencies
├── assets/             # Icons and screenshots
└── videos/             # Default download directory
```

---

## ⚠️ Disclaimer

- This tool is intended for **personal learning and research only**. Please comply with Douyin's Terms of Service and respect copyright.
- Google Chrome must be installed locally and its version must be compatible with DrissionPage.
- Download speed depends on your network and Douyin's server-side rate limits.

---

## 📜 Changelog

### v1.2.0 (current)
- Switched core engine to DrissionPage — intercepts Chrome network requests to obtain real, watermark-free download URLs
- Added **Discover** tab: look up any user and download their videos
- Added **Parse** tab: one-paste share-link parsing with persistent history
- Favorites: drag-to-reorder and real-time keyword search with auto-complete
- Global log panel: collapsible/expandable with a single click; auto-hides on tab switch
- Download Center: title search filter
- 4 built-in themes (Dark / Midnight Blue / Minimal Green / Warm Sand) with live preview
- Cookie persistence — no re-login required after restart
- Settings panel: configurable concurrency and sync limits

### v1.1.0
- Added user profile video download
- Added user likes video download
- Accept both UID and URL as input

### v1.0.0
- Basic favorites scraping and download
- Task management (pause / resume / cancel)
- Dark theme UI
- Custom download directory

---

## 🤝 Contributing

Issues and Pull Requests are welcome.

## 📄 License

[MIT License](LICENSE)
