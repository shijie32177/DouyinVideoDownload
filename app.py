import sys
import re
import json
import os
import time
import requests
import subprocess
from datetime import datetime
from urllib.parse import urlparse

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu-compositing --disable-software-rasterizer"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"

from PyQt5.QtCore import (Qt, QObject, QThread, pyqtSignal, QTimer, QByteArray, QSize,
                          QStringListModel, QSortFilterProxyModel)
from PyQt5.QtGui import QPixmap, QColor, QPainter, QBrush, QPen
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QTextEdit,
    QPushButton, QLabel, QLineEdit, QHBoxLayout, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QTabWidget, QStyle, QAbstractItemView, QFrame,
    QSplitter, QListWidget, QListWidgetItem, QScrollArea, QGridLayout,
    QCheckBox, QMenu, QDialog, QSlider, QSpinBox, QComboBox, QSizePolicy,
    QCompleter, QGroupBox,
)

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)

app = QApplication(sys.argv)

from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile

_profile_path = os.path.join(os.path.expanduser("~"), ".douyin_tool_profile")
os.makedirs(_profile_path, exist_ok=True)
profile = QWebEngineProfile("douyin_tool", app)
profile.setPersistentStoragePath(_profile_path)
profile.setCachePath(os.path.join(_profile_path, "cache"))
profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
profile.setHttpUserAgent(
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# ─── 路径常量 ─────────────────────────────────────────────────────────────────
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR    = os.path.join(_PROJECT_DIR, ".cache", "favorites")
DL_CACHE     = os.path.join(_PROJECT_DIR, ".cache", "downloads.json")
COOKIE_FILE  = os.path.join(os.path.expanduser("~"), ".douyin_tool_cookie")
COOKIE_META  = os.path.join(os.path.expanduser("~"), ".douyin_tool_cookie_meta.json")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DL_CACHE), exist_ok=True)
SELF_CACHE_DIR  = os.path.join(_PROJECT_DIR, ".cache", "self")
USERS_CACHE_DIR = os.path.join(_PROJECT_DIR, ".cache", "users")
PARSE_CACHE     = os.path.join(_PROJECT_DIR, ".cache", "parse_history.json")
os.makedirs(SELF_CACHE_DIR, exist_ok=True)
os.makedirs(USERS_CACHE_DIR, exist_ok=True)

# ─── 解析历史 ──────────────────────────────────────────────────────────────────
def load_parse_history():
    if not os.path.exists(PARSE_CACHE):
        return []
    try:
        with open(PARSE_CACHE, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        return []
    cutoff = time.time() - 90 * 86400
    return [r for r in records if r.get("parsed_at", 0) >= cutoff]

def save_parse_history(records):
    cutoff = time.time() - 90 * 86400
    records = [r for r in records if r.get("parsed_at", 0) >= cutoff]
    os.makedirs(os.path.dirname(PARSE_CACHE), exist_ok=True)
    with open(PARSE_CACHE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

# ─── Cookie 持久化 ────────────────────────────────────────────────────────────
def save_cookie(s):
    with open(COOKIE_FILE, "w", encoding="utf-8") as f: f.write(s)
    with open(COOKIE_META, "w", encoding="utf-8") as f:
        json.dump({"saved_at": time.time()}, f)

def load_cookie():
    if not os.path.exists(COOKIE_FILE): return "", 0
    with open(COOKIE_FILE, "r", encoding="utf-8") as f: c = f.read().strip()
    ts = 0
    if os.path.exists(COOKIE_META):
        try:
            with open(COOKIE_META, "r", encoding="utf-8") as f:
                ts = json.load(f).get("saved_at", 0)
        except Exception: pass
    return c, ts

# ─── 收藏夹缓存 ───────────────────────────────────────────────────────────────
def _idx_path(): return os.path.join(CACHE_DIR, "index.json")

def load_folder_index():
    p = _idx_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    return []

def save_folder_index(folders):
    with open(_idx_path(), "w", encoding="utf-8") as f:
        json.dump(folders, f, ensure_ascii=False, indent=2)

def save_folder_cache(folder_id, folder_name, videos):
    ts = time.time()
    with open(os.path.join(CACHE_DIR, f"{folder_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"id": folder_id, "name": folder_name, "synced_at": ts, "videos": videos},
                  f, ensure_ascii=False, indent=2)
    idx = load_folder_index()
    for item in idx:
        if item["id"] == folder_id:
            item.update({"name": folder_name, "count": len(videos), "synced_at": ts}); break
    else:
        idx.append({"id": folder_id, "name": folder_name, "count": len(videos), "synced_at": ts})
    save_folder_index(idx)

def load_folder_cache(folder_id):
    p = os.path.join(CACHE_DIR, f"{folder_id}.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    return None

def load_self_cache(mode):
    p = os.path.join(SELF_CACHE_DIR, f"{mode}.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_self_cache(mode, videos):
    p = os.path.join(SELF_CACHE_DIR, f"{mode}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "synced_at": time.time(), "videos": videos},
                  f, ensure_ascii=False, indent=2)

def load_user_cache(uid):
    p = os.path.join(USERS_CACHE_DIR, f"{uid}_info.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_user_cache(uid, info):
    p = os.path.join(USERS_CACHE_DIR, f"{uid}_info.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

def load_user_videos_cache(uid, mode):
    p = os.path.join(USERS_CACHE_DIR, f"{uid}_{mode}.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_user_videos_cache(uid, mode, videos):
    p = os.path.join(USERS_CACHE_DIR, f"{uid}_{mode}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"uid": uid, "mode": mode, "synced_at": time.time(), "videos": videos},
                  f, ensure_ascii=False, indent=2)

def load_users_index():
    p = os.path.join(USERS_CACHE_DIR, "index.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_users_index(users):
    p = os.path.join(USERS_CACHE_DIR, "index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# ─── 下载记录持久化 ───────────────────────────────────────────────────────────
def load_dl_records():
    if os.path.exists(DL_CACHE):
        try:
            with open(DL_CACHE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return []

def save_dl_records(records):
    with open(DL_CACHE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

# 全局下载记录字典：tid → {task_id, title, url, aweme_id, status, local_path, added_at}
_dl_records: dict = {}

def _update_dl_record(tid, **kwargs):
    if tid not in _dl_records:
        _dl_records[tid] = {"task_id": tid, "title": "", "url": "", "aweme_id": "",
                            "status": "等待中", "local_path": "", "added_at": time.time()}
    _dl_records[tid].update(kwargs)
    save_dl_records(list(_dl_records.values()))

# ─── 本地文件检测 ─────────────────────────────────────────────────────────────
def get_local_video_path(aweme_id, save_dir):
    if not os.path.isdir(save_dir): return None
    needle = str(aweme_id)[:8]
    for fname in os.listdir(save_dir):
        if needle in fname and fname.endswith(".mp4"):
            return os.path.join(save_dir, fname)
    return None

# ─── 样式 ─────────────────────────────────────────────────────────────────────
STYLE = """
QWidget { background:#2b2b2b; color:#dcdcdc;
  font-family:"Microsoft YaHei",sans-serif;
  font-size:12pt; font-weight:500; }
QMainWindow { border:1px solid #3c3c3c; }
QTabWidget::pane { border:1px solid #3c3c3c; border-top:none; padding:8px; }
QTabBar::tab { background:#2b2b2b; border:1px solid #3c3c3c; border-bottom:none;
  padding:9px 22px; margin-right:2px; border-top-left-radius:5px; border-top-right-radius:5px; }
QTabBar::tab:selected { background:#3c3c3c; color:#00aaff; }
QTabBar::tab:!selected:hover { background:#353535; }
QPushButton { background:#4a5668; border:1px solid #5a5a5a; padding:7px 14px;
  border-radius:5px; min-width:60px; }
QPushButton:hover { background:#5a6678; border-color:#7a8898; }
QPushButton:pressed { background:#3a4658; border-color:#4a5668; }
QPushButton:disabled { background:#444; color:#777; border-color:#555; }
QPushButton#ctrl { background:transparent; border:1px solid #5a5a5a; }
QPushButton#ctrl:hover { border-color:#00aaff; color:#00aaff; }
QLineEdit { background:#3c3c3c; border:1px solid #555; border-radius:5px; padding:7px;
  selection-background-color:#007acc; }
QLineEdit:focus { border-color:#007acc; }
QTextEdit { background:#252526; border:1px solid #4f4f4f; }
QLabel { background:transparent; }
QProgressBar { border:1px solid #555; border-radius:5px; text-align:center;
  background:#3c3c3c; height:18px; }
QProgressBar::chunk { background:#007acc; border-radius:4px; }
QTableWidget { background:#2b2b2b; gridline-color:#3c3c3c; border:1px solid #3c3c3c;
  alternate-background-color:#313131; selection-background-color:#007acc; }
QTableWidget::item { padding:6px; border:none; }
QHeaderView::section { background:#3c3c3c; padding:6px; border:1px solid #2b2b2b; }
QListWidget { background:#252526; border:1px solid #3c3c3c; outline:none; }
QListWidget::item { padding:9px 8px; border-bottom:1px solid #333; }
QListWidget::item:selected { background:#007acc; color:white; }
QListWidget::item:hover:!selected { background:#333; }
QScrollBar:vertical { border:none; background:#2b2b2b; width:10px; border-radius:4px; }
QScrollBar::handle:vertical { background:#4a4a4a; min-height:20px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#5a5a5a; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { border:none; background:#2b2b2b; height:10px; border-radius:4px; }
QScrollBar::handle:horizontal { background:#4a4a4a; min-width:20px; border-radius:4px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QMessageBox { background:#2e2f30; }
QComboBox { background:#3c3c3c; border:1px solid #555; border-radius:5px; padding:5px 8px; }
QComboBox:hover { border-color:#7a8898; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#3c3c3c; selection-background-color:#007acc; }
QFrame#card { background:#323232; border:1px solid #444; border-radius:6px; }
QFrame#card:hover { border-color:#007acc; }
QFrame#discInfoCard { background:#252526; border:1px solid #3c3c3c; border-radius:8px; }
#discName      { font-size:18pt; font-weight:bold; }
#discSig       { font-size:12pt; color:#c0c0c0; font-family:"Microsoft YaHei","Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif; }
#discStats     { font-size:13pt; font-weight:bold; color:#7cb8ff; }
#userListSub   { color:#b0b0b0; }
#topTabs QTabBar::tab { font-size:11pt; font-weight:bold; min-height:34px; padding:6px 20px; }
#topTabs QTabBar::tab:selected { border-bottom:3px solid #007acc; }
#myTabs QTabBar::tab { font-size:11pt; padding:4px 14px; }
"""

# ─── 主题定义 ─────────────────────────────────────────────────────────────────
THEMES = {
    "深色 (默认)": STYLE,
    "午夜蓝": """
QWidget { background:#1a1e2e; color:#cdd6f4;
  font-family:"Microsoft YaHei",sans-serif;
  font-size:12pt; font-weight:500; }
QMainWindow { border:1px solid #313244; }
QTabWidget::pane { border:1px solid #313244; border-top:none; padding:8px; }
QTabBar::tab { background:#1a1e2e; border:1px solid #313244; border-bottom:none;
  padding:9px 22px; margin-right:2px; border-top-left-radius:5px; border-top-right-radius:5px; }
QTabBar::tab:selected { background:#313244; color:#89b4fa; }
QTabBar::tab:!selected:hover { background:#242638; }
QPushButton { background:#313244; border:1px solid #45475a; padding:7px 14px;
  border-radius:5px; min-width:60px; }
QPushButton:hover { background:#45475a; border-color:#6c7086; }
QPushButton:pressed { background:#1a1e2e; border-color:#313244; }
QPushButton:disabled { background:#2a2d3e; color:#585b70; border-color:#313244; }
QLineEdit { background:#313244; border:1px solid #45475a; border-radius:5px; padding:7px;
  selection-background-color:#89b4fa; }
QLineEdit:focus { border-color:#89b4fa; }
QTextEdit { background:#181825; border:1px solid #45475a; }
QLabel { background:transparent; }
QProgressBar { border:1px solid #45475a; border-radius:5px; text-align:center;
  background:#313244; height:18px; }
QProgressBar::chunk { background:#89b4fa; border-radius:4px; }
QTableWidget { background:#1a1e2e; gridline-color:#313244; border:1px solid #313244;
  alternate-background-color:#1e2235; selection-background-color:#89b4fa; }
QTableWidget::item { padding:6px; border:none; }
QHeaderView::section { background:#313244; padding:6px; border:1px solid #1a1e2e; }
QListWidget { background:#181825; border:1px solid #313244; outline:none; }
QListWidget::item { padding:9px 8px; border-bottom:1px solid #2a2d3e; }
QListWidget::item:selected { background:#89b4fa; color:#1a1e2e; }
QListWidget::item:hover:!selected { background:#242638; }
QScrollBar:vertical { border:none; background:#1a1e2e; width:10px; border-radius:4px; }
QScrollBar::handle:vertical { background:#45475a; min-height:20px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#585b70; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { border:none; background:#1a1e2e; height:10px; border-radius:4px; }
QScrollBar::handle:horizontal { background:#45475a; min-width:20px; border-radius:4px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QMessageBox { background:#1e2235; }
QComboBox { background:#313244; border:1px solid #45475a; border-radius:5px; padding:5px 8px; }
QComboBox:hover { border-color:#6c7086; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#313244; selection-background-color:#89b4fa; }
QFrame#card { background:#242638; border:1px solid #45475a; border-radius:6px; }
QFrame#card:hover { border-color:#89b4fa; }
QFrame#discInfoCard { background:#181825; border:1px solid #313244; border-radius:8px; }
#discName      { font-size:18pt; font-weight:bold; }
#discSig       { font-size:12pt; color:#b0b8d8; font-family:"Microsoft YaHei","Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif; }
#discStats     { font-size:13pt; font-weight:bold; color:#89b4fa; }
#userListSub   { color:#a0a8c0; }
#topTabs QTabBar::tab { font-size:11pt; font-weight:bold; min-height:34px; padding:6px 20px; }
#topTabs QTabBar::tab:selected { border-bottom:3px solid #89b4fa; }
#myTabs QTabBar::tab { font-size:11pt; padding:4px 14px; }
""",
    "翠绿极简": """
QWidget { background:#0d1117; color:#e6edf3;
  font-family:"Microsoft YaHei",sans-serif;
  font-size:12pt; font-weight:500; }
QMainWindow { border:1px solid #21262d; }
QTabWidget::pane { border:1px solid #21262d; border-top:none; padding:8px; }
QTabBar::tab { background:#0d1117; border:1px solid #21262d; border-bottom:none;
  padding:9px 22px; margin-right:2px; border-top-left-radius:5px; border-top-right-radius:5px; }
QTabBar::tab:selected { background:#161b22; color:#3fb950; }
QTabBar::tab:!selected:hover { background:#131820; }
QPushButton { background:#21262d; border:1px solid #30363d; padding:7px 14px;
  border-radius:5px; min-width:60px; }
QPushButton:hover { background:#30363d; border-color:#484f58; }
QPushButton:pressed { background:#0d1117; border-color:#21262d; }
QPushButton:disabled { background:#1a1f26; color:#484f58; border-color:#21262d; }
QLineEdit { background:#161b22; border:1px solid #30363d; border-radius:5px; padding:7px;
  selection-background-color:#3fb950; }
QLineEdit:focus { border-color:#3fb950; }
QTextEdit { background:#010409; border:1px solid #30363d; }
QLabel { background:transparent; }
QProgressBar { border:1px solid #30363d; border-radius:5px; text-align:center;
  background:#161b22; height:18px; }
QProgressBar::chunk { background:#3fb950; border-radius:4px; }
QTableWidget { background:#0d1117; gridline-color:#21262d; border:1px solid #21262d;
  alternate-background-color:#111820; selection-background-color:#3fb950; }
QTableWidget::item { padding:6px; border:none; }
QHeaderView::section { background:#161b22; padding:6px; border:1px solid #0d1117; }
QListWidget { background:#010409; border:1px solid #21262d; outline:none; }
QListWidget::item { padding:9px 8px; border-bottom:1px solid #1a1f26; }
QListWidget::item:selected { background:#3fb950; color:#0d1117; }
QListWidget::item:hover:!selected { background:#131820; }
QScrollBar:vertical { border:none; background:#0d1117; width:10px; border-radius:4px; }
QScrollBar::handle:vertical { background:#30363d; min-height:20px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#484f58; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { border:none; background:#0d1117; height:10px; border-radius:4px; }
QScrollBar::handle:horizontal { background:#30363d; min-width:20px; border-radius:4px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QMessageBox { background:#161b22; }
QComboBox { background:#161b22; border:1px solid #30363d; border-radius:5px; padding:5px 8px; }
QComboBox:hover { border-color:#484f58; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#161b22; selection-background-color:#3fb950; }
QFrame#card { background:#161b22; border:1px solid #21262d; border-radius:6px; }
QFrame#card:hover { border-color:#3fb950; }
QFrame#discInfoCard { background:#0d1117; border:1px solid #21262d; border-radius:8px; }
#discName      { font-size:18pt; font-weight:bold; }
#discSig       { font-size:12pt; color:#b4bcc8; font-family:"Microsoft YaHei","Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif; }
#discStats     { font-size:13pt; font-weight:bold; color:#3fb950; }
#userListSub   { color:#aab4bc; }
#topTabs QTabBar::tab { font-size:11pt; font-weight:bold; min-height:34px; padding:6px 20px; }
#topTabs QTabBar::tab:selected { border-bottom:3px solid #3fb950; }
#myTabs QTabBar::tab { font-size:11pt; padding:4px 14px; }
""",
    "暖沙浅色": """
QWidget { background:#faf8f5; color:#2d2d2d;
  font-family:"Microsoft YaHei",sans-serif;
  font-size:12pt; font-weight:500; }
QMainWindow { border:1px solid #d4c9bc; }
QTabWidget::pane { border:1px solid #d4c9bc; border-top:none; padding:8px; }
QTabBar::tab { background:#faf8f5; border:1px solid #d4c9bc; border-bottom:none;
  padding:9px 22px; margin-right:2px; border-top-left-radius:5px; border-top-right-radius:5px; }
QTabBar::tab:selected { background:#fff; color:#c0642a; }
QTabBar::tab:!selected:hover { background:#f4f0ec; }
QPushButton { background:#e8e0d8; border:1px solid #c8bdb2; padding:7px 14px;
  border-radius:5px; min-width:60px; color:#2d2d2d; }
QPushButton:hover { background:#ddd5cc; border-color:#a89a8e; }
QPushButton:pressed { background:#ccc3ba; border-color:#998b80; }
QPushButton:disabled { background:#ece8e3; color:#a0998f; border-color:#d4c9bc; }
QLineEdit { background:#fff; border:1px solid #c8bdb2; border-radius:5px; padding:7px;
  color:#2d2d2d; selection-background-color:#c0642a; selection-color:#fff; }
QLineEdit:focus { border-color:#c0642a; }
QTextEdit { background:#fff; border:1px solid #c8bdb2; color:#2d2d2d; }
QLabel { background:transparent; color:#2d2d2d; }
QProgressBar { border:1px solid #c8bdb2; border-radius:5px; text-align:center;
  background:#e8e0d8; height:18px; color:#2d2d2d; }
QProgressBar::chunk { background:#c0642a; border-radius:4px; }
QTableWidget { background:#faf8f5; gridline-color:#d4c9bc; border:1px solid #d4c9bc;
  alternate-background-color:#f4f0ec; selection-background-color:#c0642a;
  selection-color:#fff; color:#2d2d2d; }
QTableWidget::item { padding:6px; border:none; color:#2d2d2d; }
QHeaderView::section { background:#ece8e3; padding:6px; border:1px solid #faf8f5; color:#2d2d2d; }
QListWidget { background:#fff; border:1px solid #d4c9bc; outline:none; }
QListWidget::item { padding:9px 8px; border-bottom:1px solid #e8e0d8; color:#2d2d2d; }
QListWidget::item:selected { background:#c0642a; color:#fff; }
QListWidget::item:hover:!selected { background:#f4f0ec; }
QScrollBar:vertical { border:none; background:#faf8f5; width:10px; border-radius:4px; }
QScrollBar::handle:vertical { background:#c8bdb2; min-height:20px; border-radius:4px; }
QScrollBar::handle:vertical:hover { background:#b0a49a; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { border:none; background:#faf8f5; height:10px; border-radius:4px; }
QScrollBar::handle:horizontal { background:#c8bdb2; min-width:20px; border-radius:4px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QMessageBox { background:#fff; }
QComboBox { background:#fff; border:1px solid #c8bdb2; border-radius:5px; padding:5px 8px; color:#2d2d2d; }
QComboBox:hover { border-color:#a89a8e; }
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#fff; selection-background-color:#c0642a; color:#2d2d2d; }
QFrame#card { background:#fff; border:1px solid #d4c9bc; border-radius:6px; }
QFrame#card:hover { border-color:#c0642a; }
QFrame#discInfoCard { background:#f4f0ec; border:1px solid #d4c9bc; border-radius:8px; }
#discName      { font-size:18pt; font-weight:bold; color:#2d2d2d; }
#discSig       { font-size:12pt; color:#4a4040; font-family:"Microsoft YaHei","Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif; }
#discStats     { font-size:13pt; font-weight:bold; color:#c0642a; }
#userListSub   { color:#5a5050; }
#topTabs QTabBar::tab { font-size:11pt; font-weight:bold; min-height:34px; padding:6px 20px; }
#topTabs QTabBar::tab:selected { border-bottom:3px solid #c0642a; }
#myTabs QTabBar::tab { font-size:11pt; padding:4px 14px; }
""",
}

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "settings.json")

def _load_app_settings():
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_app_settings(data: dict):
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 日志面板容器（带右下角折叠角标） ────────────────────────────────────────
class _LogSplitterContainer(QWidget):
    toggle_requested = pyqtSignal()

    def __init__(self, splitter, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(splitter)

        self._btn = QPushButton("☰", self)
        self._btn.setFixedSize(32, 24)
        self._btn.setToolTip("折叠/展开日志面板")
        self._btn.setStyleSheet(
            "QPushButton{background:rgba(50,50,50,210);color:#bbb;border:1px solid #666;"
            "border-radius:4px;font-size:14pt;font-weight:bold;padding:0px;}"
            "QPushButton:hover{background:rgba(80,80,80,230);color:#fff;border-color:#999;}"
            "QPushButton:pressed{background:rgba(25,25,25,210);}")
        self._btn.clicked.connect(self.toggle_requested)
        self._btn.raise_()

    def update_icon(self, expanded: bool):
        self._btn.setText("☰" if expanded else "▤")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        bw, bh = self._btn.width(), self._btn.height()
        self._btn.move(w - bw - 4, h - bh - 4)
        self._btn.raise_()


# ─── 收藏夹列表项 Widget ──────────────────────────────────────────────────────
class FolderItemWidget(QWidget):
    def __init__(self, folder_meta, parent=None):
        super().__init__(parent)
        self._fid = folder_meta["id"]
        is_default = (self._fid == "default")
        is_deleted = bool(folder_meta.get("deleted"))

        lay = QVBoxLayout(self)
        if is_default:
            lay.setContentsMargins(12, 10, 10, 10)
        else:
            lay.setContentsMargins(14, 7, 10, 7)
        lay.setSpacing(3)

        name = folder_meta.get("name", "")
        count = folder_meta.get("count", 0)
        synced_at = folder_meta.get("synced_at")
        ts = datetime.fromtimestamp(synced_at).strftime("%m/%d %H:%M") if synced_at else "未同步"

        if is_default:
            # 默认收藏：icon + 加粗大字
            name_row = QHBoxLayout(); name_row.setSpacing(6); name_row.setContentsMargins(0,0,0,0)
            icon_lbl = QLabel("★")
            icon_lbl.setStyleSheet("color:#ffd54f;font-size:15pt;background:transparent;")
            icon_lbl.setFixedWidth(22)
            self.name_lbl = QLabel(name)
            self.name_lbl.setWordWrap(True)
            self.name_lbl.setStyleSheet(
                "color:#ffffff;font-size:14pt;font-weight:700;background:transparent;")
            name_row.addWidget(icon_lbl)
            name_row.addWidget(self.name_lbl, 1)
            lay.addLayout(name_row)
        else:
            name_row = QHBoxLayout(); name_row.setSpacing(6); name_row.setContentsMargins(0,0,0,0)
            self.name_lbl = QLabel(name)
            self.name_lbl.setWordWrap(True)
            name_color = "#888" if is_deleted else "#dcdcdc"
            self.name_lbl.setStyleSheet(
                f"color:{name_color};font-size:13pt;font-weight:700;background:transparent;")
            name_row.addWidget(self.name_lbl, 1)
            if is_deleted:
                del_lbl = QLabel("已删除")
                del_lbl.setStyleSheet(
                    "color:#ff6b6b;font-size:9pt;font-weight:600;background:#3a1f1f;"
                    "border:1px solid #7a2f2f;border-radius:3px;padding:0 4px;")
                del_lbl.setFixedHeight(18)
                name_row.addWidget(del_lbl)
            lay.addLayout(name_row)

        self._meta_lbl = QLabel(f"{count} 个视频  ·  {ts}")
        meta_color = "#666" if is_deleted else "#bbb"
        self._meta_lbl.setStyleSheet(f"color:{meta_color};font-size:10pt;background:transparent;")
        lay.addWidget(self._meta_lbl)

    def set_selected(self, selected: bool):
        if selected:
            self._meta_lbl.setStyleSheet("color:#eee;font-size:10pt;background:transparent;")
        else:
            self._meta_lbl.setStyleSheet("color:#bbb;font-size:10pt;background:transparent;")

    def sizeHint(self):
        return QSize(200, 72 if self._fid == "default" else 62)


# ─── 封面异步加载 ─────────────────────────────────────────────────────────────
# 全局集合持有所有活跃 CoverLoader / worker+thread 引用，防止 Python GC 在线程完成前提前销毁对象
_active_loaders: set = set()

class CoverLoader(QThread):
    loaded = pyqtSignal(str, QPixmap)

    def __init__(self, aweme_id, url):
        super().__init__()
        self.aweme_id = aweme_id
        self.url = url
        _active_loaders.add(self)
        # 线程结束后从全局集合移除，让 Python GC 可以安全回收
        self.finished.connect(lambda: _active_loaders.discard(self))

    def run(self):
        try:
            r = requests.get(self.url, timeout=5,
                             headers={"Referer":"https://www.douyin.com/","User-Agent":"Mozilla/5.0"})
            if self.isInterruptionRequested(): return
            if r.status_code == 200:
                pix = QPixmap(); pix.loadFromData(QByteArray(r.content))
                if not pix.isNull() and not self.isInterruptionRequested():
                    self.loaded.emit(self.aweme_id, pix)
        except Exception: pass

# ─── 视频卡片 ─────────────────────────────────────────────────────────────────
class VideoCard(QFrame):
    download_requested    = pyqtSignal(dict)
    preview_requested     = pyqtSignal(str)
    remove_from_dl_requested = pyqtSignal(str)  # aweme_id
    delete_local_requested   = pyqtSignal(str)  # aweme_id

    W, H, CW, CH = 160, 268, 152, 185

    def __init__(self, video_meta, save_dir, parent=None):
        super().__init__(parent)
        self.video_meta = video_meta
        self.save_dir   = save_dir
        self._local_path = None
        self._dl_status  = ""
        self.setObjectName("card")
        self.setFixedSize(self.W, self.H)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 6)
        lay.setSpacing(4)

        # checkbox overlay（绝对定位在封面左上角）
        self._chk = QCheckBox(self)
        self._chk.setStyleSheet(
            "QCheckBox{background:transparent;}"
            "QCheckBox::indicator{width:18px;height:18px;border-radius:4px;"
            "border:2px solid #888;background:rgba(0,0,0,120);}"
            "QCheckBox::indicator:checked{background:#007acc;border-color:#007acc;}"
        )
        self._chk.move(6, 6)
        self._chk.raise_()

        self.cover = QLabel("⏳")
        self.cover.setFixedSize(self.CW, self.CH)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#1e1e1e;border-radius:4px;color:#555;")
        lay.addWidget(self.cover)

        # 时长标签（绝对定位在封面右下角）
        dur_ms = video_meta.get("duration", 0) or 0
        self._dur_lbl = QLabel(self)
        self._dur_lbl.setStyleSheet(
            "color:white;background:rgba(0,0,0,150);font-size:8pt;"
            "padding:1px 4px;border-radius:3px;")
        if dur_ms > 0:
            secs = dur_ms // 1000
            self._dur_lbl.setText(f"{secs//60}:{secs%60:02d}")
        self._dur_lbl.adjustSize()
        self._dur_lbl.setVisible(dur_ms > 0)

        lbl = QLabel((video_meta.get("title","")[:26]) or "无标题")
        lbl.setWordWrap(True); lbl.setFixedHeight(32)
        lbl.setStyleSheet("font-size:10pt;color:#ccc;")
        lay.addWidget(lbl)

        row = QHBoxLayout(); row.setSpacing(4); row.setContentsMargins(0,0,0,0)
        self.dl_btn   = QPushButton("下载")
        self.prev_btn = QPushButton("预览")
        for b in (self.dl_btn, self.prev_btn):
            b.setFixedHeight(22)
            b.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;")
        row.addWidget(self.dl_btn, 1)
        row.addWidget(self.prev_btn, 1)

        self.menu_lbl = QLabel("⋮")
        self.menu_lbl.setFixedWidth(14)
        self.menu_lbl.setFixedHeight(22)
        self.menu_lbl.setAlignment(Qt.AlignCenter)
        self.menu_lbl.setStyleSheet(
            "color:#888;font-size:13pt;border-radius:3px;"
            "background:transparent;")
        self.menu_lbl.setCursor(Qt.PointingHandCursor)
        self.menu_lbl.installEventFilter(self)
        row.addWidget(self.menu_lbl)
        lay.addLayout(row)

        self.dl_btn.clicked.connect(self._on_dl)
        self.prev_btn.clicked.connect(self._on_prev)

        self._refresh()
        self._reposition_dur_lbl()

        url = video_meta.get("cover_url","")
        if url:
            ldr = CoverLoader(video_meta["aweme_id"], url)
            ldr.loaded.connect(self._on_cover)
            ldr.start(); self._ldr = ldr
        else:
            self._ldr = None

    def stop_loader(self):
        """在销毁前调用，停止封面加载线程（不阻塞主线程）。"""
        ldr = getattr(self, "_ldr", None)
        if ldr:
            try:
                ldr.loaded.disconnect(self._on_cover)
            except Exception:
                pass
            if ldr.isRunning():
                ldr.requestInterruption()
            # _active_loaders 持有 ldr 引用直到线程结束，不会被 GC 提前回收
        self._ldr = None

    def _refresh(self):
        lp = get_local_video_path(self.video_meta["aweme_id"], self.save_dir)
        self._local_path = lp
        if lp:
            self.dl_btn.setText("已下载")
            self.dl_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                      "background:#388e3c;color:white;")
            self.dl_btn.setEnabled(False)
            self.prev_btn.setEnabled(True)
            self.prev_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                        "background:#1565c0;color:white;")
        else:
            self.dl_btn.setText("下载")
            self.dl_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                      "background:#007acc;color:white;")
            self.dl_btn.setEnabled(True)
            self.prev_btn.setEnabled(False)
            self.prev_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;")

    def mark_downloaded(self, path):
        self._local_path = path
        self.dl_btn.setText("已下载")
        self.dl_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                  "background:#388e3c;color:white;")
        self.dl_btn.setEnabled(False)
        self.prev_btn.setEnabled(True)
        self.prev_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                    "background:#1565c0;color:white;")

    def _on_cover(self, _, pix):
        s = pix.scaled(self.CW, self.CH, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        c = s.copy((s.width()-self.CW)//2, (s.height()-self.CH)//2, self.CW, self.CH)
        self.cover.setPixmap(c)

    def _on_dl(self):
        self.download_requested.emit(self.video_meta)
        self.update_dl_status("排队中")

    def _on_prev(self):
        if self._local_path and os.path.exists(self._local_path):
            # 优先尝试 IINA（支持更多格式），回退到系统默认播放器
            iina = "/Applications/IINA.app/Contents/MacOS/iina-cli"
            if os.path.exists(iina):
                subprocess.Popen([iina, "--keep-running", self._local_path])
            else:
                subprocess.Popen(["open", self._local_path])

    def _on_menu(self):
        menu = QMenu(self)
        aid = self.video_meta.get("aweme_id", "")
        if self._local_path and os.path.exists(self._local_path):
            open_act = menu.addAction("打开文件")
            open_act.triggered.connect(self._on_prev)
            del_file_act = menu.addAction("删除本地文件")
            del_file_act.triggered.connect(lambda: self.delete_local_requested.emit(aid))
            menu.addSeparator()
        if self._dl_status and self._dl_status not in ("已下载", ""):
            del_act = menu.addAction("从下载列表删除")
            del_act.triggered.connect(lambda: self.remove_from_dl_requested.emit(aid))
        cover_url = self.video_meta.get("cover_url", "")
        video_url = self.video_meta.get("url", "")
        if cover_url or video_url:
            menu.addSeparator()
        if cover_url:
            cp_cover = menu.addAction("复制封面链接")
            cp_cover.triggered.connect(lambda: QApplication.clipboard().setText(cover_url))
        if video_url:
            cp_video = menu.addAction("复制视频链接")
            cp_video.triggered.connect(lambda: QApplication.clipboard().setText(video_url))
        if not menu.actions():
            no_act = menu.addAction("暂无操作")
            no_act.setEnabled(False)
        menu.exec_(self.menu_lbl.mapToGlobal(self.menu_lbl.rect().bottomLeft()))

    def eventFilter(self, obj, event):
        if obj is self.menu_lbl:
            from PyQt5.QtCore import QEvent
            if event.type() == QEvent.Enter:
                self.menu_lbl.setStyleSheet(
                    "color:#ccc;font-size:13pt;border-radius:3px;background:rgba(255,255,255,20);")
            elif event.type() == QEvent.Leave:
                self.menu_lbl.setStyleSheet(
                    "color:#888;font-size:13pt;border-radius:3px;background:transparent;")
            elif event.type() == QEvent.MouseButtonPress:
                self._on_menu()
                return True
        return super().eventFilter(obj, event)

    def update_dl_status(self, status: str):
        """由主窗口在下载状态变化时调用，同步卡片按钮显示。"""
        self._dl_status = status
        status_styles = {
            "排队中":  ("排队中", "#607d8b", False),
            "等待中":  ("等待中", "#607d8b", False),
            "下载中":  ("下载中", "#1565c0", False),
            "已完成":  ("已下载", "#388e3c", False),
            "已暂停":  ("已暂停", "#f57c00", True),
            "已取消":  ("下载",   None,      True),
            "下载失败": ("重试",  "#c62828", True),
        }
        if status in status_styles:
            txt, color, enabled = status_styles[status]
            self.dl_btn.setText(txt)
            self.dl_btn.setEnabled(enabled)
            if color:
                self.dl_btn.setStyleSheet(
                    f"font-size:10pt;padding:1px 5px;border-radius:3px;background:{color};color:white;")
            else:
                self.dl_btn.setStyleSheet("font-size:10pt;padding:1px 5px;border-radius:3px;"
                                          "background:#007acc;color:white;")

    def _reposition_dur_lbl(self):
        """将时长标签定位到封面右下角。"""
        lbl = self._dur_lbl
        lbl.adjustSize()
        # cover 区域：从 (4, 4) 开始，宽 CW，高 CH；右下角留 4px 边距
        x = 4 + self.CW - lbl.width() - 4
        y = 4 + self.CH - lbl.height() - 4
        lbl.move(x, y)
        lbl.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._chk.setChecked(not self._chk.isChecked())
            self._update_selected_style()
        super().mousePressEvent(event)

    def is_selected(self):
        return self._chk.isChecked()

    def set_selected(self, v):
        self._chk.setChecked(v)
        self._update_selected_style()

    def _update_selected_style(self):
        if self._chk.isChecked():
            self.setStyleSheet("QFrame#card{background:#1a3a52;border:2px solid #007acc;border-radius:6px;}")
        else:
            self.setStyleSheet("")


# ─── 下载任务 ─────────────────────────────────────────────────────────────────
class DownloadTask(QObject):
    progress_updated  = pyqtSignal(str, int, int)
    status_updated    = pyqtSignal(str, str)
    download_finished = pyqtSignal(str, bool, str)  # id, ok, local_path

    def __init__(self, task_id, url, title, save_path):
        super().__init__()
        self.task_id = task_id; self.url = url
        self.title   = title;   self.save_path = save_path
        self.is_paused = self.is_cancelled = False
        self._is_active = False
        self.thread = QThread(); self.response = None
        self.moveToThread(self.thread)
        self.thread.started.connect(self._run)

    def start(self):
        if not self.thread.isRunning(): self.thread.start()

    def pause(self):
        self.is_paused = True
        if self.response: self.response.close()

    def resume(self):
        self.is_paused = False
        if not self.thread.isRunning():
            old = self.thread
            if old.isRunning(): old.quit(); old.wait()
            self.thread = QThread(); self.moveToThread(self.thread)
            self.thread.started.connect(self._run); self.thread.start()

    def cancel(self):
        self.is_cancelled = True
        if self.response: self.response.close()
        if self.thread.isRunning(): self.thread.quit(); self.thread.wait()

    def cleanup(self):
        self.is_cancelled = True
        if self.response: self.response.close()
        if self.thread.isRunning(): self.thread.quit(); self.thread.wait()

    def _run(self):
        self._is_active = True
        local = ""
        self.status_updated.emit(self.task_id, "下载中")
        try:
            hdrs = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Referer": "https://www.douyin.com/",
                "Accept-Encoding": "identity",  # 不压缩，确保文件完整
            }
            self.response = requests.get(self.url, headers=hdrs, stream=True,
                                         allow_redirects=True, timeout=30)
            total = int(self.response.headers.get("content-length", 0))
            if self.response.status_code not in (200, 206):
                self.status_updated.emit(self.task_id, f"失败 {self.response.status_code}")
                self.download_finished.emit(self.task_id, False, ""); return

            os.makedirs(self.save_path, exist_ok=True)
            safe = "".join(c for c in self.title if c.isalnum() or c in " -_.").strip() or "video"
            fp   = os.path.join(self.save_path, f"{safe}_{self.task_id[:8]}.mp4")
            tmp  = fp + ".tmp"; cur = 0
            with open(tmp, "wb") as f:
                for chunk in self.response.iter_content(524288):
                    if self.is_cancelled:
                        self.status_updated.emit(self.task_id, "已取消")
                        self.download_finished.emit(self.task_id, False, "")
                        if os.path.exists(tmp): os.remove(tmp); return
                    if self.is_paused:
                        self.status_updated.emit(self.task_id, "已暂停"); return
                    if chunk:
                        f.write(chunk); cur += len(chunk)
                        self.progress_updated.emit(self.task_id, cur, total)
            if os.path.exists(fp): os.remove(fp)
            os.rename(tmp, fp); local = fp
            self.status_updated.emit(self.task_id, "已完成")
            self.download_finished.emit(self.task_id, True, local)
        except Exception as e:
            self.status_updated.emit(self.task_id, f"错误:{e}")
            self.download_finished.emit(self.task_id, False, "")
        finally:
            if self.response: self.response.close()
            self._is_active = False
            # 不需要 quit()：_run 返回后线程自然结束


class DownloadManager(QObject):
    def __init__(self, save_path, max_concurrent=3):
        super().__init__()
        self.tasks = {}
        self.default_save_path = save_path
        self.max_concurrent = max_concurrent
        self._queue = []          # tids waiting to start, in order
        os.makedirs(save_path, exist_ok=True)

    def add_task(self, url, title, aweme_id):
        tid = str(aweme_id) if aweme_id else datetime.now().strftime("%Y%m%d%H%M%S%f")
        existing = self.tasks.get(tid)
        if existing:
            # 已有任务：若是活跃/等待中则不重复添加
            if existing._is_active or tid in self._queue:
                return tid
            # 失败/取消/完成的旧任务：移除，重新创建
            self.tasks.pop(tid, None)
            if tid in self._queue:
                self._queue.remove(tid)
        self.tasks[tid] = DownloadTask(tid, url, title, self.default_save_path)
        self._queue.append(tid)
        return tid

    def schedule(self):
        """Start queued tasks up to max_concurrent. Call after add or on finish."""
        active = sum(1 for t in self.tasks.values()
                     if t._is_active and not t.is_paused and not t.is_cancelled)
        for tid in list(self._queue):
            if active >= self.max_concurrent:
                break
            t = self.tasks.get(tid)
            if t and not t._is_active:
                t.start()
                self._queue.remove(tid)
                active += 1

    def start_task(self, tid):
        """Manually start a specific task (respects max_concurrent cap)."""
        active = sum(1 for t in self.tasks.values()
                     if t._is_active and not t.is_paused and not t.is_cancelled)
        if active >= self.max_concurrent:
            return False
        if tid in self.tasks:
            self.tasks[tid].start()
            if tid in self._queue:
                self._queue.remove(tid)
            return True
        return False

    def on_task_finished(self, tid):
        """Call when a task finishes to trigger next queued download."""
        if tid in self._queue:
            self._queue.remove(tid)
        self.schedule()

    def pause_task(self, tid):
        if tid in self.tasks: self.tasks[tid].pause()

    def resume_task(self, tid):
        if tid in self.tasks: self.tasks[tid].resume()

    def cancel_task(self, tid):
        if tid in self.tasks:
            self.tasks[tid].cancel()
            if tid in self._queue:
                self._queue.remove(tid)
            del self.tasks[tid]

    def set_save_path(self, p):
        self.default_save_path = p; os.makedirs(p, exist_ok=True)

    def set_max_concurrent(self, n):
        self.max_concurrent = max(1, min(10, n))
        self.schedule()  # may start more if limit raised


# ─── 收藏夹列表 Worker (只拿folder列表，不抓视频) ─────────────────────────────
class FolderListWorker(QObject):
    log            = pyqtSignal(str)
    folders_loaded = pyqtSignal(list)   # [{id,name,count}]
    cookie_expired = pyqtSignal()
    finished       = pyqtSignal()

    def __init__(self, cookie_str, show_browser=False):
        super().__init__()
        self.cookie_str = cookie_str
        self.show_browser = show_browser

    @staticmethod
    def _inject(page, cookie_str, log_fn=None):
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                n, _, v = part.partition("=")
                n = n.strip(); v = v.strip()
                if n:
                    cookies.append({"name": n, "value": v,
                                    "domain": ".douyin.com", "path": "/"})
        if log_fn:
            log_fn(f"正在注入 {len(cookies)} 个 Cookie...")
        # 必须先导航到 douyin 域名才能让 set.cookies 生效（空白页注入被浏览器忽略）
        try:
            if not page.url or not page.url.startswith("https://"):
                page.get("https://www.douyin.com/favicon.ico")
                page.wait.doc_loaded(timeout=10)
        except Exception:
            pass
        for ck in cookies:
            try:
                page.set.cookies(ck)
            except Exception:
                pass
        if log_fn:
            log_fn("✅ Cookie 注入完成")

    def run(self):
        page = None
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill","-f","remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"),".douyin_drission_profile"))
            opts.set_local_port(9334)
            self.log.emit("正在启动 Chrome...")
            page = ChromiumPage(addr_or_opts=opts)
            self._inject(page, self.cookie_str, self.log.emit)

            self.log.emit("获取收藏夹列表...")
            # 先开监听再导航，确保第一个 collects/list 包不会被 listen.start() 的 clear() 丢弃
            page.listen.start("collects/list")
            page.get("https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection")
            page.wait.doc_loaded(timeout=20)

            if "passport" in page.url or "login" in page.url.lower():
                self.log.emit("❌ Cookie 已过期，需要重新登录")
                self.cookie_expired.emit(); return

            self.log.emit("获取收藏夹列表...")
            # listen 已开，页面已加载，直接等包，不需要再 refresh

            folders = []
            seen_ids = set()
            page_num = 1

            while page_num <= 100:
                body = None
                deadline_inner = time.time() + 20
                while time.time() < deadline_inner:
                    pkt = page.listen.wait(timeout=4)
                    if pkt is False or pkt is None:
                        continue
                    try:
                        candidate = pkt.response.body
                        if isinstance(candidate, dict) and "collects_list" in candidate:
                            body = candidate
                            break
                    except Exception:
                        pass

                if body is None:
                    self.log.emit(f"  第 {page_num} 页收藏夹等待超时，停止")
                    break

                cl = body.get("collects_list") or []
                added = 0
                for item in cl:
                    fid = str(item.get("collects_id_str") or item.get("collects_id") or "")
                    if not fid or fid in seen_ids:
                        continue
                    seen_ids.add(fid)
                    fname  = item.get("collects_name") or f"收藏夹_{fid}"
                    fcount = item.get("total_number") or 0
                    cover  = ""
                    cc = item.get("collects_cover") or {}
                    ul = cc.get("url_list") or []
                    if ul: cover = ul[0]
                    folders.append({"id": fid, "name": fname, "count": fcount, "cover": cover})
                    added += 1

                self.log.emit(f"  第 {page_num} 页 +{added} 个收藏夹，累计 {len(folders)} 个")

                if not body.get("has_more", False):
                    self.log.emit(f"  已到末页")
                    break

                # 必须滚动内层容器（.route-scroll-container），page.scroll.to_bottom() 只滚 window
                page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=el.scrollHeight+9999;else window.scrollTo(0,document.body.scrollHeight+9999);")
                page_num += 1

            page.listen.stop(); page.quit()

            # 默认收藏（普通收藏，不在自定义收藏夹内）始终放第一位
            default = {"id": "default", "name": "默认收藏", "count": 0, "cover": ""}
            folders = [default] + [f for f in folders if f["id"] != "default"]
            self.log.emit(f"共 {len(folders)} 个收藏夹（含默认收藏）")
            self.folders_loaded.emit(folders)
        except ImportError:
            self.log.emit("❌ 缺少 DrissionPage")
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        finally:
            try:
                if page: page.quit()
            except Exception: pass
            self.finished.emit()


# ─── 单个收藏夹视频 Worker ────────────────────────────────────────────────────
class FolderVideoWorker(QObject):
    log            = pyqtSignal(str)
    progress       = pyqtSignal(int)        # videos so far
    done           = pyqtSignal(list)       # [video_meta]
    cookie_expired = pyqtSignal()
    finished       = pyqtSignal()

    def __init__(self, cookie_str, folder_id, folder_name, show_browser=False):
        super().__init__()
        self.cookie_str  = cookie_str
        self.folder_id   = folder_id
        self.folder_name = folder_name
        self.show_browser = show_browser

    @staticmethod
    def _inject(page, cookie_str, log_fn=None):
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                n, _, v = part.partition("=")
                n = n.strip(); v = v.strip()
                if n:
                    cookies.append({"name": n, "value": v,
                                    "domain": ".douyin.com", "path": "/"})
        if log_fn:
            log_fn(f"正在注入 {len(cookies)} 个 Cookie...")
        # 必须先导航到 douyin 域名才能让 set.cookies 生效（空白页注入被浏览器忽略）
        try:
            if not page.url or not page.url.startswith("https://"):
                page.get("https://www.douyin.com/favicon.ico")
                page.wait.doc_loaded(timeout=10)
        except Exception:
            pass
        for ck in cookies:
            try:
                page.set.cookies(ck)
            except Exception:
                pass
        if log_fn:
            log_fn("✅ Cookie 注入完成")

    def _parse(self, aweme):
        aid = aweme.get("aweme_id","")
        if not aid: return None
        title = (aweme.get("desc","") or "").strip() or f"视频_{aid}"
        author = aweme.get("author",{}).get("nickname","未知")
        vi = aweme.get("video",{})
        url = None
        for k in ("play_addr","download_addr"):
            ul = vi.get(k,{}).get("url_list",[])
            if ul: url = ul[0]; break
        if not url:
            for br in vi.get("bit_rate",[]):
                ul = br.get("play_addr",{}).get("url_list",[])
                if ul: url = ul[0]; break
        if not url: return None
        if not url.startswith("http"): url = "https:" + url
        if "&watermark=" in url: url = url.split("&watermark=")[0]
        cover = vi.get("cover",{}).get("url_list",[""])[0]
        dur = int(vi.get("duration", 0) or aweme.get("duration", 0))
        return {"aweme_id":aid,"title":title,"author":author,"url":url,
                "cover_url":cover,"duration":dur,"synced_at":time.time()}

    def run(self):
        page = None
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill","-f","remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"),".douyin_drission_profile"))
            opts.set_local_port(9334)
            self.log.emit("正在启动 Chrome...")
            page = ChromiumPage(addr_or_opts=opts)
            self._inject(page, self.cookie_str, self.log.emit)

            fid   = self.folder_id
            fname = self.folder_name

            # 默认收藏限 100 条，自定义收藏全量
            max_videos = 100 if fid == "default" else 9999

            if fid == "default":
                # ── 默认收藏：先开监听再导航，确保包不被丢弃 ──────────────
                tgt = "https://www.douyin.com/user/self?showSubTab=favorite_collection&showTab=favorite_collection"
                listen_kw = "listcollection"
                def is_target_pkt(pkt_url, body):
                    return "aweme_list" in body and "listcollection" in (pkt_url or "")

                self.log.emit(f"正在打开默认收藏...")
                page.listen.start(listen_kw)
                page.get(tgt)
                page.wait.doc_loaded(timeout=20)
                if "passport" in page.url or "login" in page.url.lower():
                    self.log.emit("❌ Cookie 已过期，需要重新登录")
                    self.cookie_expired.emit(); return

            else:
                # ── 自定义收藏夹：导航到收藏夹列表，找到 li 后点击触发 API ──
                import re as _re

                LIST_URL = ("https://www.douyin.com/user/self"
                            "?showSubTab=favorite_folder&showTab=favorite_collection")
                LI_CLS   = "W4n61X0W"
                SCROLL_LEFT_JS = ("var el=document.querySelector('.route-scroll-container');"
                                  "if(el){el.scrollTop+=400;"
                                  "return el.scrollTop+'/'+el.scrollHeight+'/'+el.clientHeight;}"
                                  "return 'no_rc';")

                def _find_li(page, name):
                    name_s = name.strip()
                    lis = page.eles(f'css:.{LI_CLS}')
                    if not lis:
                        lis = [li for li in page.eles('tag:li')
                               if '共' in (li.text or '') and '作品' in (li.text or '')]
                    for li in lis:
                        txt = (li.text or '').strip()
                        if txt.split('\n')[0].strip() == name_s:
                            return li
                    for li in lis:
                        if name_s in (li.text or '').split('\n')[0]:
                            return li
                    return None

                listen_kw = "collects/video/list"
                def is_target_pkt(pkt_url, body):
                    return "aweme_list" in body and fid in (pkt_url or "")

                # 开启 listen 后再导航，使 cursor=0 包不被 clear() 丢弃
                page.listen.start(listen_kw)
                page.get(LIST_URL)
                page.wait.doc_loaded(timeout=30)

                # 等待 SPA 渲染
                deadline = time.time() + 20
                while time.time() < deadline:
                    if page.eles(f'css:.{LI_CLS}'):
                        break
                    time.sleep(0.3)

                self.log.emit("验证登录状态...")
                if "passport" in page.url or "login" in page.url.lower():
                    self.log.emit("❌ Cookie 已过期，需要重新登录")
                    self.cookie_expired.emit(); return
                self.log.emit("✅ 登录有效")

                self.log.emit(f"正在收藏夹列表中查找「{fname}」...")
                # 收初始预取包（非阻塞）
                prefetch_bodies = []
                def _drain():
                    while True:
                        pkt = page.listen.wait(timeout=0.3)
                        if not pkt:
                            break
                        try:
                            url = pkt.url or ""
                            b   = pkt.response.body
                            if isinstance(b, dict) and is_target_pkt(url, b):
                                prefetch_bodies.append(b)
                        except Exception:
                            pass
                _drain()

                # 找 li → 找到立即点击；找不到则滚一步再找，循环
                clicked = False
                for scroll_i in range(30):
                    li = _find_li(page, fname)
                    if li:
                        self.log.emit(f"  找到「{fname}」（第{scroll_i}次滚动后），点击...")
                        li.click()
                        time.sleep(0.5)
                        _drain()
                        clicked = True
                        break
                    # 没找到，滚一步
                    self.log.emit(f"  未找到，滚动第 {scroll_i + 1} 次...")
                    try:
                        r = page.run_js(SCROLL_LEFT_JS)
                    except Exception:
                        break
                    time.sleep(0.5)
                    _drain()
                    parts = str(r).split('/')
                    if len(parts) == 3:
                        try:
                            top, sh, ch = int(parts[0]), int(parts[1]), int(parts[2])
                            if top + ch + 100 >= sh:
                                self.log.emit("  已滚到底")
                                break
                        except Exception:
                            pass
                # 最后再找一次
                if not clicked:
                    li = _find_li(page, fname)
                    if li:
                        self.log.emit(f"  最终找到「{fname}」，点击...")
                        li.click(); time.sleep(0.5); _drain(); clicked = True
                    else:
                        self.log.emit(f"  ✗ 未找到收藏夹「{fname}」，同步可能不完整")

            # ── 通用翻页逻辑（默认收藏 & 自定义收藏夹共用）─────────────────────
            # 自定义收藏夹：先消费已收到的 cursor=0 预取包
            videos    = []
            seen_ids  = set()
            page_num  = 1

            scroll_js = """
var el = document.querySelector('.route-scroll-container');
if (!el) el = document.querySelector('[class*="route-scroll"]');
if (!el) el = document.querySelector('[class*="scroll-container"]');
if (el) {
    el.scrollTop = el.scrollHeight + 9999;
    return 'scrolled:' + el.className.substring(0, 60) + ' top=' + el.scrollTop;
}
window.scrollTo(0, document.body.scrollHeight + 9999);
return 'window fallback';
"""

            def consume_prefetch():
                if fid == "default":
                    return
                for body in prefetch_bodies:
                    if body.get("status_code", 0) != 0:
                        continue
                    for aw in (body.get("aweme_list") or []):
                        vm = self._parse(aw)
                        if vm and vm["aweme_id"] not in seen_ids:
                            vm["folder_id"] = fid
                            videos.append(vm); seen_ids.add(vm["aweme_id"])
                if prefetch_bodies:
                    self.log.emit(f"  预取 cursor=0: {len(prefetch_bodies)} 包，已收录 {len(videos)} 个视频")
                    self.progress.emit(len(videos))
                    # 如果预取数据本身没有 has_more，直接返回
                    if not any(b.get("has_more") for b in prefetch_bodies):
                        return True   # complete
                return False

            if fid != "default" and consume_prefetch():
                self.log.emit(f"  预取数据已完整，共 {len(videos)} 个")
            else:
                while page_num <= 500 and len(videos) < max_videos:
                    self.log.emit(f"  等待第 {page_num} 页响应...")

                    body = None
                    deadline = time.time() + 25
                    while time.time() < deadline:
                        pkt = page.listen.wait(timeout=4)
                        if pkt is False or pkt is None:
                            continue
                        try:
                            pkt_url = getattr(pkt, "url", "") or ""
                            candidate = pkt.response.body
                            if isinstance(candidate, dict) and is_target_pkt(pkt_url, candidate):
                                body = candidate; break
                        except Exception:
                            pass

                    if body is None:
                        self.log.emit(f"  第 {page_num} 页超时，停止")
                        break
                    if body.get("status_code", -1) != 0:
                        self.log.emit(f"  接口错误码 {body.get('status_code')}，停止")
                        break

                    added = 0
                    for aw in (body.get("aweme_list") or []):
                        if len(videos) >= max_videos: break
                        vm = self._parse(aw)
                        if vm and vm["aweme_id"] not in seen_ids:
                            vm["folder_id"] = fid
                            videos.append(vm); seen_ids.add(vm["aweme_id"]); added += 1

                    self.log.emit(f"  第 {page_num} 页 +{added}，累计 {len(videos)}")
                    self.progress.emit(len(videos))

                    if not body.get("has_more", False) or len(videos) >= max_videos:
                        self.log.emit(f"  已到末页或达到上限，共 {len(videos)} 个")
                        break

                    try:
                        result = page.run_js(scroll_js)
                        self.log.emit(f"  滚动触发: {result}")
                    except Exception as e:
                        self.log.emit(f"  滚动出错: {e}，尝试 scroll.to_bottom()")
                        page.scroll.to_bottom()
                    # 不需要 sleep，下一轮 listen.wait 会等包到达
                    page_num += 1

            page.listen.stop()
            self.log.emit(f"✅ 完成，共 {len(videos)} 个，关闭浏览器...")
            self.done.emit(videos)
        except ImportError:
            self.log.emit("❌ 缺少 DrissionPage")
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        finally:
            try:
                if page: page.quit()
            except Exception: pass
            self.finished.emit()


# ─── 全量收藏夹视频同步 Worker（复用单个 Chrome 实例）────────────────────────────
class AllFoldersVideoWorker(QObject):
    log            = pyqtSignal(str)
    folders_loaded = pyqtSignal(list)            # [{id,name,count,...}]
    folder_done    = pyqtSignal(str, str, list)  # fid, fname, videos
    cookie_expired = pyqtSignal()
    verification_needed = pyqtSignal()           # 检测到人机验证，需要用户手动处理
    finished       = pyqtSignal()

    def __init__(self, cookie_str, mode="all", folders=None, show_browser=False):
        super().__init__()
        self.cookie_str  = cookie_str
        self.mode        = mode
        self.folders     = folders
        self.show_browser = show_browser
        self._paused     = False
        self._cancelled  = False

    def pause(self):  self._paused = True
    def resume(self): self._paused = False
    def cancel(self): self._cancelled = True; self._paused = False

    def _log(self, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.log.emit(f"[{ts}] {msg}")

    def _wait_if_paused(self):
        """阻塞直到 resume() 或 cancel() 被调用。"""
        while self._paused and not self._cancelled:
            time.sleep(0.3)

    _CAPTCHA_JS = """
(function(){
  var sels=['#captcha_container','[class*="captcha"]','[class*="verify"]',
            '[id*="captcha"]','[id*="verify"]','.secsdk-captcha-drag-icon',
            '[class*="secsdk"]','[class*="verify-wrap"]'];
  for(var i=0;i<sels.length;i++){
    var el=document.querySelector(sels[i]);
    if(el){var s=window.getComputedStyle(el);if(s.display!=='none'&&s.visibility!=='hidden'&&parseFloat(s.opacity||'1')>0)return true;}
  }
  return false;
})()
"""

    def _check_and_handle_verification(self, page):
        """检测人机验证覆盖层，若存在则发信号暂停并等待用户处理完后再继续。"""
        try:
            has_captcha = bool(page.run_js(self._CAPTCHA_JS))
        except Exception:
            return
        if not has_captcha:
            return
        self._log("⚠️ 检测到人机验证（滑块/验证码），已暂停同步，请手动完成验证后继续")
        self.verification_needed.emit()
        # 暂停自己，等待主线程调用 resume() 或 cancel()
        self._paused = True
        self._wait_if_paused()
        self._log("  验证完成，继续同步...")


        """在已有 page 上获取收藏夹列表，返回 [{id,name,count}]。"""
        self._log("获取收藏夹列表...")
        FAV_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
        # 先开监听再导航，确保第一个包不被 listen.start() 的内部 clear() 丢弃
        page.listen.start("collects/list")
        page.get(FAV_URL)
        page.wait.doc_loaded(timeout=30)

        if "passport" in page.url or "login" in page.url.lower():
            self._log("❌ Cookie 已过期，需要重新登录")
            self.cookie_expired.emit()
            return []
        self._log("✅ 登录有效")

        folders = []; seen_ids = set(); page_num = 1
        while page_num <= 100:
            body = None
            deadline = time.time() + 20
            while time.time() < deadline:
                pkt = page.listen.wait(timeout=4)
                if pkt is False or pkt is None: continue
                try:
                    candidate = pkt.response.body
                    if isinstance(candidate, dict) and "collects_list" in candidate:
                        body = candidate; break
                except Exception: pass

            if body is None:
                self._log(f"  第 {page_num} 页收藏夹等待超时，停止")
                break

            added = 0
            for item in (body.get("collects_list") or []):
                fid = str(item.get("collects_id_str") or item.get("collects_id") or "")
                if not fid or fid in seen_ids: continue
                seen_ids.add(fid)
                fname  = item.get("collects_name") or item.get("name") or f"收藏夹_{fid}"
                fcount = item.get("video_count", 0)
                folders.append({"id": fid, "name": fname, "count": fcount, "cover": ""})
                added += 1

            self._log(f"  第 {page_num} 页 +{added} 个收藏夹，累计 {len(folders)} 个")
            if not body.get("has_more", False): break
            page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=el.scrollHeight+9999;else window.scrollTo(0,document.body.scrollHeight+9999);")
            page_num += 1

        page.listen.stop()

        default = {"id": "default", "name": "默认收藏", "count": 0, "cover": ""}
        return [f for f in folders if f["id"] != "default"] + [default]

    @staticmethod
    def _inject(page, cookie_str, log_fn=None):
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                n, _, v = part.partition("=")
                n = n.strip(); v = v.strip()
                if n:
                    cookies.append({"name": n, "value": v,
                                    "domain": ".douyin.com", "path": "/"})
        if log_fn:
            log_fn(f"正在注入 {len(cookies)} 个 Cookie...")
        # 必须先导航到 douyin 域名才能让 set.cookies 生效（空白页注入被浏览器忽略）
        try:
            if not page.url or not page.url.startswith("https://"):
                page.get("https://www.douyin.com/favicon.ico")
                page.wait.doc_loaded(timeout=10)
        except Exception:
            pass
        for ck in cookies:
            try:
                page.set.cookies(ck)
            except Exception:
                pass
        if log_fn:
            log_fn("✅ Cookie 注入完成")

    def _parse(self, aweme):
        aid = aweme.get("aweme_id", "")
        if not aid: return None
        title  = (aweme.get("desc", "") or "").strip() or f"视频_{aid}"
        author = aweme.get("author", {}).get("nickname", "未知")
        vi  = aweme.get("video", {})
        url = None
        for k in ("play_addr", "download_addr"):
            ul = vi.get(k, {}).get("url_list", [])
            if ul: url = ul[0]; break
        if not url:
            for br in vi.get("bit_rate", []):
                ul = br.get("play_addr", {}).get("url_list", [])
                if ul: url = ul[0]; break
        if not url: return None
        if not url.startswith("http"): url = "https:" + url
        if "&watermark=" in url: url = url.split("&watermark=")[0]
        cover = vi.get("cover", {}).get("url_list", [""])[0]
        dur = int(vi.get("duration", 0) or aweme.get("duration", 0))
        return {"aweme_id": aid, "title": title, "author": author, "url": url,
                "cover_url": cover, "duration": dur, "synced_at": time.time()}

    # 滚动右侧视频列表的 JS（.route-scroll-container 是整页主滚动容器）
    # verify_4 实测确认：滚动 .route-scroll-container 能触发 cursor=10/20/30 分页请求
    _SCROLL_JS = "var el=document.querySelector('.route-scroll-container');if(el){var b=el.scrollTop;el.scrollTop=el.scrollHeight+9999;return 'rc:'+b+'->'+el.scrollTop;}var b=window.scrollY;window.scrollTo(0,document.body.scrollHeight+9999);return 'win:'+b+'->'+window.scrollY;"

    # 检测页面是否已到底（"暂时没有更多了" 或同类提示）
    _NO_MORE_JS = """
(function(){
  // 1. 先检查用户指定的具体 XPath（视频列表页"没有更多内容了"节点）
  try{
    var xpaths=[
      '/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div/div/div/div/div/div[2]/div/div[2]/div/div/div[2]/div/div[2]/div/div[2]/div/div',
      '/html/body/div[2]/div[1]/div[4]/div[2]/div/div/div/div/div/div/div/div/div[2]/div/div[2]/div/div/div[2]/div/div[2]/div/div[2]/div'
    ];
    for(var xi=0;xi<xpaths.length;xi++){
      var xr=document.evaluate(xpaths[xi],document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);
      var xel=xr.singleNodeValue;
      if(xel){
        var xt=(xel.innerText||xel.textContent||'').trim();
        if(xt.indexOf('没有更多')>=0||xt.indexOf('暂时没有')>=0||xt.indexOf('到底了')>=0||xt.indexOf('内容了')>=0) return true;
      }
    }
  }catch(e){}
  // 2. 全页叶子节点扫描（兜底）
  var texts=['暂时没有更多了','没有更多了','没有更多内容了','已经到底了','到底了','No more'];
  var all=document.querySelectorAll('*');
  for(var i=0;i<all.length;i++){
    var el=all[i];
    if(el.children.length>0) continue;
    var t=(el.innerText||el.textContent||'').trim();
    for(var j=0;j<texts.length;j++){if(t===texts[j]||t.indexOf(texts[j])>=0)return true;}
  }
  return false;
})()
"""

    # 左侧面板滚动 JS（与右侧共用同一个 .route-scroll-container，verify_1 已确认）
    _SCROLL_LEFT_JS = "var el=document.querySelector('.route-scroll-container');if(el){el.scrollTop+=400;return el.scrollTop+'/'+el.scrollHeight+'/'+el.clientHeight;}return 'no_rc';"

    def _do_scroll(self, page):
        try:
            r = page.run_js(self._SCROLL_JS)
            self._log(f"    滚动视频列表: {r or 'None'}")
        except Exception as e:
            self._log(f"    滚动出错: {e}")

    def _is_at_bottom(self, page):
        """检测页面是否显示了"暂时没有更多了"等到底提示。"""
        try:
            return bool(page.run_js(self._NO_MORE_JS))
        except Exception:
            return False

    def _scroll_left_panel(self, page):
        """
        滚动左侧收藏夹列表直到所有 li 加载完（懒加载）。

        设计依据（verify_1 + verify_6）：
        - 左侧 ul.QhXy7t32 与右侧视频列表共用同一个 .route-scroll-container
        - 初始只渲染约 40 个 li；每次滚动约 400px 追加 10 个 li
        - 滚动到底（scrollTop + clientHeight >= scrollHeight）时所有 li 加载完
        - 滚动同时还会触发新 li 对应的 cursor=0 预取请求（verify_6 实测）
          → 调用方必须在此期间持续收包，否则会错过这些预取包

        返回：加载完成后的 li 数量（int）
        """
        import re as _re
        prev_count = 0
        for _ in range(30):                        # 最多滚动 30 次，约 12000px
            try:
                r = page.run_js(self._SCROLL_LEFT_JS)
            except Exception:
                break
            if not r or r == 'no_rc':
                break
            time.sleep(0.4)                        # 等待懒加载渲染
            try:
                cur_count = len(self._find_panel_lis(page))
            except Exception:
                break
            # 解析滚动状态
            parts = str(r).split('/')
            if len(parts) == 3:
                try:
                    top, sh, ch = int(parts[0]), int(parts[1]), int(parts[2])
                    if top + ch + 100 >= sh:       # 到底了
                        break
                except Exception:
                    pass
            prev_count = cur_count
        try:
            final = len(self._find_panel_lis(page))
        except Exception:
            final = prev_count
        self._log(f"  左侧面板滚动完成，共 {final} 个 li")
        return final

    def _sync_one(self, page, fid, fname, prefetch_bodies=None):
        """
        同步单个收藏夹的所有视频。

        设计依据：
        - verify_2 确认：listen.start() 的 clear() 会丢弃 cursor=0 包，
          因此 cursor=0 数据必须从 prefetch_bodies 拿（由调用方在 listen 开启时收集）。
        - verify_4 确认：点击 li 后浏览器自动发 cursor=10，
          滚动 .route-scroll-container 触发 cursor=20/30/...
        - prefetch_bodies 中同一 cursor=0 包可能因左侧滚动被重复收到，
          通过 seen_ids 去重确保正确性。
        - collects_id={fid} 过滤确保不接收其他收藏夹的残包（verify_3 依据）。

        调用前：li 已点击（触发了 cursor=10 请求），全局 listen 持续运行。
        """
        import re as _re
        is_default = (fid == "default")
        max_videos = 100 if is_default else 9999

        def is_target(url, body):
            if is_default:
                return "aweme_list" in body and "listcollection" in (url or "")
            # 用 & 或 ? 锚定，防止 collects_id=123 误匹配 collects_id=1234
            u = url or ""
            return "aweme_list" in body and (
                f"collects_id={fid}&" in u or
                f"collects_id={fid}" == u[-len(f"collects_id={fid}"):] or
                u.endswith(f"collects_id={fid}")
            )

        def collect_next_page(first_pkt_timeout):
            """从 listen 流中等到下一个目标包，然后收完静默窗口内的并发包。
            在等包期间每 2s 轮询底部提示，一旦出现立即返回空列表（不再硬等超时）。"""
            bodies = []
            deadline = time.time() + first_pkt_timeout
            last_bottom_check = 0.0
            while time.time() < deadline:
                pkt = page.listen.wait(timeout=2)
                if not pkt:
                    # 每次 2s 无包，检查底部 DOM 和验证码
                    now = time.time()
                    if now - last_bottom_check >= 2.0:
                        last_bottom_check = now
                        self._check_and_handle_verification(page)
                        if self._cancelled:
                            return bodies
                        if self._is_at_bottom(page):
                            self._log("    检测到底部提示，停止等包")
                            return bodies
                    continue
                try:
                    url = (pkt.url or "")
                    b = pkt.response.body
                    if isinstance(b, dict) and is_target(url, b):
                        bodies.append(b)
                        break
                except Exception:
                    pass
            if not bodies:
                return bodies
            # 收同批次并发包（静默窗口 1.5s）
            sil_end = time.time() + 1.5
            while time.time() < sil_end:
                pkt = page.listen.wait(timeout=1)
                if not pkt:
                    continue
                try:
                    url = (pkt.url or "")
                    b = pkt.response.body
                    if isinstance(b, dict) and is_target(url, b):
                        bodies.append(b)
                        sil_end = time.time() + 1.5
                except Exception:
                    pass
            return bodies

        def extract_videos(bodies):
            added = 0
            any_has_more = False
            for body in bodies:
                if body.get("status_code", 0) != 0:
                    continue
                if body.get("has_more"):
                    any_has_more = True
                for aw in (body.get("aweme_list") or []):
                    if len(videos) >= max_videos:
                        break
                    vm = self._parse(aw)
                    # seen_ids 去重兼顾 prefetch 重复包和正常分页重叠
                    if vm and vm["aweme_id"] not in seen_ids:
                        vm["folder_id"] = fid
                        videos.append(vm)
                        seen_ids.add(vm["aweme_id"])
                        added += 1
            return added, any_has_more

        videos = []; seen_ids = set(); page_num = 1; consec_timeout = 0

        # 第一页：优先使用预取缓存（cursor=0 已被 listen.start() 丢弃，只能从这里拿）
        # seen_ids 去重处理同一 cursor=0 包因左侧懒加载被重复收到的情况
        if prefetch_bodies:
            added, any_has_more = extract_videos(prefetch_bodies)
            self._log(f"    第1页(预取) {len(prefetch_bodies)} 包 +{added}（去重后），累计 {len(videos)}")
            if not any_has_more or len(videos) >= max_videos:
                self._log("    同步完成（预取已完整）")
                return videos
            page_num = 2
            # 预取有 has_more=True → 点击 li 后浏览器已自动发 cursor=10
            first_timeout = 15
        else:
            # 无预取：等浏览器在点击后发 cursor=0（仅当 listen 在点击前已开启且未 clear）
            first_timeout = 15

        while page_num <= 500 and len(videos) < max_videos:
            self._wait_if_paused()
            if self._cancelled:
                self._log("    已取消同步"); break

            bodies = collect_next_page(first_timeout)
            first_timeout = 12

            if not bodies:
                consec_timeout += 1
                self._log(f"    第 {page_num} 页等包超时（连续 {consec_timeout}）")
                if self._is_at_bottom(page):
                    self._log("    检测到底部提示，同步完成"); break
                if consec_timeout >= 2:
                    self._log("    连续超时，停止"); break
                self._do_scroll(page)
                if self._is_at_bottom(page):
                    self._log("    滚动后检测到底部提示，同步完成"); break
                continue

            consec_timeout = 0
            added, any_has_more = extract_videos(bodies)
            self._log(f"    第 {page_num} 页 {len(bodies)} 包 +{added}，累计 {len(videos)}")

            # 接口明确说没有更多，或已达上限，直接结束
            if not any_has_more or len(videos) >= max_videos:
                self._log("    同步完成"); break

            # 收到数据后先检测底部，再决定是否继续滚动
            if self._is_at_bottom(page):
                self._log("    检测到底部提示，同步完成"); break

            # 稍等一下让 DOM 完成渲染，再检测一次，避免滚动时 DOM 还未刷新
            time.sleep(0.3)
            if self._is_at_bottom(page):
                self._log("    检测到底部提示，同步完成"); break

            self._do_scroll(page)
            page_num += 1

        return videos

    LIST_URL = ("https://www.douyin.com/user/self"
                "?showSubTab=favorite_folder&showTab=favorite_collection")

    # 收藏夹列表页（showSubTab=favorite_folder）左侧 li class
    _LI_CLS = "W4n61X0W"
    _li_cls_cache = None

    # 视频列表页（点击收藏夹进入后）左侧面板每个收藏夹条目的 div class
    _FOLDER_ITEM_CLS = "yKNs6LhU"

    # 探测左侧收藏夹 li 的 JS：返回第一个 class 名 + 样本文字，用于调试
    _DETECT_LI_CLS_JS = """
(function(){
  var lis = document.querySelectorAll('li');
  for(var i=0;i<lis.length;i++){
    var t=(lis[i].innerText||'').trim();
    var cls=lis[i].className||'';
    // 包含「共」+「作品」：旧版抖音
    if(t.indexOf('共')>=0 && t.indexOf('作品')>=0 && cls){
      return cls.split(' ')[0]+'|'+t.substring(0,30);
    }
  }
  // 宽泛兜底：找左侧导航区域的 li（有多个同类 li 且含收藏夹关键字）
  var all = document.querySelectorAll('li');
  var counts = {};
  for(var i=0;i<all.length;i++){
    var c=(all[i].className||'').split(' ')[0];
    if(c) counts[c]=(counts[c]||0)+1;
  }
  // 找出出现次数 >= 5 的 class（侧边栏收藏夹列表特征）
  for(var c in counts){
    if(counts[c]>=5){
      var sample=document.querySelector('li.'+c);
      var t2=(sample?sample.innerText:'').trim().substring(0,30);
      return c+'|'+t2+'|count='+counts[c];
    }
  }
  return null;
})()
"""

    def _find_panel_lis(self, page):
        """返回左侧收藏夹 li 列表，先用缓存的 class，失败则动态探测。"""
        # 1. 先用缓存 class（或默认值）
        cls = self._li_cls_cache or self._LI_CLS
        lis = page.eles(f'css:.{cls}')
        if lis:
            return lis
        # 2. class 可能被 SPA 热更新重命名 → 运行时探测
        try:
            raw = page.run_js(self._DETECT_LI_CLS_JS)
            if raw:
                new_cls = raw.split('|')[0].strip()
                if new_cls and new_cls != cls:
                    self._log(f"  li class 已更新: {cls!r} → {new_cls!r}（样本: {raw!r}），缓存新值")
                    AllFoldersVideoWorker._li_cls_cache = new_cls
                    lis = page.eles(f'css:.{new_cls}')
                    if lis:
                        return lis
        except Exception:
            pass
        # 3. 最终兜底：遍历所有 li，按文字内容匹配（不依赖 class）
        try:
            candidates = [li for li in page.eles('tag:li')
                          if '共' in (li.text or '') and '作品' in (li.text or '')]
            if candidates:
                return candidates
            # 再宽泛一点：找有多个相同 class 且文字不为空的 li 组
            # （收藏夹 li 总是一组相同 class 的 li）
            return []
        except Exception:
            return []

    def _find_panel_divs(self, page):
        """返回视频列表页左侧收藏夹面板的条目 div 列表（yKNs6LhU class）。"""
        cls = self._FOLDER_ITEM_CLS
        divs = page.eles(f'css:.{cls}')
        return divs if divs else []

    def _find_folder_item(self, page, fname, log_sample=False):
        """在视频列表页左侧面板找目标收藏夹 div（yKNs6LhU）。
        div 的 text 格式：'收藏夹名称\\n数量' 或 '收藏夹名称  数量'。
        """
        fname_s = fname.strip()
        divs = self._find_panel_divs(page)
        if not divs:
            return None
        if log_sample:
            samples = [repr((d.text or '').strip()[:40]) for d in divs[:5]]
            if samples:
                self._log(f"    左侧面板 div 样本({len(divs)}个): {', '.join(samples)}")
        for d in divs:
            try:
                txt = (d.text or '').strip()
                # 取第一行（换行前）或去掉末尾数字部分
                name_part = txt.split('\n')[0].strip().split('  ')[0].strip()
                if name_part == fname_s:
                    return d
            except Exception:
                pass
        for d in divs:
            try:
                txt = (d.text or '').strip()
                name_part = txt.split('\n')[0].strip().split('  ')[0].strip()
                if fname_s in name_part or name_part in fname_s:
                    return d
            except Exception:
                pass
        return None

    def _find_folder_li(self, page, fname, log_sample=False):
        """在收藏夹列表页左侧找目标 li（W4n61X0W）。"""
        fname_s = fname.strip()
        lis = self._find_panel_lis(page)
        if not lis:
            return None
        if log_sample:
            samples = []
            for li in lis[:5]:
                try:
                    samples.append(repr((li.text or '').strip()[:40]))
                except Exception:
                    pass
            if samples:
                self._log(f"    li 样本({len(lis)}个): {', '.join(samples)}")
        for li in lis:
            try:
                txt = (li.text or '').strip()
                if txt.split('\n')[0].strip() == fname_s:
                    return li
            except Exception:
                pass
        for li in lis:
            try:
                txt = (li.text or '').strip()
                if fname_s in txt.split('\n')[0]:
                    return li
            except Exception:
                pass
        return None

    def _load_list_page(self, page):
        """导航到收藏夹列表页，等左侧 li 渲染完成。
        必须在 page.listen.start() 之前调用（或全局 listen 已开启状态下调用），
        让页面预取的 cursor=0 包进入缓冲区。
        """
        page.get(self.LIST_URL)
        page.wait.doc_loaded(timeout=30)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._find_panel_lis(page):
                break
            time.sleep(0.3)
        cnt = len(self._find_panel_lis(page))
        self._log(f"收藏夹列表已加载，共 {cnt} 个 li")
        return cnt

    def _load_and_drain(self, page):
        """
        单次导航到 LIST_URL，滚动左侧面板加载所有 li，同时收集：
          - collects/list 包 → 收藏夹名单（替代 _fetch_folder_list 的导航）
          - collects/video/list 包 → 视频 cursor=0 预取包

        优化：一次导航同时拿到收藏夹列表 + 视频预取，比先 _fetch_folder_list
        再 _load_and_drain 少一次完整导航。

        调用前：调用方必须已执行 page.listen.start(kw)，kw 可以是宽泛关键字
                （如 "collects"）以同时匹配两种 API。

        返回 (folders, prefetch):
          folders  : [{id,name,count,cover}] 从 collects/list 包解析的收藏夹列表
                     （不含默认收藏；调用方自行追加）
          prefetch : {collects_id: [body,...]} 视频 cursor=0 包
        """
        import re as _re
        page.get(self.LIST_URL)
        page.wait.doc_loaded(timeout=30)
        # 等待 SPA 渲染
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._find_panel_lis(page):
                break
            time.sleep(0.3)

        if "passport" in page.url or "login" in page.url.lower():
            self._log("❌ Cookie 已过期，需要重新登录")
            self.cookie_expired.emit()
            return [], {}

        prefetch = {}           # {fid: [video_body,...]}
        folder_pages = {}       # {page_num: body} 收藏夹列表分页
        seen_fids = set()
        folders = []

        folder_list_has_more = [False]   # 用列表让内部函数可写

        def _drain_now():
            """非阻塞排空缓冲区，同时处理两种包"""
            while True:
                pkt = page.listen.wait(timeout=0.2)
                if not pkt:
                    break
                try:
                    url = pkt.url or ""
                    b = pkt.response.body
                    if not isinstance(b, dict):
                        continue
                    # 视频预取包
                    if "collects/video/list" in url and "aweme_list" in b:
                        m = _re.search(r'collects_id=(\d+)', url)
                        if m:
                            prefetch.setdefault(m.group(1), []).append(b)
                    elif "listcollection" in url and "aweme_list" in b:
                        prefetch.setdefault("default", []).append(b)
                    # 收藏夹名单包
                    elif "collects/list" in url and "collects_list" in b:
                        pn = len(folder_pages)
                        folder_pages[pn] = b
                        for item in (b.get("collects_list") or []):
                            fid = str(item.get("collects_id_str") or item.get("collects_id") or "")
                            if not fid or fid in seen_fids:
                                continue
                            seen_fids.add(fid)
                            fname  = item.get("collects_name") or item.get("name") or f"收藏夹_{fid}"
                            fcount = item.get("video_count") or item.get("total_number") or 0
                            cover  = ""
                            cc = item.get("collects_cover") or {}
                            ul = cc.get("url_list") or []
                            if ul: cover = ul[0]
                            folders.append({"id": fid, "name": fname, "count": fcount, "cover": cover})
                        # 记录是否还有下一页名单
                        folder_list_has_more[0] = bool(b.get("has_more"))
                except Exception:
                    pass

        # 等初始包
        last_new = time.time()
        hard_limit = time.time() + 10
        while time.time() < hard_limit:
            prev_len = sum(len(v) for v in prefetch.values()) + len(folders)
            _drain_now()
            new_len = sum(len(v) for v in prefetch.values()) + len(folders)
            if new_len > prev_len:
                last_new = time.time()
            elif time.time() - last_new > 2.0:
                break
            time.sleep(0.3)

        # 滚动左侧面板，加载所有 li，持续收包
        self._log(f"  滚动左侧面板加载所有 li（listen 持续收包）...")
        prev_count = len(self._find_panel_lis(page))
        self._log(f"  初始 li 数: {prev_count}，已知收藏夹: {len(folders)} 个")
        # DOM 探测：打印实际 li 结构，帮助确认选择器
        try:
            dom_info = page.run_js("""
(function(){
  var lis=document.querySelectorAll('li');
  var out=[];
  for(var i=0;i<Math.min(lis.length,5);i++){
    var li=lis[i];
    out.push('cls=['+li.className+'] txt='+((li.innerText||'').trim().substring(0,30)));
  }
  // 找收藏夹相关 li
  var fav=[];
  for(var i=0;i<lis.length;i++){
    var t=(lis[i].innerText||'').trim();
    if(t.length>0 && t.length<60 && lis[i].className){
      fav.push('cls=['+lis[i].className.split(' ')[0]+'] txt='+t.substring(0,40));
      if(fav.length>=5) break;
    }
  }
  return 'total_li='+lis.length+' || samples: '+fav.join(' | ');
})()
""")
            self._log(f"  [DOM探测] {dom_info}")
        except Exception as e:
            self._log(f"  [DOM探测失败] {e}")

        for scroll_i in range(30):
            try:
                r = page.run_js(self._SCROLL_LEFT_JS)
            except Exception:
                break
            time.sleep(0.4)
            _drain_now()
            # 若 collects/list 还有下一页，需要滚到底触发下一页请求（名单 API 分页机制）
            if folder_list_has_more[0]:
                folder_list_has_more[0] = False
                try:
                    page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=el.scrollHeight+9999;else window.scrollTo(0,document.body.scrollHeight+9999);")
                except Exception:
                    pass
                # 等新的名单包到达
                t_wait = time.time() + 5
                prev_f = len(folders)
                while time.time() < t_wait:
                    _drain_now()
                    if len(folders) > prev_f:
                        break
                    time.sleep(0.2)
                self._log(f"  collects/list 翻页后收藏夹={len(folders)}")
            try:
                cur = len(self._find_panel_lis(page))
            except Exception:
                break
            if cur != prev_count:
                self._log(f"  scroll {scroll_i+1}: li={cur}，收藏夹={len(folders)}")
                prev_count = cur
            parts = str(r).split('/')
            if len(parts) == 3:
                try:
                    top, sh, ch = int(parts[0]), int(parts[1]), int(parts[2])
                    if top + ch + 100 >= sh:
                        break
                except Exception:
                    pass

        # 再等最后一批；若名单还有更多页则继续触发
        last_new = time.time()
        hard_limit2 = time.time() + 6
        while time.time() < hard_limit2:
            prev_len = sum(len(v) for v in prefetch.values()) + len(folders)
            _drain_now()
            if folder_list_has_more[0]:
                folder_list_has_more[0] = False
                try:
                    page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=el.scrollHeight+9999;else window.scrollTo(0,document.body.scrollHeight+9999);")
                except Exception:
                    pass
                hard_limit2 = time.time() + 6   # 重置等待窗口
                last_new = time.time()
                time.sleep(0.3)
                continue
            new_len = sum(len(v) for v in prefetch.values()) + len(folders)
            if new_len > prev_len:
                last_new = time.time()
            elif time.time() - last_new > 1.5:
                break
            time.sleep(0.3)

        # 滚回顶部，准备后续点击 li
        try:
            page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=0;")
            time.sleep(0.3)
        except Exception:
            pass

        self._log(f"  加载完毕: {prev_count} 个 li，{len(folders)} 个收藏夹，{len(prefetch)} 个有预取视频数据")
        return folders, prefetch


    def _nav_click_folder(self, page, fid, fname):
        """
        切换到目标收藏夹并返回预取数据。

        两种路径：
        1. 视频列表页（已点击过某个收藏夹进入）：左侧面板是 DIV.yKNs6LhU，
           直接点击目标 div 切换，不需要重新导航。
        2. 收藏夹列表页（LIST_URL，或 fallback 导航后）：左侧是 li.W4n61X0W，
           点击后进入视频列表页。

        listen 必须在调用前已开启。
        """
        import re as _re

        def _wait_for_click_settle():
            """点击后短暂等待，让浏览器建立请求，不消耗任何 listen 包。"""
            time.sleep(0.8)

        def _drain_stale():
            """排空 listen 缓冲区里点击前残留的旧包，不保存任何数据。"""
            while True:
                pkt = page.listen.wait(timeout=0.1)
                if not pkt:
                    break


        def _try_click_div(scroll_first=True):
            """在视频列表页左侧面板（DIV.yKNs6LhU）找目标并点击。
            所有 yKNs6LhU div 已全量在 DOM 中（非懒加载），直接查找后 scrollIntoView。
            """
            _drain_stale()
            target = self._find_folder_item(page, fname, log_sample=True)
            if target:
                self._log(f"    找到「{fname}」左侧 div，点击...")
                try:
                    page.run_js("""
var items = document.querySelectorAll('.yKNs6LhU');
for(var i=0;i<items.length;i++){
  var t=(items[i].innerText||'').trim().split('\\n')[0].trim();
  if(t === arguments[0] || arguments[0].indexOf(t) >= 0 || t.indexOf(arguments[0]) >= 0){
    items[i].scrollIntoView({block:'nearest', behavior:'smooth'});
    break;
  }
}
""", fname)
                    time.sleep(0.3)
                except Exception:
                    pass
                target.click()
                _wait_for_click_settle()  # 等浏览器建立请求
            """在收藏夹列表页左侧（li.W4n61X0W）找目标并点击。"""
            if scroll_first:
                try:
                    page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=0;")
                    time.sleep(0.2)
                except Exception:
                    pass
            _drain_stale()
            for scroll_i in range(30):
                target_li = self._find_folder_li(page, fname, log_sample=(scroll_i == 0))
                if target_li:
                    self._log(f"    找到「{fname}」li（第{scroll_i}次滚动后），点击...")
                    target_li.click()
                    _wait_for_click_settle()  # 等浏览器建立请求
                    return True
                try:
                    r = page.run_js(self._SCROLL_LEFT_JS)
                except Exception:
                    break
                time.sleep(0.3)
                _drain_stale()
                parts = str(r).split('/')
                if len(parts) == 3:
                    try:
                        top, sh, ch = int(parts[0]), int(parts[1]), int(parts[2])
                        if top + ch + 100 >= sh:
                            break
                    except Exception:
                        pass
            target_li = self._find_folder_li(page, fname, log_sample=True)
            if target_li:
                self._log(f"    最终找到「{fname}」li，点击...")
                target_li.click()
                _wait_for_click_settle()  # 等浏览器建立请求
                return True
            return False

        # ── 路径1：视频列表页，左侧是 DIV.yKNs6LhU ──
        if self._find_panel_divs(page):
            if _try_click_div(scroll_first=True):
                return
            self._log(f"  左侧 div 未找到「{fname}」，fallback 重新导航 LIST_URL...")
        # ── 路径2：收藏夹列表页，左侧是 li.W4n61X0W ──
        elif self._find_panel_lis(page):
            if _try_click_li(scroll_first=True):
                return
            self._log(f"  li 未找到「{fname}」，fallback 重新导航 LIST_URL...")
        else:
            self._log(f"  左侧面板未找到（div/li 均无），重新导航 LIST_URL...")

        # ── Fallback：重新导航 LIST_URL 后再用 li 点击 ──
        page.get(self.LIST_URL)
        page.wait.doc_loaded(timeout=30)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._find_panel_lis(page):
                break
            time.sleep(0.3)
        try:
            page.run_js("var el=document.querySelector('.route-scroll-container');if(el)el.scrollTop=0;")
            time.sleep(0.1)
        except Exception:
            pass

        if _try_click_li(scroll_first=False):
            return

        self._log(f"  ✗ 未找到「{fname}」（已重新导航仍找不到）")

    def _run_video_sync(self, page, folders=None):  # folders 参数已废弃，内部自行获取最新列表
        """
        全量同步入口：优化版，尽量减少导航次数。

        关键设计依据：
        1. verify_2: listen.start() 的 clear() 丢弃 cursor=0 → listen 必须在导航前开启
        2. verify_1/6: 左侧 li 懒加载，scrolling 触发更多 li 及其 cursor=0 预取
        3. verify_dom: 点击 li 后左侧面板消失（count → 0），无法连续点击同一页面的多个 li
        4. 优化策略：
           - _load_and_drain 单次导航同时拿到收藏夹名单 + 所有视频 cursor=0 预取
           - has_more=False 的收藏夹直接用 prefetch 数据，无需任何导航
           - has_more=True 的收藏夹：_nav_click_folder 优先在视频列表页左侧 DIV.yKNs6LhU
             点击切换（无需重新导航）；若尚未进入视频列表页则用 li.W4n61X0W 点击进入；
             均失败时 fallback 重新导航 LIST_URL
           - 默认收藏：单独导航到 listcollection URL
        """
        import re as _re
        import traceback

        sync_start = time.time()

        # ── 阶段一：单次导航同时获取收藏夹名单 + 所有视频 cursor=0 预取包 ─────────
        # 用宽泛关键字同时捕获 collects/list（名单）和 collects/video/list（视频预取）
        self._log("一次性导航获取收藏夹列表及预取视频数据...")
        page.listen.start("collects")
        fetched_folders, prefetch_all = self._load_and_drain(page)

        if not fetched_folders:
            self._log("❌ 未获取到收藏夹列表，停止"); return page

        default = {"id": "default", "name": "默认收藏", "count": 0, "cover": ""}
        fetched_folders_full = fetched_folders + [default]
        self._log(f"✅ 收藏夹列表：{len(fetched_folders_full)} 个（含默认收藏），{len(prefetch_all)} 个有预取数据")
        self.folders_loaded.emit(fetched_folders_full)  # 更新 UI 进度条/列表/删除标记

        custom_folders  = fetched_folders           # 不含 default
        default_folders = [default]

        # ── 阶段二：逐一同步 ─────────────────────────────────────────────────────
        all_synced = list(custom_folders) + list(default_folders)
        folder_stats = []  # [(fname, video_cnt, elapsed_s, skipped)]

        for i, f in enumerate(all_synced):
            self._wait_if_paused()
            if self._cancelled:
                self._log("已取消同步"); break

            fid = f["id"]; fname = f["name"]
            t0 = time.time()
            self._log(f"[{i+1}/{len(all_synced)}] 同步「{fname}」")

            try:
                if fid == "default":
                    # 默认收藏：单独导航到不同 URL
                    page.listen.start("listcollection")
                    tgt = ("https://www.douyin.com/user/self"
                           "?showSubTab=favorite_collection&showTab=favorite_collection")
                    page.get(tgt)
                    page.wait.doc_loaded(timeout=30)
                    pre = []
                    last_new = time.time()
                    hard_limit = time.time() + 10
                    while time.time() < hard_limit:
                        pkt = page.listen.wait(timeout=0.5)
                        if pkt:
                            try:
                                b = pkt.response.body
                                if isinstance(b, dict) and "aweme_list" in b:
                                    pre.append(b)
                                    last_new = time.time()
                            except Exception:
                                pass
                        elif time.time() - last_new > 2.5:
                            break  # 2.5s 内无新包，认为初始预取完成
                    self._log(f"    默认收藏预取: {len(pre)} 包")
                    videos = self._sync_one(page, fid, fname, prefetch_bodies=pre if pre else None)

                else:
                    # prefetch_all key 由 URL 正则提取，统一用 str 匹配
                    pre = prefetch_all.get(str(fid)) or prefetch_all.get(fid)
                    pre_has_more = bool(pre and any(b.get("has_more") for b in pre))

                    if pre and not pre_has_more:
                        # 预取数据完整（has_more=False），直接用，无需导航
                        self._log(f"    预取完整（has_more=False），跳过导航")
                        # _sync_one 需要在 listen 状态下运行以处理可能的追加包
                        # 这里数据已完整，直接从 prefetch 提取即可
                        videos = self._extract_from_prefetch(fid, fname, pre)
                    else:
                        # has_more=True 或无预取：点击左侧面板切换，触发 cursor=10/20... 分页请求
                        reason = "has_more=True" if pre_has_more else "无预取数据"
                        self._log(f"    {reason}，点击 li 切换...")
                        page.listen.start("collects/video/list")
                        self._nav_click_folder(page, fid, fname)
                        # 阶段一已收到 cursor=0 包，点击后浏览器不会重发 cursor=0，
                        # 直接把阶段一的 pre 作为第一页，后续 cursor=10/20 由 _sync_one 继续收
                        videos = self._sync_one(page, fid, fname, prefetch_bodies=pre or None)

                if self._cancelled:
                    self._log(f"  取消「{fname}」"); break
                elapsed = time.time() - t0
                self._log(f"  ✓ 「{fname}」完成，{len(videos)} 个视频，耗时 {elapsed:.1f}s")
                folder_stats.append((fname, len(videos), elapsed, False))
                self.folder_done.emit(fid, fname, videos)

            except Exception as e:
                elapsed = time.time() - t0
                err_name = type(e).__name__
                if any(k in err_name for k in ("PageDisconnected", "Disconnected", "SessionClosed")):
                    self._log(f"  ⚠ 浏览器断开，正在重新启动...")
                    try:
                        if page: page.quit()
                    except Exception:
                        pass
                    try:
                        page = self._make_page()
                        self._log(f"  ✓ 浏览器已重启，重试「{fname}」...")
                        if fid == "default":
                            page.listen.start("listcollection")
                            tgt = ("https://www.douyin.com/user/self"
                                   "?showSubTab=favorite_collection&showTab=favorite_collection")
                            page.get(tgt)
                            page.wait.doc_loaded(timeout=30)
                            pre = []
                            last_new = time.time()
                            hard_limit = time.time() + 10
                            while time.time() < hard_limit:
                                pkt = page.listen.wait(timeout=0.5)
                                if pkt:
                                    try:
                                        b = pkt.response.body
                                        if isinstance(b, dict) and "aweme_list" in b:
                                            pre.append(b)
                                            last_new = time.time()
                                    except Exception:
                                        pass
                                elif time.time() - last_new > 2.5:
                                    break
                        else:
                            page.listen.start("collects/video/list")
                            self._nav_click_folder(page, fid, fname)
                            # 浏览器重启后 cursor=0 会重新触发，由 _sync_one 的 collect_next_page 收取
                        videos = self._sync_one(page, fid, fname, prefetch_bodies=pre if pre else None)
                        if self._cancelled:
                            self._log(f"  取消「{fname}」"); break
                        elapsed = time.time() - t0
                        self._log(f"  ✓ 「{fname}」完成，{len(videos)} 个视频，耗时 {elapsed:.1f}s（含重启）")
                        folder_stats.append((fname, len(videos), elapsed, False))
                        self.folder_done.emit(fid, fname, videos)
                    except Exception as e2:
                        elapsed = time.time() - t0
                        folder_stats.append((fname, 0, elapsed, True))
                        self._log(f"  ✗ 「{fname}」重试失败: {e2}\n{traceback.format_exc()}")
                else:
                    elapsed = time.time() - t0
                    folder_stats.append((fname, 0, elapsed, True))
                    self._log(f"  ✗ 「{fname}」出错: {e}\n{traceback.format_exc()}")

        total_elapsed = time.time() - sync_start
        total_videos = sum(cnt for _, cnt, _, skipped in folder_stats if not skipped)
        ok_cnt = sum(1 for _, _, _, skipped in folder_stats if not skipped)
        fail_cnt = sum(1 for _, _, _, skipped in folder_stats if skipped)
        if not self._cancelled:
            self._log("─" * 48)
            self._log(f"✅ 全部收藏夹同步完成")
            self._log(f"   总耗时: {total_elapsed:.1f}s  共 {ok_cnt} 个成功 / {fail_cnt} 个失败")
            self._log(f"   合计视频: {total_videos} 个")
            if folder_stats:
                slowest = sorted(folder_stats, key=lambda x: x[2], reverse=True)[:3]
                self._log(f"   最慢收藏夹: " + "  ".join(f"「{n}」{t:.1f}s" for n, _, t, _ in slowest))
        return page

    def _extract_from_prefetch(self, fid, fname, pre):
        """
        从预取数据（cursor=0）直接提取视频，不需要分页。
        仅用于 has_more=False 的收藏夹。
        """
        videos = []; seen_ids = set()
        for body in (pre or []):
            if body.get("status_code", 0) != 0:
                continue
            for aw in (body.get("aweme_list") or []):
                vm = self._parse(aw)
                if vm and vm["aweme_id"] not in seen_ids:
                    vm["folder_id"] = fid
                    videos.append(vm)
                    seen_ids.add(vm["aweme_id"])
        return videos

    def _make_page(self):
        """启动 Chrome 并注入 cookie，返回已登录的 page。"""
        from DrissionPage import ChromiumPage, ChromiumOptions
        subprocess.run(["pkill", "-f", "remote-debugging-port=9334"], capture_output=True)
        time.sleep(0.1)
        opts = ChromiumOptions()
        opts.headless(not self.show_browser)
        opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
        opts.set_user_data_path(os.path.join(os.path.expanduser("~"), ".douyin_drission_profile"))
        opts.set_local_port(9334)
        self._log("正在启动 Chrome...")
        page = ChromiumPage(addr_or_opts=opts)
        self._inject(page, self.cookie_str, self._log)
        return page

    def run(self):
        page = None
        try:
            page = self._make_page()

            if self.mode == "list_only":
                folders = self._fetch_folder_list(page)
                self._log(f"共 {len(folders)} 个收藏夹（含默认收藏）")
                self.folders_loaded.emit(folders)
                if not folders:
                    self._log("未发现收藏夹")
                else:
                    self._log("✅ 收藏夹列表同步完成")

            elif self.mode == "videos_only":
                # _run_video_sync 内部的阶段一会调 _load_and_drain，
                # 它同时拿到最新收藏夹列表 + 视频预取包，只需一次导航
                # 传空 folders，让 _run_video_sync 自行获取最新列表
                page = self._run_video_sync(page, None)

            else:  # "all"
                page = self._run_video_sync(page, None)

        except ImportError:
            self._log("❌ 缺少 DrissionPage")
        except Exception as e:
            import traceback
            self._log(f"出错: {e}\n{traceback.format_exc()}")
        finally:
            try:
                if page: page.quit()
            except Exception: pass
            self.finished.emit()



class FetchWorker(QObject):
    log         = pyqtSignal(str)
    video_found = pyqtSignal(str, str, dict)
    finished    = pyqtSignal(int)

    def __init__(self, function_type, uid, cookie_str, show_browser=False):
        super().__init__()
        self.function_type = function_type
        self.uid = uid; self.cookie_str = cookie_str
        self.show_browser = show_browser

    def run(self):
        total = 0
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill","-f","remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"),".douyin_drission_profile"))
            opts.set_local_port(9334)
            page = ChromiumPage(addr_or_opts=opts)
            cookies = []
            for part in self.cookie_str.split(";"):
                part = part.strip()
                if "=" in part:
                    n, _, v = part.partition("=")
                    n = n.strip(); v = v.strip()
                    if n: cookies.append({"name":n,"value":v,"domain":".douyin.com","path":"/"})
            self.log.emit(f"正在注入 {len(cookies)} 个 Cookie...")
            for ck in cookies:
                try: page.set.cookies(ck)
                except Exception: pass
            self.log.emit("✅ Cookie 注入完成")

            kw  = "aweme/post" if self.function_type == "profile" else "aweme/favorite"
            tgt = (f"https://www.douyin.com/user/{self.uid}" if self.function_type == "profile"
                   else f"https://www.douyin.com/user/{self.uid}?showTab=like")
            page.listen.start(kw); page.get(tgt)
            pn = 1
            while pn <= 200:
                pkt = page.listen.wait(timeout=20)
                if pkt is None: break
                try:
                    body = pkt.response.body
                    if not isinstance(body, dict): continue
                    if body.get("status_code",-1) != 0: break
                    for aw in body.get("aweme_list",[]):
                        aid = aw.get("aweme_id","")
                        if not aid: continue
                        author = aw.get("author",{}).get("nickname","未知")
                        title  = (aw.get("desc","") or "").strip() or f"视频_{aid}"
                        vi = aw.get("video",{})
                        url = None
                        for k in ("play_addr","download_addr"):
                            ul = vi.get(k,{}).get("url_list",[])
                            if ul: url = ul[0]; break
                        if not url: continue
                        if not url.startswith("http"): url = "https:" + url
                        if "&watermark=" in url: url = url.split("&watermark=")[0]
                        self.video_found.emit(f"{author[:8]}_{title[:20]}", url,
                                              {"aweme_id":aid,"author":author,"raw_title":title})
                        total += 1
                    self.log.emit(f"第 {pn} 页，累计 {total}")
                    if not body.get("has_more",False): break
                    page.scroll.to_bottom(); pn += 1
                except Exception as e:
                    self.log.emit(f"解析出错: {e}"); break
            page.listen.stop(); page.quit()
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        self.finished.emit(total)


class MySelfVideoWorker(QObject):
    """同步自己账号的作品/喜欢/历史观看"""
    log           = pyqtSignal(str)
    video_batch   = pyqtSignal(list)
    finished      = pyqtSignal(int)
    cookie_expired = pyqtSignal()

    MODE_URLS = {
        "post":    ("aweme/post",     "https://www.douyin.com/user/self?showTab=post"),
        "like":    ("aweme/favorite", "https://www.douyin.com/user/self?showTab=like"),
        "history": ("history",        "https://www.douyin.com/user/self?showTab=history"),
    }

    def __init__(self, mode, cookie_str, limit=100, show_browser=False):
        super().__init__()
        self.mode = mode
        self.cookie_str = cookie_str
        self.limit = limit
        self.show_browser = show_browser
        self._paused = False
        self._cancelled = False

    def pause(self):   self._paused = True
    def resume(self):  self._paused = False
    def cancel(self):  self._cancelled = True; self._paused = False

    def _wait_if_paused(self):
        while self._paused and not self._cancelled:
            time.sleep(0.2)

    @staticmethod
    def _inject(page, cookie_str, log_fn=None):
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                n, _, v = part.partition("=")
                n = n.strip(); v = v.strip()
                if n:
                    cookies.append({"name": n, "value": v, "domain": ".douyin.com", "path": "/"})
        if log_fn:
            log_fn(f"正在注入 {len(cookies)} 个 Cookie...")
        # 必须先导航到 douyin 域名才能让 set.cookies 生效（空白页注入被浏览器忽略）
        try:
            if not page.url or not page.url.startswith("https://"):
                page.get("https://www.douyin.com/favicon.ico")
                page.wait.doc_loaded(timeout=10)
        except Exception:
            pass
        for ck in cookies:
            try: page.set.cookies(ck)
            except Exception: pass
        if log_fn:
            log_fn("✅ Cookie 注入完成")

    @staticmethod
    def _parse_aweme(aweme):
        aid = aweme.get("aweme_id", "")
        if not aid: return None
        title  = (aweme.get("desc", "") or "").strip() or f"视频_{aid}"
        author = aweme.get("author", {}).get("nickname", "未知")
        vi  = aweme.get("video", {})
        url = None
        for k in ("play_addr", "download_addr"):
            ul = vi.get(k, {}).get("url_list", [])
            if ul: url = ul[0]; break
        if not url:
            for br in vi.get("bit_rate", []):
                ul = br.get("play_addr", {}).get("url_list", [])
                if ul: url = ul[0]; break
        if not url: return None
        if not url.startswith("http"): url = "https:" + url
        if "&watermark=" in url: url = url.split("&watermark=")[0]
        cover = vi.get("cover", {}).get("url_list", [""])[0]
        dur = int(vi.get("duration", 0) or aweme.get("duration", 0))
        return {"aweme_id": aid, "title": title, "author": author, "url": url,
                "cover_url": cover, "duration": dur, "synced_at": time.time()}

    def run(self):
        total = 0
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill", "-f", "remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"), ".douyin_drission_profile"))
            opts.set_local_port(9334)
            page = ChromiumPage(addr_or_opts=opts)
            self._inject(page, self.cookie_str, self.log.emit)
            kw, url = self.MODE_URLS.get(self.mode, ("aweme/post", "https://www.douyin.com/user/self?showTab=post"))
            limit_desc = f"前 {self.limit} 个" if self.limit else "全部"
            self.log.emit(f"开始同步「{self.mode}」（{limit_desc}），导航中...")
            page.listen.start(kw)
            page.get(url)
            pn = 1
            while pn <= 300:
                if self._cancelled:
                    self.log.emit("🛑 已取消"); break
                self._wait_if_paused()
                if self._cancelled:
                    self.log.emit("🛑 已取消"); break
                pkt = page.listen.wait(timeout=20)
                if not pkt:
                    self.log.emit("超时，停止"); break
                try:
                    body = pkt.response.body
                    if not isinstance(body, dict): continue
                    status = body.get("status_code", -1)
                    if status == 8:
                        self.log.emit("⚠️ Cookie 已过期"); self.cookie_expired.emit(); break
                    if status != 0: break
                    batch = [self._parse_aweme(aw) for aw in body.get("aweme_list", [])]
                    batch = [v for v in batch if v]
                    # enforce limit
                    if self.limit and total + len(batch) >= self.limit:
                        batch = batch[:max(0, self.limit - total)]
                        if batch:
                            self.video_batch.emit(batch); total += len(batch)
                        self.log.emit(f"已达到同步上限 {self.limit} 个，停止")
                        break
                    if batch:
                        self.video_batch.emit(batch); total += len(batch)
                    self.log.emit(f"第 {pn} 页，累计 {total} 个")
                    if not body.get("has_more", False): break
                    page.scroll.to_bottom(); pn += 1
                except Exception as e:
                    self.log.emit(f"解析出错: {e}"); break
            try: page.listen.stop(); page.quit()
            except Exception: pass
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        self.finished.emit(total)


class UserVideoWorker(QObject):
    """抓取指定用户的作品/喜欢，包含用户信息"""
    log        = pyqtSignal(str)
    user_info  = pyqtSignal(dict)
    video_batch = pyqtSignal(list)
    finished   = pyqtSignal(int)

    def __init__(self, mode, uid, cookie_str, show_browser=False):
        super().__init__()
        self.mode = mode; self.uid = uid; self.cookie_str = cookie_str
        self.show_browser = show_browser

    @staticmethod
    def _inject(page, cookie_str, log_fn=None):
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                n, _, v = part.partition("=")
                n = n.strip(); v = v.strip()
                if n:
                    cookies.append({"name": n, "value": v, "domain": ".douyin.com", "path": "/"})
        if log_fn:
            log_fn(f"正在注入 {len(cookies)} 个 Cookie...")
        # 必须先导航到 douyin 域名才能让 set.cookies 生效（空白页注入被浏览器忽略）
        try:
            if not page.url or not page.url.startswith("https://"):
                page.get("https://www.douyin.com/favicon.ico")
                page.wait.doc_loaded(timeout=10)
        except Exception:
            pass
        for ck in cookies:
            try: page.set.cookies(ck)
            except Exception: pass

    @staticmethod
    def _parse_aweme(aweme):
        aid = aweme.get("aweme_id", "")
        if not aid: return None
        title  = (aweme.get("desc", "") or "").strip() or f"视频_{aid}"
        author = aweme.get("author", {}).get("nickname", "未知")
        vi  = aweme.get("video", {})
        url = None
        for k in ("play_addr", "download_addr"):
            ul = vi.get(k, {}).get("url_list", [])
            if ul: url = ul[0]; break
        if not url:
            for br in vi.get("bit_rate", []):
                ul = br.get("play_addr", {}).get("url_list", [])
                if ul: url = ul[0]; break
        if not url: return None
        if not url.startswith("http"): url = "https:" + url
        if "&watermark=" in url: url = url.split("&watermark=")[0]
        cover = vi.get("cover", {}).get("url_list", [""])[0]
        dur = int(vi.get("duration", 0) or aweme.get("duration", 0))
        return {"aweme_id": aid, "title": title, "author": author, "url": url,
                "cover_url": cover, "duration": dur, "synced_at": time.time()}

    def run(self):
        total = 0
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill", "-f", "remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"), ".douyin_drission_profile"))
            opts.set_local_port(9334)
            page = ChromiumPage(addr_or_opts=opts)
            self._inject(page, self.cookie_str, self.log.emit)

            kw = "aweme/post" if self.mode == "post" else "aweme/favorite"
            tgt_url = (f"https://www.douyin.com/user/{self.uid}" if self.mode == "post"
                       else f"https://www.douyin.com/user/{self.uid}?showTab=like")

            # 一次导航同时捕获用户信息包和视频列表包
            self.log.emit(f"正在获取用户信息及{'作品' if self.mode == 'post' else '喜欢'}列表...")
            page.listen.start("aweme")  # 宽关键词：同时匹配 user/profile/other 和 aweme/post/favorite
            page.get(tgt_url)

            got_user_info = False
            pn = 1
            while pn <= 300:
                pkt = page.listen.wait(timeout=20)
                if not pkt:
                    self.log.emit("超时，停止"); break
                try:
                    pkt_url = getattr(pkt, "url", "") or ""
                    body = pkt.response.body
                    if not isinstance(body, dict): continue

                    # 用户信息包
                    if not got_user_info and "user/profile/other" in pkt_url:
                        u = body.get("user", {})
                        if u:
                            user_info = {
                                "uid": self.uid,
                                "nickname": u.get("nickname", self.uid),
                                "unique_id": u.get("unique_id", ""),
                                "signature": u.get("signature", ""),
                                "avatar_url": (u.get("avatar_larger", {}).get("url_list") or
                                              u.get("avatar_medium", {}).get("url_list") or [""])[0],
                                "follower_count": u.get("follower_count", 0),
                                "following_count": u.get("following_count", 0),
                                "aweme_count": u.get("aweme_count", 0),
                                "synced_at": time.time(),
                            }
                            self.user_info.emit(user_info)
                            self.log.emit(f"用户：{user_info['nickname']}")
                            got_user_info = True
                        continue

                    # 视频列表包
                    if kw not in pkt_url: continue
                    if body.get("status_code", -1) != 0: break
                    batch = [self._parse_aweme(aw) for aw in body.get("aweme_list", [])]
                    batch = [v for v in batch if v]
                    if batch:
                        self.video_batch.emit(batch); total += len(batch)
                    self.log.emit(f"第 {pn} 页，累计 {total} 个")
                    if not body.get("has_more", False): break
                    page.scroll.to_bottom(); pn += 1
                except Exception as e:
                    self.log.emit(f"解析出错: {e}"); break

            if not got_user_info:
                self.log.emit("未捕获到用户信息包（超时）")
            try: page.listen.stop(); page.quit()
            except Exception: pass
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        self.finished.emit(total)


class SelfNicknameWorker(QObject):
    """用 requests 轻量获取登录账号昵称，不启动浏览器"""
    nickname_ready = pyqtSignal(str)   # 昵称
    finished       = pyqtSignal()

    def __init__(self, cookie_str):
        super().__init__()
        self.cookie_str = cookie_str

    def run(self):
        try:
            cookies = {}
            for part in self.cookie_str.split(";"):
                part = part.strip()
                if "=" in part:
                    n, _, v = part.partition("=")
                    n = n.strip(); v = v.strip()
                    if n:
                        cookies[n] = v
            hdrs = {
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/125.0.0.0 Safari/537.36"),
                "Referer": "https://www.douyin.com/",
            }
            url = ("https://www.douyin.com/aweme/v1/web/user/profile/self/"
                   "?device_platform=webapp&aid=6383&channel=channel_pc_web")
            resp = requests.get(url, headers=hdrs, cookies=cookies, timeout=10)
            data = resp.json()
            u = data.get("user", {})
            nick = u.get("nickname", "").strip()
            if nick:
                self.nickname_ready.emit(nick)
        except Exception:
            pass
        self.finished.emit()


class UserInfoWorker(QObject):
    """仅抓取用户信息（昵称/签名/粉丝数等），不同步视频"""
    log       = pyqtSignal(str)
    user_info = pyqtSignal(dict)
    finished  = pyqtSignal()

    def __init__(self, uid, cookie_str, show_browser=False):
        super().__init__()
        self.uid = uid
        self.cookie_str = cookie_str
        self.show_browser = show_browser

    def run(self):
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill", "-f", "remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"), ".douyin_drission_profile"))
            opts.set_local_port(9334)
            page = ChromiumPage(addr_or_opts=opts)
            cookies = []
            for part in self.cookie_str.split(";"):
                part = part.strip()
                if "=" in part:
                    n, _, v = part.partition("=")
                    n = n.strip(); v = v.strip()
                    if n:
                        cookies.append({"name": n, "value": v, "domain": ".douyin.com", "path": "/"})
            self.log.emit(f"正在注入 {len(cookies)} 个 Cookie...")
            for ck in cookies:
                try: page.set.cookies(ck)
                except Exception: pass
            self.log.emit("✅ Cookie 注入完成")
            self.log.emit(f"正在获取用户信息 UID={self.uid[:20]}...")
            page.listen.start("user/profile/other")
            page.get(f"https://www.douyin.com/user/{self.uid}")
            pkt = page.listen.wait(timeout=15)
            if pkt:
                try:
                    b = pkt.response.body
                    if isinstance(b, dict):
                        u = b.get("user", {})
                        if u:
                            info = {
                                "uid": self.uid,
                                "nickname": u.get("nickname", self.uid),
                                "unique_id": u.get("unique_id", ""),
                                "signature": u.get("signature", ""),
                                "avatar_url": (u.get("avatar_larger", {}).get("url_list") or
                                               u.get("avatar_medium", {}).get("url_list") or [""])[0],
                                "follower_count": u.get("follower_count", 0),
                                "following_count": u.get("following_count", 0),
                                "aweme_count": u.get("aweme_count", 0),
                                "synced_at": time.time(),
                            }
                            self.user_info.emit(info)
                            self.log.emit(f"✅ 用户信息已更新：{info['nickname']}")
                except Exception as e:
                    self.log.emit(f"用户信息解析失败: {e}")
            else:
                self.log.emit("⚠️ 未捕获到用户信息包（超时）")
            try: page.listen.stop(); page.quit()
            except Exception: pass
        except Exception as e:
            import traceback
            self.log.emit(f"出错: {e}\n{traceback.format_exc()}")
        self.finished.emit()


def _make_circle_pixmap(pixmap, size):
    """Crop-scale pixmap to a circle of given diameter."""
    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    cropped = scaled.copy(x, y, size, size)
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(cropped))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return result


class UserListItemWidget(QWidget):
    """用户列表行 widget：圆形头像 + 昵称 + 抖音号 + 粉丝/关注。"""
    AVATAR_SIZE = 52

    def __init__(self, uid, nickname, parent=None):
        super().__init__(parent)
        self.uid = uid
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6); lay.setSpacing(10)

        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
        self._set_placeholder()
        lay.addWidget(self.avatar_lbl, 0, Qt.AlignTop)

        text_lay = QVBoxLayout(); text_lay.setSpacing(2); text_lay.setContentsMargins(0,0,0,0)

        self.name_lbl = QLabel(nickname)
        self.name_lbl.setStyleSheet("font-size:13pt;font-weight:700;")
        fm = self.name_lbl.fontMetrics()
        self.name_lbl.setText(fm.elidedText(nickname, Qt.ElideRight, 148))
        text_lay.addWidget(self.name_lbl)

        self.uid_lbl = QLabel("抖音号：—")
        self.uid_lbl.setObjectName("userListSub")
        self.uid_lbl.setStyleSheet("font-size:10pt;")
        text_lay.addWidget(self.uid_lbl)

        self.stats_lbl = QLabel("")
        self.stats_lbl.setObjectName("userListSub")
        self.stats_lbl.setStyleSheet("font-size:10pt;")
        text_lay.addWidget(self.stats_lbl)

        text_lay.addStretch()
        lay.addLayout(text_lay, 1)

    def _set_placeholder(self):
        s = self.AVATAR_SIZE
        ph = QPixmap(s, s); ph.fill(Qt.transparent)
        painter = QPainter(ph)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#555")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, s, s)
        painter.setPen(QPen(QColor("#999")))
        painter.setFont(self.font())
        painter.drawText(ph.rect(), Qt.AlignCenter, "?")
        painter.end()
        self.avatar_lbl.setPixmap(ph)

    def set_avatar(self, pixmap):
        self.avatar_lbl.setPixmap(_make_circle_pixmap(pixmap, self.AVATAR_SIZE))

    def set_nickname(self, nickname):
        fm = self.name_lbl.fontMetrics()
        self.name_lbl.setText(fm.elidedText(nickname, Qt.ElideRight, 148))

    def set_unique_id(self, unique_id):
        if unique_id:
            self.uid_lbl.setText(f"抖音号：{unique_id}")
        else:
            self.uid_lbl.setText("抖音号：—")

    def set_stats(self, follower_count=0, following_count=0):
        def _fmt(n):
            if n >= 10000:
                return f"{n/10000:.1f}w"
            return str(n)
        if follower_count or following_count:
            self.stats_lbl.setText(f"粉丝 {_fmt(follower_count)}  关注 {_fmt(following_count)}")
        else:
            self.stats_lbl.setText("")


class ParseHistoryCard(QFrame):
    """解析列表行：封面 + 标题/作者/时间 + 操作按钮行"""
    preview_requested  = pyqtSignal(str)
    download_requested = pyqtSignal(dict)
    delete_requested   = pyqtSignal(str)

    COVER_W, COVER_H = 60, 80

    def __init__(self, record, save_dir, parent=None):
        super().__init__(parent)
        self.record   = record
        self.save_dir = save_dir
        self._local_path = None
        # 列表行样式：无边框，悬停高亮，底部细分割线
        self.setStyleSheet(
            "ParseHistoryCard{background:transparent;border:none;"
            "border-bottom:1px solid #252525;}"
            "ParseHistoryCard:hover{background:#1c1c1c;}")
        self.setFixedHeight(96)
        self.setCursor(Qt.ArrowCursor)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(14)

        # 封面
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(self.COVER_W, self.COVER_H)
        self.cover_lbl.setAlignment(Qt.AlignCenter)
        self.cover_lbl.setText("⏳")
        self.cover_lbl.setStyleSheet(
            "background:#1a1a1a;border-radius:4px;color:#555;font-size:9pt;"
            "border:1px solid #2a2a2a;")
        outer.addWidget(self.cover_lbl)

        # 文字信息列
        info_lay = QVBoxLayout(); info_lay.setSpacing(2); info_lay.setContentsMargins(0,0,0,0)

        title = record.get("title", "") or "无标题"
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-size:11pt;font-weight:bold;")
        self.title_lbl.setMaximumWidth(9999)
        fm = self.title_lbl.fontMetrics()
        self.title_lbl.setText(fm.elidedText(title, Qt.ElideRight, 520))
        info_lay.addWidget(self.title_lbl)

        author = record.get("author", "")
        self.author_lbl = QLabel(f"@{author}" if author else "")
        self.author_lbl.setStyleSheet("color:#888;font-size:9pt;")
        info_lay.addWidget(self.author_lbl)

        parsed_at = record.get("parsed_at", 0)
        ts_str = datetime.fromtimestamp(parsed_at).strftime("%Y-%m-%d %H:%M") if parsed_at else ""
        self.time_lbl = QLabel(ts_str)
        self.time_lbl.setStyleSheet("color:#555;font-size:9pt;")
        info_lay.addWidget(self.time_lbl)

        info_lay.addStretch()
        outer.addLayout(info_lay, 1)

        # 操作按钮（垂直居中，水平排列）
        act_lay = QHBoxLayout(); act_lay.setSpacing(6); act_lay.setContentsMargins(0,0,0,0)
        act_lay.setAlignment(Qt.AlignVCenter)

        self.prev_btn = QPushButton("▶ 预览")
        self.prev_btn.setFixedSize(76, 28)
        self.prev_btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;border-radius:5px;"
            "font-size:9pt;font-weight:bold;}"
            "QPushButton:hover{background:#1976d2;}"
            "QPushButton:disabled{background:#252525;color:#555;border:1px solid #333;}")
        self.prev_btn.clicked.connect(self._on_prev)
        act_lay.addWidget(self.prev_btn)

        self.dl_btn = QPushButton("⬇ 下载")
        self.dl_btn.setFixedSize(76, 28)
        self.dl_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border:none;border-radius:5px;"
            "font-size:9pt;font-weight:bold;}"
            "QPushButton:hover{background:#388e3c;}"
            "QPushButton:disabled{background:#1b5e20;color:#aaa;}")
        self.dl_btn.clicked.connect(self._on_dl)
        act_lay.addWidget(self.dl_btn)

        self.menu_lbl = QLabel("⋮")
        self.menu_lbl.setFixedSize(24, 28)
        self.menu_lbl.setAlignment(Qt.AlignCenter)
        self.menu_lbl.setStyleSheet(
            "color:#555;font-size:15pt;background:transparent;")
        self.menu_lbl.setCursor(Qt.PointingHandCursor)
        self.menu_lbl.installEventFilter(self)
        act_lay.addWidget(self.menu_lbl)

        outer.addLayout(act_lay)

        self._refresh()

        cover_url = record.get("cover_url", "")
        if cover_url:
            ldr = CoverLoader(record["aweme_id"], cover_url)
            ldr.loaded.connect(self._on_cover)
            ldr.start()
            _active_loaders.add(ldr)

    def _refresh(self):
        lp = get_local_video_path(self.record["aweme_id"], self.save_dir)
        self._local_path = lp
        if lp:
            self.dl_btn.setText("已下载")
            self.dl_btn.setStyleSheet(
                "QPushButton{background:#2e7d32;color:white;border:none;border-radius:5px;"
                "font-size:9pt;font-weight:bold;}")
            self.dl_btn.setEnabled(False)
            self.prev_btn.setEnabled(True)
        else:
            self.dl_btn.setText("⬇ 下载")
            self.dl_btn.setStyleSheet(
                "QPushButton{background:#2e7d32;color:white;border:none;border-radius:5px;"
                "font-size:9pt;font-weight:bold;}"
                "QPushButton:hover{background:#388e3c;}")
            self.dl_btn.setEnabled(True)
            self.prev_btn.setEnabled(False)

    def mark_downloaded(self, path):
        self._local_path = path
        self.dl_btn.setText("已下载")
        self.dl_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border:none;border-radius:5px;"
            "font-size:9pt;font-weight:bold;}")
        self.dl_btn.setEnabled(False)
        self.prev_btn.setEnabled(True)

    def _on_cover(self, _, pix):
        s = pix.scaled(self.COVER_W, self.COVER_H,
                       Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        c = s.copy((s.width()-self.COVER_W)//2, (s.height()-self.COVER_H)//2,
                   self.COVER_W, self.COVER_H)
        self.cover_lbl.setPixmap(c)

    def _on_prev(self):
        if self._local_path and os.path.exists(self._local_path):
            iina = "/Applications/IINA.app/Contents/MacOS/iina-cli"
            if os.path.exists(iina):
                subprocess.Popen([iina, "--keep-running", self._local_path])
            else:
                subprocess.Popen(["open", self._local_path])

    def _on_dl(self):
        meta = {
            "aweme_id": self.record.get("aweme_id", ""),
            "title":    self.record.get("title", ""),
            "url":      self.record.get("url", ""),
            "author":   self.record.get("author", ""),
        }
        self.download_requested.emit(meta)
        self.dl_btn.setText("排队中")

    def eventFilter(self, obj, event):
        if obj is self.menu_lbl and event.type() == event.MouseButtonPress:
            self._on_menu()
            return True
        return super().eventFilter(obj, event)

    def _on_menu(self):
        menu = QMenu(self)
        del_act = menu.addAction("删除记录")
        del_act.triggered.connect(
            lambda: self.delete_requested.emit(self.record.get("aweme_id", "")))
        menu.addSeparator()
        local_path = getattr(self, "_local_path", "") or ""
        if local_path and os.path.exists(local_path):
            dir_act = menu.addAction("打开视频文件目录")
            _dp = os.path.dirname(local_path)
            dir_act.triggered.connect(lambda: subprocess.Popen(["open", _dp]))
        cover_url = self.record.get("cover_url", "")
        video_url = self.record.get("url", "")
        if cover_url:
            cp_cover = menu.addAction("复制封面链接")
            cp_cover.triggered.connect(lambda: QApplication.clipboard().setText(cover_url))
        if video_url:
            cp_video = menu.addAction("复制视频链接")
            cp_video.triggered.connect(lambda: QApplication.clipboard().setText(video_url))
        raw_content = self.record.get("raw_content", "") or self.record.get("share_text", "") or self.record.get("aweme_id", "")
        if raw_content:
            cp_raw = menu.addAction("复制解析前内容")
            cp_raw.triggered.connect(lambda: QApplication.clipboard().setText(raw_content))
        menu.exec_(self.menu_lbl.mapToGlobal(self.menu_lbl.rect().bottomLeft()))


class ShareLinkParser(QObject):
    """解析抖音分享文本中的短链接，提取视频信息。

    流程：
      1. 正则提取 v.douyin.com/xxx 短链
      2. HEAD 请求（移动 UA）→ 302 Location 包含 /video/{aweme_id}/
      3. GET douyin.com/video/{aweme_id}（Googlebot UA）→ JSON-LD 提取
         title / author / cover（无需 Cookie）
      4. DrissionPage + Cookie → 监听 aweme/detail 获取下载 URL
    """
    result  = pyqtSignal(dict)   # {aweme_id, title, author, url, cover_url, duration}
    failed  = pyqtSignal(str)
    log     = pyqtSignal(str)

    _MOB_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
               "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
    _BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    _PC_UA  = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    def __init__(self, share_text, cookie_str=""):
        super().__init__()
        self.share_text = share_text
        self.cookie_str = cookie_str

    # ── 提取短链 ────────────────────────────────────────────────────
    @staticmethod
    def _extract_short_url(text):
        for pattern in (r'https?://v\.douyin\.com/\S+',
                        r'https?://\S*iesdouyin\.com/\S+'):
            m = re.search(pattern, text)
            if m:
                return m.group(0).rstrip("）)，,。.！! \n\r")
        return None

    # ── Step 1: HEAD 短链 → aweme_id（无 Cookie）─────────────────────
    def _resolve_aweme_id(self, short_url):
        try:
            r = requests.head(short_url,
                              headers={"User-Agent": self._MOB_UA},
                              allow_redirects=False, timeout=8)
            loc = r.headers.get("Location", "")
            self.log.emit(f"重定向: {loc[:80]}")
            m = re.search(r'/video/(\d{15,20})', loc)
            if m: return m.group(1)
        except Exception as e:
            self.log.emit(f"HEAD 请求失败: {e}")
        # 回退：GET 跟重定向，从最终 URL 或响应体提取
        try:
            r = requests.get(short_url,
                             headers={"User-Agent": self._MOB_UA},
                             allow_redirects=True, timeout=10)
            m = re.search(r'/video/(\d{15,20})', r.url)
            if m: return m.group(1)
            m = re.search(r'/video/(\d{15,20})', r.text)
            if m: return m.group(1)
        except Exception as e:
            self.log.emit(f"GET 跟踪失败: {e}")
        return None

    # ── Step 2: Googlebot GET → JSON-LD（无 Cookie）─────────────────
    def _fetch_metadata_jsonld(self, aweme_id):
        url = f"https://www.douyin.com/video/{aweme_id}"
        try:
            r = requests.get(url, headers={"User-Agent": self._BOT_UA,
                                           "Referer": "https://www.google.com/"},
                             timeout=10)
            # 所有 JSON-LD 块
            blocks = re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                r.text, re.DOTALL)
            for raw in blocks:
                try:
                    obj = json.loads(raw)
                    # 找 VideoObject
                    if obj.get("@type") != "VideoObject": continue
                    title  = obj.get("name", "")
                    author = obj.get("creator", {}).get("name", "") if isinstance(obj.get("creator"), dict) else ""
                    thumbs = obj.get("thumbnailUrl", [])
                    cover  = thumbs[0] if thumbs else ""
                    # duration: PT0H0M43S → ms
                    dur_iso = obj.get("duration", "")
                    dur = 0
                    dm = re.match(r'PT(\d+)H(\d+)M(\d+)S', dur_iso)
                    if dm:
                        h, mn, s = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
                        dur = (h * 3600 + mn * 60 + s) * 1000
                    return {"aweme_id": aweme_id, "title": title, "author": author,
                            "cover_url": cover, "duration": dur, "url": None}
                except Exception:
                    continue
        except Exception as e:
            self.log.emit(f"JSON-LD 获取失败: {e}")
        return None

    # ── Step 3: DrissionPage + Cookie → 下载 URL ────────────────────
    def _fetch_download_url(self, aweme_id, partial_meta):
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            subprocess.run(["pkill", "-f", "remote-debugging-port=9334"], capture_output=True)
            time.sleep(0.1)
            opts = ChromiumOptions()
            opts.headless(not self.show_browser)
            opts.set_argument("--no-sandbox"); opts.set_argument("--disable-gpu")
            opts.set_user_data_path(os.path.join(os.path.expanduser("~"), ".douyin_drission_profile"))
            opts.set_local_port(9334)
            page = ChromiumPage(addr_or_opts=opts)
            if self.cookie_str:
                ck_count = 0
                for part in self.cookie_str.split(";"):
                    part = part.strip()
                    if "=" in part:
                        n, _, v = part.partition("=")
                        if n.strip():
                            try:
                                page.set.cookies({"name": n.strip(), "value": v.strip(),
                                                  "domain": ".douyin.com", "path": "/"})
                                ck_count += 1
                            except Exception: pass
                self.log.emit(f"正在注入 {ck_count} 个 Cookie...")
                self.log.emit("✅ Cookie 注入完成")
            self.log.emit("浏览器获取下载链接中...")
            # 监听 feed 或 detail 接口
            for kw in ("aweme/v1/feed", "aweme/detail", "aweme/post"):
                page.listen.start(kw)
                page.get(f"https://www.douyin.com/video/{aweme_id}")
                pkt = page.listen.wait(timeout=12)
                page.listen.stop()
                if not pkt: continue
                try:
                    body = pkt.response.body
                    if not isinstance(body, dict): continue
                    aweme_list = body.get("aweme_list") or []
                    if aweme_list:
                        aw = aweme_list[0]
                    elif body.get("aweme_detail"):
                        aw = body["aweme_detail"]
                    else:
                        continue
                    vi = aw.get("video", {})
                    dl_url = None
                    for k in ("play_addr", "download_addr"):
                        ul = vi.get(k, {}).get("url_list", [])
                        if ul: dl_url = ul[0]; break
                    if not dl_url:
                        for br in vi.get("bit_rate", []):
                            ul = br.get("play_addr", {}).get("url_list", [])
                            if ul: dl_url = ul[0]; break
                    if dl_url:
                        if not dl_url.startswith("http"): dl_url = "https:" + dl_url
                        if "&watermark=" in dl_url: dl_url = dl_url.split("&watermark=")[0]
                        # 用 API 返回的 title/author 覆盖 JSON-LD（更准确）
                        api_title = (aw.get("desc", "") or "").strip()
                        api_author = aw.get("author", {}).get("nickname", "")
                        partial_meta.update({
                            "url": dl_url,
                            "title": api_title or partial_meta.get("title", ""),
                            "author": api_author or partial_meta.get("author", ""),
                        })
                        try: page.quit()
                        except Exception: pass
                        return partial_meta
                except Exception as e:
                    self.log.emit(f"包解析出错({kw}): {e}")
            try: page.quit()
            except Exception: pass
        except Exception as e:
            import traceback
            self.log.emit(f"浏览器失败: {e}\n{traceback.format_exc()}")
        return None

    def run(self):
        short_url = self._extract_short_url(self.share_text)
        if not short_url:
            self.failed.emit("未在输入中找到抖音分享链接（v.douyin.com/...）"); return
        self.log.emit(f"解析短链：{short_url}")

        # Step 1
        aweme_id = self._resolve_aweme_id(short_url)
        if not aweme_id:
            self.failed.emit("无法从重定向 URL 提取视频 ID，请确认链接有效"); return
        self.log.emit(f"aweme_id = {aweme_id}")

        # Step 2：无 Cookie 获取元数据
        meta = self._fetch_metadata_jsonld(aweme_id)
        if meta:
            self.log.emit(f"标题：{meta['title'][:40]}  作者：{meta['author']}")
        else:
            meta = {"aweme_id": aweme_id, "title": f"视频_{aweme_id}",
                    "author": "", "cover_url": "", "duration": 0, "url": None}

        # Step 3：需要 Cookie 获取下载 URL
        self.log.emit("正在获取下载链接（需要登录）...")
        result = self._fetch_download_url(aweme_id, meta)
        if result and result.get("url"):
            self.result.emit(result)
        else:
            self.failed.emit("获取下载链接失败，请确认已登录（Cookie 有效）")


class AvatarLoader(QThread):
    """异步加载头像图片"""
    loaded = pyqtSignal(str, QPixmap)  # uid, pixmap

    def __init__(self, uid, url):
        super().__init__()
        self.uid = uid; self.url = url
        _active_loaders.add(self)
        self.finished.connect(lambda: _active_loaders.discard(self))

    def run(self):
        try:
            r = requests.get(self.url, timeout=8,
                             headers={"Referer": "https://www.douyin.com/",
                                      "User-Agent": "Mozilla/5.0"})
            if self.isInterruptionRequested(): return
            if r.status_code == 200:
                pix = QPixmap(); pix.loadFromData(QByteArray(r.content))
                if not pix.isNull() and not self.isInterruptionRequested():
                    self.loaded.emit(self.uid, pix)
        except Exception:
            pass

class AutoScrollListWidget(QListWidget):
    """拖拽时靠近边缘自动滚动，每次滚动约可见条数的 55%，避免滚太多。"""
    _SCROLL_ZONE = 40   # 触发区域（像素）
    _INTERVAL    = 300  # 每次触发间隔（ms），慢一点防止过冲

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(self._INTERVAL)
        self._scroll_timer.timeout.connect(self._do_scroll)
        self._scroll_dir = 0

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        y = event.pos().y()
        h = self.viewport().height()
        if y < self._SCROLL_ZONE:
            self._scroll_dir = -1
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        elif y > h - self._SCROLL_ZONE:
            self._scroll_dir = 1
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        else:
            self._scroll_dir = 0
            self._scroll_timer.stop()

    def dragLeaveEvent(self, event):
        self._scroll_timer.stop()
        self._scroll_dir = 0
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._scroll_timer.stop()
        self._scroll_dir = 0
        super().dropEvent(event)

    def _do_scroll(self):
        bar = self.verticalScrollBar()
        # 用第一个可见 item 的高度估算行高，算出可见行数，滚动 55%
        item_h = self.sizeHintForRow(0) if self.count() > 0 else 60
        if item_h <= 0:
            item_h = 60
        visible_rows = max(1, self.viewport().height() // item_h)
        step = max(1, int(visible_rows * 0.55)) * item_h
        bar.setValue(bar.value() + self._scroll_dir * step)

class DlBtn(QPushButton):
    def __init__(self, text, tid): super().__init__(text); self.tid = tid


# ═════════════════════════════════════════════════════════════════════════════
# 设置对话框
# ═════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    theme_changed        = pyqtSignal(str)
    concurrent_changed   = pyqtSignal(int)
    sync_limits_changed  = pyqtSignal(int, int)  # post, like
    show_browser_changed = pyqtSignal(bool)

    def __init__(self, current_theme, current_concurrent,
                 post_limit, like_limit, show_browser=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(460, 470)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(20, 16, 20, 16)

        # ══ 面板: 通用 ══════════════════════════════════════════════
        gen_box = QGroupBox("通用")
        gen_box.setStyleSheet("QGroupBox{font-weight:bold;font-size:10pt;padding-top:8px;}")
        gen_lay = QVBoxLayout(gen_box)
        gen_lay.setSpacing(10)

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("界面主题")
        theme_lbl.setFixedWidth(130)
        self._theme_cb = QComboBox()
        self._theme_cb.addItems(list(THEMES.keys()))
        idx = list(THEMES.keys()).index(current_theme) if current_theme in THEMES else 0
        self._theme_cb.setCurrentIndex(idx)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_cb, 1)
        gen_lay.addLayout(theme_row)

        conc_row = QHBoxLayout()
        conc_lbl = QLabel("最大同时下载")
        conc_lbl.setFixedWidth(130)
        self._conc_spin = QSpinBox()
        self._conc_spin.setRange(1, 10)
        self._conc_spin.setValue(current_concurrent)
        self._conc_spin.setSuffix(" 个")
        self._conc_slider = QSlider(Qt.Horizontal)
        self._conc_slider.setRange(1, 10)
        self._conc_slider.setValue(current_concurrent)
        self._conc_slider.setTickPosition(QSlider.TicksBelow)
        self._conc_slider.setTickInterval(1)
        self._conc_spin.valueChanged.connect(self._conc_slider.setValue)
        self._conc_slider.valueChanged.connect(self._conc_spin.setValue)
        conc_row.addWidget(conc_lbl)
        conc_row.addWidget(self._conc_slider, 1)
        conc_row.addWidget(self._conc_spin)
        gen_lay.addLayout(conc_row)
        hint_conc = QLabel("并发数越多，网络占用越高（建议 3）")
        hint_conc.setStyleSheet("color:#888;font-size:9pt;")
        gen_lay.addWidget(hint_conc)

        self._show_browser_chk = QCheckBox("自动化爬取时显示浏览器窗口")
        self._show_browser_chk.setChecked(show_browser)
        self._show_browser_chk.setToolTip(
            "勾选后爬取时可见 Chrome 窗口（方便调试）；\n"
            "不勾选则以无头模式运行，速度更快、不干扰使用。")
        gen_lay.addWidget(self._show_browser_chk)

        lay.addWidget(gen_box)

        # ══ 面板: 我的 — 同步设置 ═══════════════════════════════════
        sync_box = QGroupBox("我的 — 同步设置")
        sync_box.setStyleSheet("QGroupBox{font-weight:bold;font-size:10pt;padding-top:8px;}")
        sync_lay = QVBoxLayout(sync_box)
        sync_lay.setSpacing(10)

        def _limit_row(label, value, tooltip):
            row = QHBoxLayout()
            lbl = QLabel(label); lbl.setFixedWidth(130)
            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(value)
            spin.setSuffix("  个")
            spin.setSpecialValueText("不限")
            spin.setFixedWidth(110)
            spin.setToolTip(tooltip)
            row.addWidget(lbl)
            row.addWidget(spin)
            row.addStretch()
            sync_lay.addLayout(row)
            return spin

        self._post_spin = _limit_row(
            "我的作品同步上限", post_limit,
            "同步「我的作品」时最多抓取的视频数（0 = 不限）")
        self._like_spin = _limit_row(
            "我的喜欢同步上限", like_limit,
            "同步「我的喜欢」时最多抓取的视频数（0 = 不限）")

        hint_sync = QLabel("0 = 不限数量；重新同步时生效")
        hint_sync.setStyleSheet("color:#888;font-size:9pt;")
        sync_lay.addWidget(hint_sync)

        lay.addWidget(sync_box)

        lay.addStretch()

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("确定")
        ok_btn.setFixedWidth(80)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._apply)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        # 即时预览主题
        self._theme_cb.currentTextChanged.connect(self._preview_theme)

    def _preview_theme(self, name):
        qss = THEMES.get(name, "")
        QApplication.instance().setStyleSheet(qss)

    def _apply(self):
        theme = self._theme_cb.currentText()
        conc  = self._conc_spin.value()
        self.theme_changed.emit(theme)
        self.concurrent_changed.emit(conc)
        self.sync_limits_changed.emit(
            self._post_spin.value(),
            self._like_spin.value(),
        )
        self.show_browser_changed.emit(self._show_browser_chk.isChecked())
        self.accept()

    def reject(self):
        # 取消时恢复原主题（由调用方在 rejected 信号处理）
        super().reject()


# ═════════════════════════════════════════════════════════════════════════════
# 主窗口
# ═════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("抖音视频工具")
        self.setGeometry(100, 100, 1400, 900)
        scr = QApplication.desktop().screenGeometry()
        sz  = self.geometry()
        self.move((scr.width()-sz.width())//2, (scr.height()-sz.height())//2)

        # 加载持久化设置
        self._app_settings = _load_app_settings()
        self._current_theme = self._app_settings.get("theme", "深色 (默认)")

        self._save_dir = os.path.join(_PROJECT_DIR, "videos")
        max_conc = self._app_settings.get("max_concurrent", 3)
        self.dl_mgr    = DownloadManager(self._save_dir, max_concurrent=max_conc)
        self._cards: dict[str, VideoCard] = {}   # aweme_id → card
        self._selected_aids: set = set()          # 跨收藏夹选中集合，aweme_id

        # worker 引用
        self._fl_thread = self._fl_worker = None   # folder list
        self._fv_thread = self._fv_worker = None   # folder videos (single)
        self._afv_thread = self._afv_worker = None  # all-folders video sync
        self._uv_thread = self._uv_worker = None   # user videos
        self._disc_uv_thread = self._disc_uv_worker = None  # discover tab

        self._current_folder = None   # {id, name}
        self._folders_meta   = []     # [{id,name,count,synced_at?}]
        self.video_data      = []     # for user video tab

        # 顶层 tabs: 我的 / 发现 / 下载
        self.top_tabs = QTabWidget()
        self.top_tabs.setObjectName("topTabs")
        self.top_tabs.currentChanged.connect(self._collapse_global_log)

        # "我的" 子 tab
        self.my_widget = QWidget()
        my_w_lay = QVBoxLayout(self.my_widget)
        my_w_lay.setContentsMargins(6, 6, 6, 0)
        my_w_lay.setSpacing(4)

        # 共享登录状态栏（所有子 tab 共用）
        login_frame = QFrame()
        login_frame.setStyleSheet("QFrame{border:1px solid #007acc;border-radius:5px;}")
        login_lay = QHBoxLayout(login_frame)
        login_lay.setContentsMargins(8, 4, 8, 4); login_lay.setSpacing(8)
        self.my_login = QLabel("● 未登录")
        self.my_login.setStyleSheet("color:#ff6666;font-weight:bold;")
        login_lay.addWidget(self.my_login)
        ob_my = QPushButton("① 打开抖音")
        ob_my.setStyleSheet(
            "QPushButton{background:#555;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;}"
            "QPushButton:hover{background:#686868;} QPushButton:pressed{background:#444;}")
        ob_my.clicked.connect(lambda: subprocess.Popen(["open", "https://www.douyin.com"]))
        login_lay.addWidget(ob_my)
        self.my_ck_btn = QPushButton("② 更新 Cookie")
        self.my_ck_btn.setStyleSheet(
            "QPushButton{background:#e53935;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;}"
            "QPushButton:hover{background:#ef5350;} QPushButton:pressed{background:#c62828;}")
        self.my_ck_btn.clicked.connect(self.open_cookie_dialog)
        login_lay.addWidget(self.my_ck_btn)
        login_lay.addStretch()
        my_w_lay.addWidget(login_frame)

        self.my_tabs = QTabWidget()
        self.my_tabs.setObjectName("myTabs")
        self.my_tabs.currentChanged.connect(self._collapse_global_log)
        my_w_lay.addWidget(self.my_tabs)

        self.fav_widget = QWidget(); self._setup_fav_ui()
        self.my_tabs.addTab(self.fav_widget, "我的收藏")
        self.my_post_widget = QWidget(); self._setup_self_tab_ui(self.my_post_widget, "post")
        self.my_tabs.addTab(self.my_post_widget, "我的作品")
        self.my_like_widget = QWidget(); self._setup_self_tab_ui(self.my_like_widget, "like")
        self.my_tabs.addTab(self.my_like_widget, "我的喜欢")
        self.top_tabs.addTab(self.my_widget, "我的")

        # "发现" tab
        self.discover_widget = QWidget(); self._setup_discover_ui()
        self.top_tabs.addTab(self.discover_widget, "发现")

        # "下载" tab
        self.dl_widget = QWidget(); self._setup_dl_ui()
        self.top_tabs.addTab(self.dl_widget, "下载")

        # "解析" tab
        self.parse_widget = QWidget(); self._setup_parse_ui()
        self.top_tabs.addTab(self.parse_widget, "解析")

        # 顶部工具栏（设置按钮）
        tb = self.addToolBar("工具")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setStyleSheet("QToolBar{background:transparent;border:none;padding:2px 4px;spacing:4px;}")
        tb.addWidget(QWidget())  # spacer
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedHeight(30)
        settings_btn.setFixedWidth(36)
        settings_btn.setStyleSheet("font-size:13pt;padding:2px 4px;")
        settings_btn.clicked.connect(self._open_settings)
        tb.addWidget(settings_btn)

        # 全局共享日志面板
        self.global_log = QTextEdit()
        self.global_log.setReadOnly(True)
        self.global_log.setPlaceholderText("全局日志...")
        self.global_log.setMinimumHeight(40)
        self.global_log.setVisible(False)

        self._glog_vsp = QSplitter(Qt.Vertical)
        self._glog_vsp.setHandleWidth(5)
        self._glog_vsp.addWidget(self.top_tabs)
        self._glog_vsp.addWidget(self.global_log)
        self._glog_vsp.setStretchFactor(0, 1)
        self._glog_vsp.setStretchFactor(1, 0)
        self._glog_vsp.setSizes([99999, 0])
        self._glog_expanded = False

        glog_container = _LogSplitterContainer(self._glog_vsp)
        glog_container.toggle_requested.connect(self._toggle_global_log)
        self._glog_toggle_container = glog_container
        self._glog_toggle_container.update_icon(self._glog_expanded)

        c = QWidget()
        QVBoxLayout(c).addWidget(glog_container)
        self.setCentralWidget(c)

        self._load_cookie()
        self._load_folder_index()
        self._restore_dl_records()
        self.top_tabs.setCurrentIndex(0)

    def _open_settings(self):
        post_limit   = self._app_settings.get("post_sync_limit", 50)
        like_limit   = self._app_settings.get("like_sync_limit", 100)
        show_browser = self._app_settings.get("show_browser", False)
        dlg = SettingsDialog(self._current_theme, self.dl_mgr.max_concurrent,
                             post_limit, like_limit, show_browser, self)
        orig_theme = self._current_theme
        dlg.rejected.connect(lambda: QApplication.instance().setStyleSheet(
            THEMES.get(orig_theme, STYLE)))
        dlg.theme_changed.connect(self._apply_theme)
        dlg.concurrent_changed.connect(self._apply_concurrent)
        dlg.sync_limits_changed.connect(self._apply_sync_limits)
        dlg.show_browser_changed.connect(self._apply_show_browser)
        dlg.exec_()

    def _apply_theme(self, name):
        self._current_theme = name
        qss = THEMES.get(name, STYLE)
        QApplication.instance().setStyleSheet(qss)
        self._app_settings["theme"] = name
        _save_app_settings(self._app_settings)
        self._update_completer_popup_style(name)

    def _update_completer_popup_style(self, theme_name):
        if not hasattr(self, "_folder_completer"): return
        sel_bg, sel_fg, bg, fg, border = {
            "深色 (默认)": ("#007acc", "#ffffff", "#2a2a2a", "#dddddd", "#555"),
            "午夜蓝":      ("#89b4fa", "#1a1e2e", "#1a1e2e", "#cdd6f4", "#313244"),
            "翠绿极简":    ("#3fb950", "#0d1117", "#0d1117", "#c9d1d9", "#21262d"),
            "暖沙浅色":    ("#c0642a", "#ffffff", "#f5ede3", "#2d2d2d", "#d4c9bc"),
        }.get(theme_name, ("#007acc", "#ffffff", "#2a2a2a", "#dddddd", "#555"))
        popup = self._folder_completer.popup()
        popup.setObjectName("folderSearchPopup")
        popup.setStyleSheet(f"""
            QListView#folderSearchPopup {{
                font-size: 13pt;
                font-weight: 500;
                background: {bg};
                color: {fg};
                border: 1px solid {border};
                outline: none;
            }}
            QListView#folderSearchPopup::item {{
                min-height: 36px;
                padding: 4px 10px;
            }}
            QListView#folderSearchPopup::item:selected,
            QListView#folderSearchPopup::item:hover {{
                background: {sel_bg};
                color: {sel_fg};
            }}
        """)

    def _apply_concurrent(self, n):
        self.dl_mgr.set_max_concurrent(n)
        self._app_settings["max_concurrent"] = n
        _save_app_settings(self._app_settings)

    def _apply_sync_limits(self, post, like):
        self._app_settings["post_sync_limit"] = post
        self._app_settings["like_sync_limit"] = like
        _save_app_settings(self._app_settings)
        for mode, val in (("post", post), ("like", like)):
            md = getattr(self, "_self_tabs", {}).get(mode)
            if md:
                spin = md.get("limit_spin")
                if spin and not spin.hasFocus():
                    spin.setValue(val)

    def _apply_show_browser(self, val: bool):
        self._app_settings["show_browser"] = val
        _save_app_settings(self._app_settings)

    # ══════════════════════════════════════════════════════════════════
    # Tab 0: 我的收藏
    # ══════════════════════════════════════════════════════════════════
    def _setup_fav_ui(self):
        lay = QVBoxLayout(self.fav_widget)
        lay.setSpacing(7); lay.setContentsMargins(10,9,10,7)

        # 顶栏：同步按钮（登录区已移到外层 my_widget 共享栏）
        top = QHBoxLayout(); top.setSpacing(8)

        self.refresh_list_btn = QPushButton("🔄 同步列表")
        self.refresh_list_btn.setStyleSheet(
            "QPushButton{background:#007acc;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#1a8fdd;} QPushButton:pressed{background:#005fa3;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.refresh_list_btn.setToolTip("同步收藏夹列表")
        self.refresh_list_btn.clicked.connect(self._start_folder_list_sync)
        top.addWidget(self.refresh_list_btn)

        self.sync_videos_btn = QPushButton("⬇ 同步视频")
        self.sync_videos_btn.setStyleSheet(
            "QPushButton{background:#6a1b9a;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#7b1fa2;} QPushButton:pressed{background:#4a148c;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.sync_videos_btn.setToolTip("同步所有收藏夹的视频")
        self.sync_videos_btn.clicked.connect(self._start_videos_sync)
        self.sync_videos_btn.setEnabled(False)
        top.addWidget(self.sync_videos_btn)

        self.dl_folder_btn = QPushButton("⬇ 下载当前夹")
        self.dl_folder_btn.setStyleSheet(
            "QPushButton{background:#388e3c;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#43a047;} QPushButton:pressed{background:#2e7d32;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.dl_folder_btn.setToolTip("下载当前收藏夹的全部视频")
        self.dl_folder_btn.clicked.connect(self._download_current_folder)
        self.dl_folder_btn.setEnabled(False)
        top.addWidget(self.dl_folder_btn)
        lay.addLayout(top)

        self.fav_progress_lbl = QLabel("")
        self.fav_progress_lbl.setStyleSheet("color:#aaa;font-size:9pt;")
        lay.addWidget(self.fav_progress_lbl)

        # 同步进度条 + 控制按钮行
        sync_ctrl_row = QHBoxLayout()
        self.sync_progress_bar = QProgressBar()
        self.sync_progress_bar.setRange(0, 100)
        self.sync_progress_bar.setValue(0)
        self.sync_progress_bar.setFixedHeight(16)
        self.sync_progress_bar.setTextVisible(True)
        self.sync_progress_bar.setFormat("%v/%m 个收藏夹")
        self.sync_progress_bar.setVisible(False)
        sync_ctrl_row.addWidget(self.sync_progress_bar, 1)

        self.sync_pause_btn = QPushButton("⏸ 暂停")
        self.sync_pause_btn.setFixedWidth(80)
        self.sync_pause_btn.setFixedHeight(28)
        self.sync_pause_btn.setStyleSheet(
            "QPushButton{font-size:10pt;padding:2px 6px;}"
            "QPushButton:hover{background:#5a6678;} QPushButton:pressed{background:#3a4658;}")
        self.sync_pause_btn.setVisible(False)
        self.sync_pause_btn.clicked.connect(self._toggle_sync_pause)
        sync_ctrl_row.addWidget(self.sync_pause_btn)

        self.sync_cancel_btn = QPushButton("✕ 取消")
        self.sync_cancel_btn.setFixedWidth(72)
        self.sync_cancel_btn.setFixedHeight(28)
        self.sync_cancel_btn.setStyleSheet(
            "QPushButton{font-size:10pt;padding:2px 6px;background:#c62828;color:white;border:none;border-radius:4px;}"
            "QPushButton:hover{background:#d32f2f;} QPushButton:pressed{background:#b71c1c;}")
        self.sync_cancel_btn.setVisible(False)
        self.sync_cancel_btn.clicked.connect(self._cancel_sync)
        sync_ctrl_row.addWidget(self.sync_cancel_btn)
        lay.addLayout(sync_ctrl_row)

        # 分割器
        sp = QSplitter(Qt.Horizontal); sp.setHandleWidth(4)

        # 左: 收藏夹列表
        left = QWidget(); ll2 = QVBoxLayout(left)
        ll2.setContentsMargins(0,0,4,0); ll2.setSpacing(4)
        fh = QHBoxLayout()
        fh.addWidget(QLabel("收藏夹")); fh.addStretch()
        self.folder_cnt_lbl = QLabel("0个")
        self.folder_cnt_lbl.setStyleSheet("color:#aaa;font-size:9pt;")
        fh.addWidget(self.folder_cnt_lbl)
        self.edit_folder_btn = QPushButton("编辑")
        self.edit_folder_btn.setFixedHeight(24)
        self.edit_folder_btn.setFixedWidth(48)
        self.edit_folder_btn.setStyleSheet(
            "QPushButton{font-size:9pt;padding:1px 6px;border-radius:3px;"
            "border:1px solid #555;background:#3a3a3a;color:#ccc;}"
            "QPushButton:hover{background:#4a4a4a;color:#fff;}"
            "QPushButton:checked{background:#e65100;border-color:#f57c00;color:white;}")
        self.edit_folder_btn.setCheckable(True)
        self.edit_folder_btn.toggled.connect(self._toggle_folder_edit_mode)
        fh.addWidget(self.edit_folder_btn)
        ll2.addLayout(fh)
        # 搜索框 + 下拉补全
        self.folder_search = QLineEdit()
        self.folder_search.setPlaceholderText("搜索收藏夹…")
        self.folder_search.setFixedHeight(28)
        self.folder_search.setStyleSheet(
            "QLineEdit{border:1px solid #444;border-radius:4px;padding:2px 6px;"
            "font-size:10pt;background:#2a2a2a;color:#ddd;}"
            "QLineEdit:focus{border-color:#007acc;}")
        # Completer：匹配数 ≤ 5 时弹出下拉，选中后跳转
        self._folder_completer_model = QStringListModel()
        self._folder_completer = QCompleter(self._folder_completer_model, self)
        self._folder_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._folder_completer.setFilterMode(Qt.MatchContains)
        self._folder_completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._folder_completer.setMaxVisibleItems(5)
        self.folder_search.setCompleter(self._folder_completer)
        self._search_display_to_fid = {}  # display_name → fid，用于重名时精确跳转
        # 初始 popup 样式（主题色在 _apply_theme 里同步更新）
        from PyQt5.QtGui import QFont
        pop_font = QFont(); pop_font.setPointSize(13)
        self._folder_completer.popup().setFont(pop_font)
        self._update_completer_popup_style(getattr(self, "_current_theme", "深色 (默认)"))
        # textEdited 只在用户真正输入时触发，避免 completer 自动填充再次触发过滤
        self.folder_search.textEdited.connect(self._on_folder_search_changed)
        self._folder_completer.activated.connect(self._on_folder_search_activated)
        ll2.addWidget(self.folder_search)
        self.folder_list = AutoScrollListWidget()
        self.folder_list.setMinimumWidth(220)
        self.folder_list.setSpacing(1)
        self.folder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._folder_list_context_menu)
        self.folder_list.currentRowChanged.connect(self._on_folder_selected)
        self.folder_list.itemSelectionChanged.connect(self._update_folder_item_colors)
        # 拖拽排序
        self.folder_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.folder_list.setDefaultDropAction(Qt.MoveAction)
        self.folder_list.model().rowsMoved.connect(self._on_folder_rows_moved)
        ll2.addWidget(self.folder_list)
        # 编辑模式操作栏（默认隐藏）
        self._edit_bar = QWidget()
        edit_lay = QHBoxLayout(self._edit_bar)
        edit_lay.setContentsMargins(0,0,0,0); edit_lay.setSpacing(4)
        self.edit_del_btn = QPushButton("🗑 删除选中")
        self.edit_del_btn.setEnabled(False)
        self.edit_del_btn.setStyleSheet(
            "QPushButton{font-size:9pt;padding:3px 8px;border-radius:3px;"
            "background:#c62828;color:white;border:none;}"
            "QPushButton:hover{background:#e53935;}"
            "QPushButton:disabled{background:#555;color:#888;}")
        self.edit_del_btn.clicked.connect(self._edit_delete_selected)
        edit_lay.addWidget(self.edit_del_btn)
        edit_lay.addStretch()
        done_btn = QPushButton("完成")
        done_btn.setFixedHeight(26)
        done_btn.setStyleSheet(
            "QPushButton{font-size:9pt;padding:3px 10px;border-radius:3px;"
            "background:#007acc;color:white;border:none;}"
            "QPushButton:hover{background:#1a8fdd;}")
        done_btn.clicked.connect(lambda: self.edit_folder_btn.setChecked(False))
        edit_lay.addWidget(done_btn)
        self._edit_bar.setVisible(False)
        ll2.addWidget(self._edit_bar)

        # 右: 视频网格
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(4,0,0,0); rl.setSpacing(4)
        gh = QHBoxLayout()
        self.grid_title = QLabel("请选择左侧收藏夹")
        self.grid_title.setStyleSheet("font-weight:bold;font-size:11pt;")
        gh.addWidget(self.grid_title); gh.addStretch()
        self.grid_cnt = QLabel("")
        self.grid_cnt.setStyleSheet("color:#aaa;")
        gh.addWidget(self.grid_cnt)
        self.resync_btn = QPushButton("🔄 重新同步")
        self.resync_btn.setStyleSheet(
            "QPushButton{padding:4px 9px;font-size:10pt;}"
            "QPushButton:hover{background:#5a6678;} QPushButton:pressed{background:#3a4658;}")
        self.resync_btn.clicked.connect(self._resync_folder_videos)
        self.resync_btn.setVisible(False)
        gh.addWidget(self.resync_btn); rl.addLayout(gh)

        # 批量操作栏
        batch_bar = QHBoxLayout(); batch_bar.setSpacing(6)
        self.sel_all_btn = QPushButton("全选")
        self.sel_none_btn = QPushButton("取消全选")
        self.batch_dl_btn = QPushButton("⬇ 批量下载")
        self.batch_del_btn = QPushButton("🗑 删除文件")
        self.clear_cache_btn = QPushButton("✕ 清空缓存")
        _batch_btns = [self.sel_all_btn, self.sel_none_btn,
                       self.batch_dl_btn, self.batch_del_btn, self.clear_cache_btn]
        for b in _batch_btns:
            b.setFixedHeight(28)
            b.setStyleSheet("QPushButton{font-size:10pt;padding:2px 8px;border-radius:4px;"
                            "background:#3a3a3a;color:#ccc;border:1px solid #555;}"
                            "QPushButton:hover{background:#4a4a4a;border-color:#777;color:#fff;}"
                            "QPushButton:pressed{background:#2a2a2a;}"
                            "QPushButton:disabled{background:#2e2e2e;color:#666;border-color:#444;}")
            b.setEnabled(False)
            batch_bar.addWidget(b)
        batch_bar.addStretch()
        self.sel_all_btn.clicked.connect(self._select_all_cards)
        self.sel_none_btn.clicked.connect(self._select_none_cards)
        self.batch_dl_btn.clicked.connect(self._batch_download_selected)
        self.batch_del_btn.clicked.connect(self._batch_delete_files)
        self.clear_cache_btn.clicked.connect(self._clear_folder_cache)
        rl.addLayout(batch_bar)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_lay  = QGridLayout(self.grid_host)
        self.grid_lay.setSpacing(10); self.grid_lay.setContentsMargins(4,4,4,4)
        self.grid_lay.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        rl.addWidget(self.scroll)

        sp.addWidget(left); sp.addWidget(right)
        sp.setStretchFactor(0,0); sp.setStretchFactor(1,1)
        sp.setSizes([240, 960])

        lay.addWidget(sp, 1)

    def _glog_default_sizes(self):
        total = sum(self._glog_vsp.sizes()) or self._glog_vsp.height() or 800
        log_h = max(80, int(total * 0.35))
        return [total - log_h, log_h]

    def _collapse_global_log(self, _index=None):
        if not getattr(self, "_glog_expanded", False):
            return
            self._glog_sizes = self._glog_vsp.sizes()
            self._glog_vsp.setSizes([99999, 0])
            self.global_log.setVisible(False)
            self._glog_expanded = False
            self._glog_toggle_container.update_icon(False)

    def _toggle_global_log(self):
        if self._glog_expanded:
            self._glog_sizes = self._glog_vsp.sizes()
            self._glog_vsp.setSizes([99999, 0])
            self.global_log.setVisible(False)
            self._glog_expanded = False
        else:
            self.global_log.setVisible(True)
            sizes = getattr(self, "_glog_sizes", None)
            if not sizes or sizes[1] < 40:
                sizes = self._glog_default_sizes()
            self._glog_vsp.setSizes(sizes)
            self._glog_expanded = True
        self._glog_toggle_container.update_icon(self._glog_expanded)

    def _glog(self, msg: str):
        from datetime import datetime as _dt
        line = f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
        self.global_log.append(line)
        if not self._glog_expanded:
            self.global_log.setVisible(True)
            sizes = getattr(self, "_glog_sizes", None)
            if not sizes or sizes[1] < 40:
                sizes = self._glog_default_sizes()
            self._glog_vsp.setSizes(sizes)
            self._glog_expanded = True
            self._glog_toggle_container.update_icon(True)

    # ── 收藏夹列表加载/刷新 ──────────────────────────────────────────
    def _load_folder_index(self):
        idx = load_folder_index()
        if idx:
            customs = [f for f in idx if f["id"] != "default"]
            default = [f for f in idx if f["id"] == "default"]
            self._folders_meta = customs + default
            self._refresh_folder_list()
            self.sync_videos_btn.setEnabled(True)
            self._update_fav_sync_time()

    def _update_fav_sync_time(self):
        """在 fav_progress_lbl 显示最近一次全量同步时间。"""
        ts_list = [f.get("synced_at", 0) for f in self._folders_meta if f.get("synced_at")]
        if ts_list:
            from datetime import datetime as _dt
            last = _dt.fromtimestamp(max(ts_list)).strftime("%Y-%m-%d %H:%M")
            self.fav_progress_lbl.setText(f"上次同步：{last}")
        else:
            self.fav_progress_lbl.setText("尚未同步")

    def _refresh_folder_list(self):
        self.folder_list.blockSignals(True)
        prev_id = self._current_folder["id"] if self._current_folder else None
        self.folder_list.clear()

        defaults  = [f for f in self._folders_meta if f["id"] == "default"]
        active    = [f for f in self._folders_meta if f["id"] != "default" and not f.get("deleted")]
        deleted   = [f for f in self._folders_meta if f["id"] != "default" and f.get("deleted")]
        sel_row   = None

        def _add_header(text):
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, "__header__")
            item.setFlags(Qt.NoItemFlags)  # 不可选
            item.setSizeHint(QSize(0, 26))
            font = item.font(); font.setPointSize(8); font.setBold(True)
            item.setFont(font)
            item.setForeground(QColor("#888"))
            self.folder_list.addItem(item)

        def _add_folder(f):
            nonlocal sel_row
            is_def = (f["id"] == "default")
            item = QListWidgetItem()
            item.setData(Qt.UserRole, f["id"])
            item.setSizeHint(QSize(0, 96 if is_def else 76))
            if is_def:
                item.setBackground(QColor("#2a3a28"))  # 深绿底色凸显默认收藏
            elif f.get("deleted"):
                item.setBackground(QColor("#2a1f1f"))  # 深红底色标记已删除
            self.folder_list.addItem(item)
            # 用缓存文件里的实际视频数作为权威来源，避免 count 字段与实际不符
            cache = load_folder_cache(f["id"])
            actual_count = len(cache.get("videos", [])) if cache else f.get("count", 0)
            display_f = {**f, "count": actual_count}
            if cache and cache.get("synced_at"):
                display_f["synced_at"] = cache["synced_at"]
            w = FolderItemWidget(display_f)
            self.folder_list.setItemWidget(item, w)
            if f["id"] == prev_id:
                sel_row = self.folder_list.count() - 1

        if defaults:
            _add_folder(defaults[0])
        if active:
            _add_header("  我的收藏夹")
            for f in active:
                _add_folder(f)
        if deleted:
            _add_header("  已删除收藏夹")
            for f in deleted:
                _add_folder(f)

        if sel_row is not None:
            self.folder_list.setCurrentRow(sel_row)
        active_cnt = len(defaults) + len(active)
        self.folder_cnt_lbl.setText(f"{active_cnt}个" + (f"（+{len(deleted)}已删除）" if deleted else ""))
        self.folder_list.blockSignals(False)
        self._update_folder_item_colors()

    def _update_folder_item_colors(self):
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            w = self.folder_list.itemWidget(item)
            if isinstance(w, FolderItemWidget):
                w.set_selected(item.isSelected())

    def _start_folder_list_sync(self):
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先设置 Cookie"); return
        if self._afv_thread and self._afv_thread.isRunning():
            QMessageBox.information(self, "提示", "正在同步中，请稍候"); return
        self.refresh_list_btn.setEnabled(False)
        self.sync_videos_btn.setEnabled(False)
        self._glog("▶ 开始同步收藏夹列表")
        self._glog("⏳ 正在启动 Chrome 并获取收藏夹列表...")
        self.sync_progress_bar.setValue(0); self.sync_progress_bar.setMaximum(1)
        self.sync_progress_bar.setFormat("获取收藏夹列表中...")
        self.sync_progress_bar.setVisible(True)
        self.sync_pause_btn.setText("⏸ 暂停"); self.sync_pause_btn.setVisible(True)
        self.sync_cancel_btn.setVisible(True)
        self._afv_thread = QThread()
        self._afv_worker = AllFoldersVideoWorker(self._cookie_str, mode="list_only",
                                                   show_browser=self._app_settings.get("show_browser", False))
        self._afv_worker.moveToThread(self._afv_thread)
        self._afv_worker.log.connect(self._glog)
        self._afv_worker.folders_loaded.connect(self._on_folders_loaded)
        self._afv_worker.cookie_expired.connect(self._on_cookie_expired)
        self._afv_worker.verification_needed.connect(self._on_verification_needed)
        self._afv_worker.finished.connect(self._on_afv_finished)
        self._afv_thread.started.connect(self._afv_worker.run)
        self._afv_done_count = 0
        self._afv_total = 0
        self._afv_thread.start()

    def _start_videos_sync(self):
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先设置 Cookie"); return
        if self._afv_thread and self._afv_thread.isRunning():
            QMessageBox.information(self, "提示", "正在同步中，请稍候"); return
        if not self._folders_meta:
            QMessageBox.warning(self, "提示", "请先点击「同步收藏夹列表」获取列表"); return
        self.refresh_list_btn.setEnabled(False)
        self.sync_videos_btn.setEnabled(False)
        self._glog("▶ 开始同步所有收藏夹视频")
        total = len(self._folders_meta)
        self._glog(f"⏳ 先重新获取最新收藏夹列表（当前缓存 {total} 个），再开始视频同步...")
        self.sync_progress_bar.setValue(0); self.sync_progress_bar.setMaximum(max(total, 1))
        self.sync_progress_bar.setFormat("正在更新收藏夹列表...")
        self.sync_progress_bar.setVisible(True)
        self.sync_pause_btn.setText("⏸ 暂停"); self.sync_pause_btn.setVisible(True)
        self.sync_cancel_btn.setVisible(True)
        self._afv_thread = QThread()
        self._afv_worker = AllFoldersVideoWorker(
            self._cookie_str, mode="videos_only", folders=None,
            show_browser=self._app_settings.get("show_browser", False))
        self._afv_worker.moveToThread(self._afv_thread)
        self._afv_worker.log.connect(self._glog)
        self._afv_worker.folders_loaded.connect(self._on_folders_loaded)
        self._afv_worker.folder_done.connect(self._on_afv_folder_done)
        self._afv_worker.cookie_expired.connect(self._on_cookie_expired)
        self._afv_worker.verification_needed.connect(self._on_verification_needed)
        self._afv_worker.finished.connect(self._on_afv_finished)
        self._afv_thread.started.connect(self._afv_worker.run)
        self._afv_done_count = 0
        self._afv_total = total
        self._afv_thread.start()

    def _toggle_sync_pause(self):
        w = self._afv_worker
        if not w: return
        if w._paused:
            w.resume()
            self.sync_pause_btn.setText("⏸ 暂停")
            self._glog("▶ 继续同步...")
        else:
            w.pause()
            self.sync_pause_btn.setText("▶ 继续")
            self._glog("⏸ 已暂停")

    def _cancel_sync(self):
        w = self._afv_worker
        if w: w.cancel()
        self._glog("🛑 正在取消...")
        self.sync_cancel_btn.setEnabled(False)

    def _on_folders_loaded(self, folders):
        existing = {f["id"]: f for f in self._folders_meta}
        new_ids = {f["id"] for f in folders}
        for f in folders:
            ex = existing.get(f["id"], {})
            merged = {**ex, **f}
            # 本地已同步的 count/synced_at 比 API 返回更准确，不要被覆盖
            if ex.get("count", 0) > f.get("count", 0):
                merged["count"] = ex["count"]
            if ex.get("synced_at"):
                merged["synced_at"] = ex["synced_at"]
            merged.pop("deleted", None)   # 重新出现则清除已删除标记
            existing[f["id"]] = merged
        # 标记在本地存在但 API 不再返回的收藏夹为已删除
        deleted_cnt = 0
        for fid, f in existing.items():
            if fid not in new_ids and fid != "default":
                if not f.get("deleted"):
                    f["deleted"] = True
                    self._glog(f"⚠ 收藏夹「{f.get('name', fid)}」在账号中已不存在，标记为已删除")
                    deleted_cnt += 1
        if deleted_cnt:
            self._glog(f"⚠ 共 {deleted_cnt} 个收藏夹已从账号中删除")
        customs = [f for f in existing.values() if f["id"] != "default"]
        default = [f for f in existing.values() if f["id"] == "default"]
        self._folders_meta = customs + default
        active_cnt = sum(1 for f in self._folders_meta if not f.get("deleted"))
        self._afv_total = active_cnt   # 进度条只计算未删除的
        save_folder_index(self._folders_meta)
        self._refresh_folder_list()
        self.sync_progress_bar.setMaximum(max(self._afv_total, 1))
        self.sync_progress_bar.setValue(0)
        self.sync_progress_bar.setFormat(f"%v/{self._afv_total} 个收藏夹")
        self._glog(f"✅ 发现 {len(folders)} 个收藏夹")
        # 仅 list_only 模式结束时才重新启用按钮；videos_only 模式正在继续同步视频
        if not (self._afv_worker and self._afv_worker.mode == "videos_only"):
            self.sync_videos_btn.setEnabled(bool(self._folders_meta))

    def _on_afv_folder_done(self, fid, fname, videos):
        save_folder_cache(fid, fname, videos)
        for fm in self._folders_meta:
            if fm["id"] == fid:
                fm["count"] = len(videos); fm["synced_at"] = time.time(); break
        save_folder_index(self._folders_meta)
        self._refresh_folder_list()
        if self._current_folder and self._current_folder["id"] == fid:
            self._populate_grid(videos)
        self._afv_done_count = getattr(self, "_afv_done_count", 0) + 1
        total = getattr(self, "_afv_total", len(self._folders_meta))
        self.sync_progress_bar.setValue(self._afv_done_count)
        self._glog(f"⏳ 已同步 {self._afv_done_count}/{total} 个收藏夹...")

    def _on_afv_finished(self):
        if self._afv_thread:
            self._afv_thread.quit(); self._afv_thread.wait()
        self._afv_worker = None
        self.refresh_list_btn.setEnabled(True)
        self.sync_videos_btn.setEnabled(bool(self._folders_meta))
        self.sync_progress_bar.setVisible(False)
        self.sync_pause_btn.setVisible(False)
        self.sync_cancel_btn.setVisible(False)
        self.sync_cancel_btn.setEnabled(True)
        from datetime import datetime as _dt
        self._glog(f"✅ 所有收藏夹视频同步完成  上次同步 {_dt.now().strftime('%m-%d %H:%M')}")
        self._update_fav_sync_time()

    # ── 收藏夹搜索 ───────────────────────────────────────────────────
    def _get_item_name(self, item):
        """从 QListWidgetItem 取收藏夹名称，header item 返回 None。"""
        if not item:
            return None
        if item.data(Qt.UserRole) == "__header__":
            return None
        w = self.folder_list.itemWidget(item)
        lbl = getattr(w, "name_lbl", None)
        return lbl.text() if lbl else None

    def _on_folder_search_changed(self, text):
        """实时过滤列表：显示匹配项，隐藏不匹配项；清空时恢复全部。"""
        q = text.strip().lower()
        self.folder_list.blockSignals(True)

        # 收集匹配项用于 completer，重名时加 (2)(3)... 区分
        display_name_count = {}   # name → count so far
        match_display_to_fid = {}  # display_name → fid（最后一个同名的 fid，不影响唯一名）

        # 先做 show/hide 过滤
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if not item:
                continue
            fid = item.data(Qt.UserRole)
            if fid == "__header__":
                item.setHidden(True)
                continue
            if not q:
                item.setHidden(False)
                continue
            name = self._get_item_name(item) or ""
            hit = q in name.lower()
            item.setHidden(not hit)
            if hit:
                display_name_count[name] = display_name_count.get(name, 0) + 1
                cnt = display_name_count[name]
                display = name if cnt == 1 else f"{name} ({cnt})"
                match_display_to_fid[display] = fid

        if q:
            # 让有可见子项的 header 显示出来
            i = 0
            while i < self.folder_list.count():
                item = self.folder_list.item(i)
                if item and item.data(Qt.UserRole) == "__header__":
                    has_visible = False
                    j = i + 1
                    while j < self.folder_list.count():
                        next_item = self.folder_list.item(j)
                        if not next_item:
                            j += 1
                            continue
                        if next_item.data(Qt.UserRole) == "__header__":
                            break
                        if not next_item.isHidden():
                            has_visible = True
                            break
                        j += 1
                    item.setHidden(not has_visible)
                i += 1
        else:
            for i in range(self.folder_list.count()):
                item = self.folder_list.item(i)
                if item:
                    item.setHidden(False)

        self.folder_list.blockSignals(False)

        # 更新 completer，但同名第一个不加后缀时需要回填正确映射
        # 重建：重名的第一个也需要加 (1) 以便区分
        if q and display_name_count:
            # 对于有重名的 name，第一个也需要加 (1)
            has_dup = {n for n, c in display_name_count.items() if c > 1}
            final_displays = []
            dup_counters = {}
            for i in range(self.folder_list.count()):
                item = self.folder_list.item(i)
                if not item or item.isHidden():
                    continue
                fid = item.data(Qt.UserRole)
                if fid == "__header__":
                    continue
                name = self._get_item_name(item) or ""
                if q not in name.lower():
                    continue
                if name in has_dup:
                    dup_counters[name] = dup_counters.get(name, 0) + 1
                    display = f"{name} ({dup_counters[name]})"
                else:
                    display = name
                final_displays.append(display)
                self._search_display_to_fid[display] = fid
            self._folder_completer_model.setStringList(final_displays)
        else:
            self._folder_completer_model.setStringList([])

    def _on_folder_search_activated(self, display_name):
        """用户从下拉中选中一个条目，按 fid 定位到对应收藏夹。"""
        fid = getattr(self, '_search_display_to_fid', {}).get(display_name)
        found = False
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if not item:
                continue
            if fid:
                if item.data(Qt.UserRole) == fid:
                    self.folder_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                    self.folder_list.setCurrentItem(item)
                    found = True
                    break
            else:
                # 兜底：按名称匹配（无重名情况）
                item_name = self._get_item_name(item)
                if item_name == display_name:
                    self.folder_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                    self.folder_list.setCurrentItem(item)
                    found = True
                    break
        # 清空搜索框并恢复完整列表
        self.folder_search.blockSignals(True)
        self.folder_search.clear()
        self.folder_search.blockSignals(False)
        self._on_folder_search_changed("")
        self.folder_list.setFocus()

    # ── 选中收藏夹 → 加载视频网格 ───────────────────────────────────
    def _on_folder_selected(self, row):
        if row < 0: return
        item = self.folder_list.item(row)
        if not item: return
        fid = item.data(Qt.UserRole)
        if not fid or fid == "__header__": return
        f = next((x for x in self._folders_meta if x["id"] == fid), None)
        if not f: return
        self._current_folder = f
        self.grid_title.setText(f"📁 {f['name']}")
        self.resync_btn.setVisible(True)
        self.dl_folder_btn.setEnabled(True)
        for b in [self.sel_all_btn, self.sel_none_btn, self.batch_dl_btn,
                  self.batch_del_btn, self.clear_cache_btn]:
            b.setEnabled(True)
        cache = load_folder_cache(f["id"])
        if cache:
            self._populate_grid(cache.get("videos", []))
        else:
            self._clear_grid()
            self.grid_cnt.setText("未同步 → 点击「重新同步视频」")

    def _populate_grid(self, videos):
        self._clear_grid()
        self.grid_cnt.setText(f"{len(videos)} 个视频")
        avail = self.scroll.viewport().width() or (self.width() - 260)
        cols  = max(1, avail // (VideoCard.W + 14))
        BATCH = 20  # 每批创建的卡片数，批间让出事件循环避免 UI 冻结
        for i, vm in enumerate(videos):
            card = VideoCard(vm, self._save_dir)
            card.download_requested.connect(self._on_card_dl)
            card.remove_from_dl_requested.connect(self._remove_card_from_dl)
            card.delete_local_requested.connect(self._delete_local_file)
            aid = vm["aweme_id"]
            # 恢复跨收藏夹选中状态
            if aid in self._selected_aids:
                card.set_selected(True)
            # 选中变化时同步到跨收藏夹集合
            card._chk.stateChanged.connect(
                lambda state, a=aid: self._on_card_check(a, state))
            self.grid_lay.addWidget(card, i // cols, i % cols)
            self._cards[aid] = card
            if (i + 1) % BATCH == 0:
                QApplication.processEvents()
        self._update_batch_btn_state()

    def _clear_grid(self):
        self._cards.clear()
        while self.grid_lay.count():
            w = self.grid_lay.takeAt(0).widget()
            if w:
                if hasattr(w, "stop_loader"):
                    w.stop_loader()
                w.deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_folder:
            cache = load_folder_cache(self._current_folder["id"])
            if cache and cache.get("videos"):
                QTimer.singleShot(100, lambda: self._populate_grid(cache["videos"]))
        # 我的作品/喜欢：resize 时重排列数
        if hasattr(self, "_self_tabs"):
            for mode, md in self._self_tabs.items():
                if not self._self_cards.get(mode): continue
                grid = md["grid_layout"]
                scroll = md["scroll"]
                avail = scroll.viewport().width()
                if not avail:
                    avail = scroll.width() - scroll.verticalScrollBar().width() - 4
                if not avail:
                    avail = self.width() - 240
                new_cols = max(1, avail // (VideoCard.W + 10))
                cur_cols = md.get("col_count", 0)
                if new_cols != cur_cols and new_cols > 0:
                    md["col_count"] = new_cols
                    widgets = []
                    n = grid.count()
                    for _ in range(n):
                        item = grid.takeAt(0)
                        if item and item.widget(): widgets.append(item.widget())
                    for i, w in enumerate(widgets):
                        grid.addWidget(w, i // new_cols, i % new_cols)
        # 发现 tab：resize 时重排列数
        if hasattr(self, "_disc_cards"):
            for mode in ("post",):
                grid = getattr(self, f"_disc_{mode}_grid", None)
                scroll = getattr(self, f"_disc_{mode}_scroll", None)
                if not grid or not scroll or not self._disc_cards.get(mode): continue
                avail = scroll.viewport().width()
                if not avail:
                    avail = scroll.width() - scroll.verticalScrollBar().width() - 4
                if not avail:
                    avail = self.width() - 240
                new_cols = max(1, avail // (VideoCard.W + 10))
                cur_cols = getattr(self, "_disc_col_count", {}).get(mode, 0)
                if new_cols != cur_cols and new_cols > 0:
                    if not hasattr(self, "_disc_col_count"):
                        self._disc_col_count = {}
                    self._disc_col_count[mode] = new_cols
                    n = grid.count()
                    widgets = []
                    for _ in range(n):
                        item = grid.takeAt(0)
                        if item and item.widget(): widgets.append(item.widget())
                    for i, w in enumerate(widgets):
                        grid.addWidget(w, i // new_cols, i % new_cols)

    # ── 同步收藏夹视频 ───────────────────────────────────────────────
    def _resync_folder_videos(self):
        if not self._current_folder: return
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先设置 Cookie"); return
        if self._fv_thread and self._fv_thread.isRunning():
            QMessageBox.information(self, "提示", "正在同步中，请稍候"); return
        fid   = self._current_folder["id"]
        fname = self._current_folder["name"]
        self.resync_btn.setEnabled(False)
        self._glog(f"▶ 开始同步收藏夹「{fname}」视频")
        self._fv_thread = QThread()
        self._fv_worker = FolderVideoWorker(self._cookie_str, fid, fname,
                                             show_browser=self._app_settings.get("show_browser", False))
        self._fv_worker.moveToThread(self._fv_thread)
        self._fv_worker.log.connect(self._glog)
        self._fv_worker.progress.connect(lambda n: self._glog(f"⏳ 已抓取 {n} 个视频..."))
        self._fv_worker.done.connect(lambda videos: self._on_folder_videos_done(fid, fname, videos))
        self._fv_worker.cookie_expired.connect(self._on_cookie_expired)
        self._fv_worker.finished.connect(self._on_fv_finished)
        self._fv_thread.started.connect(self._fv_worker.run)
        self._fv_thread.start()

    def _on_folder_videos_done(self, fid, fname, videos):
        save_folder_cache(fid, fname, videos)
        # 更新 _folders_meta 的 count
        for f in self._folders_meta:
            if f["id"] == fid:
                f["count"] = len(videos); f["synced_at"] = time.time(); break
        self._refresh_folder_list()
        if self._current_folder and self._current_folder["id"] == fid:
            self._populate_grid(videos)
        self._glog(f"✅ 「{fname}」同步完成：{len(videos)} 个视频")
        self._update_fav_sync_time()

    def _on_fv_finished(self):
        self._fv_thread.quit(); self._fv_thread.wait()
        self._fv_worker = None
        self.resync_btn.setEnabled(True)
        fname = self._current_folder["name"] if self._current_folder else "收藏夹"
        from datetime import datetime as _dt
        self._glog(f"✅ 收藏夹「{fname}」视频同步完成  上次同步 {_dt.now().strftime('%m-%d %H:%M')}")

    # ── 下载当前收藏夹所有视频 ───────────────────────────────────────
    def _download_current_folder(self):
        if not self._current_folder: return
        cache = load_folder_cache(self._current_folder["id"])
        if not cache:
            QMessageBox.information(self, "提示", "请先同步此收藏夹视频"); return
        added = 0
        for vm in cache.get("videos", []):
            if not get_local_video_path(vm["aweme_id"], self._save_dir):
                fname = self._current_folder.get("name", "收藏夹")
                self._do_add_download(vm["title"], vm["url"], vm["aweme_id"],
                                      source=f"我的收藏 · {fname}", author=vm.get("author",""))
                added += 1
        self._glog(f"已将 {added} 个视频加入下载队列")
        if added: self.top_tabs.setCurrentIndex(2)

    def _on_card_check(self, aweme_id, state):
        if state:
            self._selected_aids.add(aweme_id)
        else:
            self._selected_aids.discard(aweme_id)
        self._update_batch_btn_state()

    def _on_card_dl(self, vm):
        fname = (self._current_folder or {}).get("name", "收藏夹")
        self._do_add_download(vm["title"], vm["url"], vm["aweme_id"],
                              source=f"我的收藏 · {fname}", author=vm.get("author",""))

    def _update_batch_btn_state(self):
        has_sel = bool(self._selected_aids)
        self.batch_dl_btn.setEnabled(has_sel)
        self.batch_del_btn.setEnabled(has_sel)

    def _select_all_cards(self):
        for c in self._cards.values():
            c.set_selected(True)
        self._update_batch_btn_state()

    def _select_none_cards(self):
        for c in self._cards.values():
            c.set_selected(False)
        self._selected_aids.clear()
        self._update_batch_btn_state()

    def _batch_download_selected(self):
        # 从所有收藏夹缓存中查找选中的视频（_selected_aids 跨收藏夹保留）
        added = 0
        for fmeta in self._folders_meta:
            cache = load_folder_cache(fmeta["id"])
            if not cache:
                continue
            for vm in (cache.get("videos") or []):
                aid = vm.get("aweme_id")
                if aid in self._selected_aids:
                    local = get_local_video_path(aid, self._save_dir)
                    if not local:
                        self._do_add_download(vm["title"], vm["url"], aid,
                                              source=f"我的收藏 · {fmeta['name']}", author=vm.get("author",""))
                        added += 1
            self.top_tabs.setCurrentIndex(2)
        else:
            self._glog("所选视频均已下载或无有效 URL")

    def _batch_delete_files(self):
        targets = [(aid, c) for aid, c in self._cards.items() if c.is_selected() and c._local_path]
        if not targets:
            QMessageBox.information(self, "提示", "没有已下载的选中视频"); return
        r = QMessageBox.question(self, "确认删除",
            f"将删除 {len(targets)} 个视频文件（本地文件），缓存记录保留。确认？",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes: return
        for aid, c in targets:
            try: os.remove(c._local_path)
            except Exception: pass
            c._local_path = None; c._refresh()
            self._selected_aids.discard(aid)
        self._glog(f"已删除 {len(targets)} 个视频文件")

    def _clear_folder_cache(self):
        if not self._current_folder: return
        fid = self._current_folder["id"]; fname = self._current_folder["name"]
        r = QMessageBox.question(self, "确认清空",
            f"清空「{fname}」的视频缓存记录（不删除已下载文件）？",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes: return
        cache_path = os.path.join(CACHE_DIR, f"{fid}.json")
        try: os.remove(cache_path)
        except Exception: pass
        for fm in self._folders_meta:
            if fm["id"] == fid:
                fm.pop("synced_at", None); fm["count"] = 0; break
        save_folder_index(self._folders_meta)
        self._refresh_folder_list()
        self._clear_grid()
        self.grid_cnt.setText("缓存已清空 → 点击「重新同步视频」")
        self._glog(f"「{fname}」缓存已清空")

    def _toggle_folder_edit_mode(self, on):
        self._edit_bar.setVisible(on)
        if on:
            self.edit_folder_btn.setText("编辑中")
            self.folder_list.setSelectionMode(QAbstractItemView.MultiSelection)
            self.folder_list.clearSelection()
            self.folder_list.selectionModel().selectionChanged.connect(
                self._edit_selection_changed)
        else:
            self.edit_folder_btn.setText("编辑")
            self.folder_list.setSelectionMode(QAbstractItemView.SingleSelection)
            try:
                self.folder_list.selectionModel().selectionChanged.disconnect(
                    self._edit_selection_changed)
            except Exception:
                pass
            # 恢复选中当前收藏夹
            if self._current_folder:
                for i in range(self.folder_list.count()):
                    it = self.folder_list.item(i)
                    if it and it.data(Qt.UserRole) == self._current_folder["id"]:
                        self.folder_list.setCurrentRow(i); break

    def _edit_selection_changed(self):
        sel = [self.folder_list.item(i).data(Qt.UserRole)
               for i in range(self.folder_list.count())
               if self.folder_list.item(i).isSelected()
               and self.folder_list.item(i).data(Qt.UserRole) != "__header__"]
        self.edit_del_btn.setEnabled(bool(sel))

    def _edit_delete_selected(self):
        sel_fids = [self.folder_list.item(i).data(Qt.UserRole)
                    for i in range(self.folder_list.count())
                    if self.folder_list.item(i).isSelected()
                    and self.folder_list.item(i).data(Qt.UserRole) not in (None, "__header__")]
        if not sel_fids: return
        names = [f["name"] for f in self._folders_meta if f["id"] in sel_fids]
        r = QMessageBox.question(self, "确认批量删除",
            f"将从本地记录中删除 {len(sel_fids)} 个收藏夹：\n{', '.join(names[:5])}{'...' if len(names)>5 else ''}\n（不影响抖音账号，不删除已下载视频）",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes: return
        for fid in sel_fids:
            self._folders_meta = [f for f in self._folders_meta if f["id"] != fid]
            cache_path = os.path.join(CACHE_DIR, f"{fid}.json")
            try: os.remove(cache_path)
            except Exception: pass
        save_folder_index(self._folders_meta)
        self._refresh_folder_list()
        if self._current_folder and self._current_folder["id"] in sel_fids:
            self._current_folder = None
            self._clear_grid()
            self.grid_title.setText("请选择左侧收藏夹")
        self._glog(f"已删除 {len(sel_fids)} 个收藏夹记录")
        self.edit_del_btn.setEnabled(False)

    def _on_folder_rows_moved(self, parent, start, end, dest, dest_row):
        """拖拽排序后，按列表当前顺序更新 _folders_meta 并持久化"""
        new_order = []
        for i in range(self.folder_list.count()):
            it = self.folder_list.item(i)
            if not it: continue
            fid = it.data(Qt.UserRole)
            if fid in (None, "__header__"): continue
            meta = next((f for f in self._folders_meta if f["id"] == fid), None)
            if meta:
                new_order.append(meta)
        self._folders_meta = new_order
        save_folder_index(self._folders_meta)

    def _folder_list_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        if not item: return
        fid = item.data(Qt.UserRole)
        if fid in (None, "__header__"): return
        meta = next((f for f in self._folders_meta if f["id"] == fid), None)
        if not meta: return
        menu = QMenu(self)
        act_pin    = menu.addAction("⬆ 置顶")
        act_resync = menu.addAction("🔄 重新同步视频")
        act_clear  = menu.addAction("✕ 清空视频缓存")
        menu.addSeparator()
        act_del = menu.addAction("🗑 删除此收藏夹记录")
        act = menu.exec_(self.folder_list.viewport().mapToGlobal(pos))
        if act == act_pin:
            self._folders_meta = [meta] + [f for f in self._folders_meta if f["id"] != fid]
            save_folder_index(self._folders_meta)
            self._refresh_folder_list()
        elif act == act_resync:
            self.folder_list.setCurrentItem(item)
            self._resync_folder_videos()
        elif act == act_clear:
            self.folder_list.setCurrentItem(item)
            self._clear_folder_cache()
        elif act == act_del:
            r = QMessageBox.question(self, "确认删除",
                f"从本地记录中删除「{meta['name']}」？（不影响抖音账号，不删除已下载视频）",
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes: return
            self._folders_meta = [f for f in self._folders_meta if f["id"] != fid]
            cache_path = os.path.join(CACHE_DIR, f"{fid}.json")
            try: os.remove(cache_path)
            except Exception: pass
            save_folder_index(self._folders_meta)
            self._refresh_folder_list()
            if self._current_folder and self._current_folder["id"] == fid:
                self._current_folder = None
                self._clear_grid()
                self.grid_title.setText("请选择左侧收藏夹")
            self._glog(f"已删除收藏夹记录「{meta['name']}」")

    # ══════════════════════════════════════════════════════════════════
    # 自己的作品/喜欢/历史观看 tab（通用模板）
    # ══════════════════════════════════════════════════════════════════
    def _setup_self_tab_ui(self, widget, mode):
        MODE_LABELS = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
        label = MODE_LABELS.get(mode, mode)
        lay = QVBoxLayout(widget)
        lay.setSpacing(7); lay.setContentsMargins(10, 9, 10, 7)

        top = QHBoxLayout(); top.setSpacing(8)
        sync_btn = QPushButton(f"⬇ 同步{label}")
        sync_btn.setStyleSheet(
            "QPushButton{background:#007acc;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#1a8fdd;} QPushButton:pressed{background:#005fa3;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        sync_btn.clicked.connect(lambda: self._start_self_sync(mode))
        top.addWidget(sync_btn)

        pause_btn = QPushButton("⏸ 暂停")
        pause_btn.setStyleSheet(
            "QPushButton{background:#f57c00;color:white;font-weight:bold;padding:6px 12px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#fb8c00;} QPushButton:pressed{background:#e65100;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        pause_btn.setEnabled(False)
        pause_btn.setVisible(False)
        top.addWidget(pause_btn)

        cancel_btn = QPushButton("✕ 停止")
        cancel_btn.setStyleSheet(
            "QPushButton{background:#c62828;color:white;font-weight:bold;padding:6px 12px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#e53935;} QPushButton:pressed{background:#b71c1c;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        cancel_btn.setEnabled(False)
        cancel_btn.setVisible(False)
        top.addWidget(cancel_btn)

        dl_all_btn = QPushButton("↓ 下载全部")
        dl_all_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#388e3c;} QPushButton:pressed{background:#1b5e20;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        dl_all_btn.setEnabled(False)
        dl_all_btn.clicked.connect(lambda: self._self_dl_all(mode))
        top.addWidget(dl_all_btn)

        sel_all_btn = QPushButton("全选")
        sel_all_btn.setStyleSheet(
            "QPushButton{padding:6px 10px;border-radius:4px;border:1px solid #555;}"
            "QPushButton:hover{background:#444;}")
        sel_all_btn.clicked.connect(lambda: self._self_select_all(mode))
        top.addWidget(sel_all_btn)

        sel_none_btn = QPushButton("取消选择")
        sel_none_btn.setStyleSheet(
            "QPushButton{padding:6px 10px;border-radius:4px;border:1px solid #555;}"
            "QPushButton:hover{background:#444;}")
        sel_none_btn.clicked.connect(lambda: self._self_select_none(mode))
        top.addWidget(sel_none_btn)

        batch_dl_btn = QPushButton("⬇ 批量下载选中")
        batch_dl_btn.setStyleSheet(
            "QPushButton{background:#e65100;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#f57c00;} QPushButton:pressed{background:#bf360c;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        batch_dl_btn.setEnabled(False)
        batch_dl_btn.clicked.connect(lambda: self._self_batch_download(mode))
        top.addWidget(batch_dl_btn)
        top.addStretch()

        limit_lbl = QLabel("同步数量：")
        limit_lbl.setStyleSheet("color:#aaa;")
        top.addWidget(limit_lbl)
        from PyQt5.QtWidgets import QSpinBox
        limit_spin = QSpinBox()
        limit_spin.setRange(0, 9999)
        default_limit = {
            "like": self._app_settings.get("like_sync_limit", 100),
        }.get(mode, self._app_settings.get("post_sync_limit", 50))
        limit_spin.setValue(default_limit)
        limit_spin.setSuffix("  个")
        limit_spin.setSpecialValueText("不限")
        limit_spin.setFixedWidth(90)
        limit_spin.setToolTip("0 = 不限数量；默认同步前 100 个")
        limit_spin.setStyleSheet("QSpinBox{padding:3px 5px;border-radius:4px;border:1px solid #555;}")
        top.addWidget(limit_spin)

        status_lbl = QLabel("未同步")
        status_lbl.setStyleSheet("color:#aaa;")
        top.addWidget(status_lbl)
        lay.addLayout(top)

        prog = QProgressBar()
        prog.setVisible(False)
        lay.addWidget(prog)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(4, 4, 4, 4)
        grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(grid_container)
        lay.addWidget(scroll, 1)

        mode_data = {
            "sync_btn": sync_btn, "pause_btn": pause_btn, "cancel_btn": cancel_btn,
            "dl_all_btn": dl_all_btn,
            "batch_dl_btn": batch_dl_btn, "status_lbl": status_lbl,
            "limit_spin": limit_spin,
            "prog": prog, "scroll": scroll,
            "grid_layout": grid_layout, "grid_container": grid_container,
            "col_count": 0,
        }
        if not hasattr(self, "_self_tabs"):
            self._self_tabs = {}
        self._self_tabs[mode] = mode_data
        if not hasattr(self, "_self_cards"):
            self._self_cards = {}
        self._self_cards[mode] = {}
        if not hasattr(self, "_self_selected"):
            self._self_selected = {}
        self._self_selected[mode] = set()

        cache = load_self_cache(mode)
        if cache and cache.get("videos"):
            videos_snapshot = cache["videos"]
            ts = cache.get("synced_at", 0)
            from datetime import datetime as _dt
            t_str = _dt.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""
            status_lbl.setText(f"缓存 {len(videos_snapshot)} 个  {t_str}")
            dl_all_btn.setEnabled(True)
            QTimer.singleShot(50, lambda m=mode, v=videos_snapshot: self._self_populate_grid(m, v, append=False))

    def _self_populate_grid(self, mode, videos, append=True):
        md = self._self_tabs[mode]
        grid = md["grid_layout"]
        cards = self._self_cards[mode]
        selected = self._self_selected[mode]
        if not append:
            while grid.count():
                item = grid.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            cards.clear()
        scroll = md["scroll"]
        avail = scroll.viewport().width()
        if not avail:
            avail = scroll.width() - scroll.verticalScrollBar().width() - 4
        if not avail:
            avail = self.width() - 240
        if not avail and not append:
            # viewport not ready yet; retry after a short delay
            QTimer.singleShot(150, lambda m=mode, v=list(videos): self._self_populate_grid(m, v, append=False))
            return
        col_count = max(1, avail // (VideoCard.W + 10))
        md["col_count"] = col_count
        for vm in videos:
            aid = vm.get("aweme_id", "")
            if not aid or aid in cards: continue
            card = VideoCard(vm, self._save_dir)
            if aid in selected:
                card.set_selected(True)
            card._chk.stateChanged.connect(
                lambda state, a=aid, m=mode: self._self_on_card_check(m, a, state))
            _src_map = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
            _src = _src_map.get(mode, "我的")
            card.download_requested.connect(
                lambda v, s=_src: self._do_add_download(v["title"], v["url"], v["aweme_id"],
                                                        source=s, author=v.get("author","")))
            card.remove_from_dl_requested.connect(self._remove_card_from_dl)
            card.delete_local_requested.connect(self._delete_local_file)
            idx = len(cards)
            grid.addWidget(card, idx // col_count, idx % col_count)
            cards[aid] = card

    def _self_on_card_check(self, mode, aweme_id, state):
        sel = self._self_selected[mode]
        if state: sel.add(aweme_id)
        else: sel.discard(aweme_id)
        self._self_tabs[mode]["batch_dl_btn"].setEnabled(bool(sel))

    def _self_select_all(self, mode):
        for c in self._self_cards[mode].values():
            c.set_selected(True)
        self._self_tabs[mode]["batch_dl_btn"].setEnabled(bool(self._self_cards[mode]))

    def _self_select_none(self, mode):
        for c in self._self_cards[mode].values():
            c.set_selected(False)
        self._self_selected[mode].clear()
        self._self_tabs[mode]["batch_dl_btn"].setEnabled(False)

    def _self_dl_all(self, mode):
        cache = load_self_cache(mode)
        if not cache: return
        added = 0
        src_map = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
        src = src_map.get(mode, "我的")
        for vm in cache.get("videos", []):
            if not get_local_video_path(vm["aweme_id"], self._save_dir):
                self._do_add_download(vm["title"], vm["url"], vm["aweme_id"],
                                      source=src, author=vm.get("author",""))
                added += 1
        self._glog(f"已将 {added} 个视频加入下载队列")
        if added: self.top_tabs.setCurrentIndex(2)

    def _self_batch_download(self, mode):
        sel = self._self_selected[mode]
        cache = load_self_cache(mode)
        if not cache: return
        added = 0
        src_map = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
        src = src_map.get(mode, "我的")
        for vm in cache.get("videos", []):
            aid = vm.get("aweme_id", "")
            if aid in sel and not get_local_video_path(aid, self._save_dir):
                self._do_add_download(vm["title"], vm["url"], aid,
                                      source=src, author=vm.get("author",""))
                added += 1
        self._glog(f"已将 {added} 个选中视频加入下载队列")
        if added: self.top_tabs.setCurrentIndex(2)

    def _start_self_sync(self, mode):
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先在「我的收藏」设置 Cookie"); return
        # 若同一 mode 线程还在运行则拒绝重复启动
        old_thread = getattr(self, f"_self_{mode}_thread", None)
        if old_thread and old_thread.isRunning():
            return
        md = self._self_tabs[mode]
        limit = md["limit_spin"].value()
        md["sync_btn"].setEnabled(False)
        md["pause_btn"].setText("⏸ 暂停"); md["pause_btn"].setEnabled(True); md["pause_btn"].setVisible(True)
        md["cancel_btn"].setEnabled(True); md["cancel_btn"].setVisible(True)
        md["prog"].setVisible(True); md["prog"].setRange(0, 0)
        MODE_LABELS = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
        self._glog(f"▶ 开始同步{MODE_LABELS.get(mode, mode)}")
        grid = md["grid_layout"]
        while grid.count():
            item = grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._self_cards[mode].clear(); self._self_selected[mode].clear()
        thread = QThread()
        worker = MySelfVideoWorker(mode, self._cookie_str, limit=limit,
                                   show_browser=self._app_settings.get("show_browser", False))
        worker.moveToThread(thread)
        # 加入全局集合防止 Python GC 在线程结束前销毁对象
        _active_loaders.add(thread); _active_loaders.add(worker)
        thread.finished.connect(lambda t=thread, w=worker: (
            _active_loaders.discard(t), _active_loaders.discard(w)))
        worker.log.connect(self._glog)
        worker.video_batch.connect(lambda batch, m=mode: self._self_on_batch(m, batch))
        worker.cookie_expired.connect(
            lambda: QMessageBox.warning(self, "Cookie 过期", "请重新设置 Cookie"))
        worker.finished.connect(lambda cnt, m=mode: self._self_sync_done(m, cnt))
        thread.started.connect(worker.run)
        setattr(self, f"_self_{mode}_thread", thread)
        setattr(self, f"_self_{mode}_worker", worker)

        def _toggle_pause():
            w = getattr(self, f"_self_{mode}_worker", None)
            if not w: return
            if w._paused:
                w.resume()
                md["pause_btn"].setText("⏸ 暂停")
                self._glog("▶ 继续同步...")
            else:
                w.pause()
                md["pause_btn"].setText("▶ 继续")
                self._glog("⏸ 已暂停")

        def _do_cancel():
            w = getattr(self, f"_self_{mode}_worker", None)
            if w: w.cancel()
            self._glog("🛑 正在取消...")
            md["cancel_btn"].setEnabled(False)

        try: md["pause_btn"].clicked.disconnect()
        except Exception: pass
        try: md["cancel_btn"].clicked.disconnect()
        except Exception: pass
        md["pause_btn"].clicked.connect(_toggle_pause)
        md["cancel_btn"].clicked.connect(_do_cancel)

        thread.start()

    def _self_on_batch(self, mode, batch):
        self._self_populate_grid(mode, batch, append=True)
        cache = load_self_cache(mode) or {"videos": []}
        existing_ids = {v["aweme_id"] for v in cache["videos"]}
        for vm in batch:
            if vm["aweme_id"] not in existing_ids:
                cache["videos"].append(vm)
        save_self_cache(mode, cache["videos"])

    def _self_sync_done(self, mode, count):
        md = self._self_tabs[mode]
        md["sync_btn"].setEnabled(True)
        md["pause_btn"].setVisible(False); md["pause_btn"].setEnabled(False)
        md["cancel_btn"].setVisible(False); md["cancel_btn"].setEnabled(False)
        md["prog"].setVisible(False)
        from datetime import datetime as _dt
        md["status_lbl"].setText(f"共 {count} 个  {_dt.now().strftime('%m-%d %H:%M')}")
        md["dl_all_btn"].setEnabled(count > 0)
        MODE_LABELS = {"post": "我的作品", "like": "我的喜欢", "history": "历史观看"}
        self._glog(f"{'✅' if count else '❌'} {MODE_LABELS.get(mode, mode)}同步完成，共 {count} 个视频  上次同步 {_dt.now().strftime('%m-%d %H:%M')}")
        t = getattr(self, f"_self_{mode}_thread", None)
        # 只调 quit()，不调 wait()——避免在信号 slot 里死锁主线程
        if t:
            t.quit()
            setattr(self, f"_self_{mode}_thread", None)

    # ══════════════════════════════════════════════════════════════════
    # Tab 1: 用户视频（旧版，保留以防引用）
    # ══════════════════════════════════════════════════════════════════
    def _setup_uv_ui(self):
        lay = QVBoxLayout(self.uv_widget)
        lay.setSpacing(9); lay.setContentsMargins(14,11,14,9)

        lf = QFrame(); lf.setStyleSheet("QFrame{border:1px solid #007acc;border-radius:5px;}")
        ll = QVBoxLayout(lf); ll.setContentsMargins(9,5,9,5)
        lr = QHBoxLayout()
        lr.addWidget(QLabel("登录状态："))
        self.uv_login = QLabel("● 未登录")
        self.uv_login.setStyleSheet("color:#ff6666;font-weight:bold;")
        lr.addWidget(self.uv_login); lr.addStretch(); ll.addLayout(lr)
        br = QHBoxLayout()
        ob = QPushButton("① 打开抖音")
        ob.setStyleSheet("background:#555;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;")
        ob.clicked.connect(lambda: subprocess.Popen(["open","https://www.douyin.com"]))
        br.addWidget(ob)
        self.uv_ck_btn = QPushButton("② 设置 Cookie")
        self.uv_ck_btn.setStyleSheet("background:#e53935;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;")
        self.uv_ck_btn.clicked.connect(self.open_cookie_dialog)
        br.addWidget(self.uv_ck_btn); br.addStretch(); ll.addLayout(br)
        lay.addWidget(lf)

        ff = QFrame(); ff.setStyleSheet("QFrame{border:1px solid #444;border-radius:5px;}")
        fl = QVBoxLayout(ff); fl.setContentsMargins(9,5,9,5)
        fl.addWidget(QLabel("选择抓取内容："))
        fb = QHBoxLayout()
        self.prof_btn = QPushButton("▶  用户主页视频"); self.prof_btn.setMinimumHeight(34)
        self.prof_btn.clicked.connect(lambda: self._start_uv("profile"))
        self.like_btn = QPushButton("♥  用户喜欢视频"); self.like_btn.setMinimumHeight(34)
        self.like_btn.clicked.connect(lambda: self._start_uv("like"))
        fb.addWidget(self.prof_btn); fb.addWidget(self.like_btn); fl.addLayout(fb)
        ur = QHBoxLayout(); ur.addWidget(QLabel("用户 UID 或主页链接："))
        self.uid_input = QLineEdit()
        self.uid_input.setPlaceholderText("MS4wLjABAAAAxxx 或 https://www.douyin.com/user/xxx")
        ur.addWidget(self.uid_input, 1); fl.addLayout(ur)
        lay.addWidget(ff)

        self.uv_log = QTextEdit(); self.uv_log.setReadOnly(True)
        self.uv_log.setPlaceholderText("抓取日志..."); lay.addWidget(self.uv_log, 1)

        bot = QHBoxLayout()
        self.uv_prog = QProgressBar(); self.uv_prog.setVisible(False)
        bot.addWidget(self.uv_prog, 1); bot.addStretch()
        self.uv_add_btn = QPushButton("添加到下载中心")
        self.uv_add_btn.setEnabled(False)
        self.uv_add_btn.clicked.connect(self._uv_add_all)
        bot.addWidget(self.uv_add_btn); lay.addLayout(bot)
        self.uv_status = QLabel("请先登录，然后输入 UID 选择抓取功能")
        self.uv_status.setStyleSheet("color:#aaa;padding:2px;")
        lay.addWidget(self.uv_status)

    def _start_uv(self, ft):
        if not getattr(self,"_cookie_str",""):
            QMessageBox.warning(self,"未登录","请先设置 Cookie"); return
        uid = self._extract_uid(self.uid_input.text().strip())
        if not uid:
            QMessageBox.warning(self,"需要 UID","请输入目标用户 UID 或主页链接"); return
        self.video_data = []; self.uv_log.clear()
        self.uv_add_btn.setEnabled(False)
        self.uv_prog.setVisible(True); self.uv_prog.setRange(0,0)
        self._uv_thread = QThread()
        self._uv_worker = FetchWorker(ft, uid, self._cookie_str,
                                      show_browser=self._app_settings.get("show_browser", False))
        self._uv_worker.moveToThread(self._uv_thread)
        self._uv_worker.log.connect(self.uv_log.append)
        self._uv_worker.log.connect(lambda m: self.uv_status.setText(m[:100]))
        self._uv_worker.video_found.connect(self._uv_found)
        self._uv_worker.finished.connect(self._uv_done)
        self._uv_thread.started.connect(self._uv_worker.run)
        self._uv_thread.start()

    def _uv_found(self, title, url, meta):
        if not any(m.get("aweme_id")==meta["aweme_id"] for _,_,m in self.video_data):
            self.video_data.append((title, url, meta))
            self.uv_log.append(f"  ✓ {title}")

    def _uv_done(self, count):
        self._uv_thread.quit(); self._uv_thread.wait()
        self._uv_worker = None
        self.uv_prog.setVisible(False)
        self.uv_status.setText(f"抓取完成，共 {count} 个视频")
        if count: self.uv_add_btn.setEnabled(True)
        self.uv_log.append(f"\n{'✅' if count else '❌'} 共 {count} 个视频" +
                           ("，点击「添加到下载中心」" if count else "，Cookie 可能已过期"))

    def _uv_add_all(self):
        for t,u,m in self.video_data:
            self._do_add_download(t, u, m.get("aweme_id",""),
                                  source="发现用户", author=m.get("author",""))
        self.top_tabs.setCurrentIndex(2)

    # ══════════════════════════════════════════════════════════════════
    # "发现" tab：用户视频卡片化展示
    # ══════════════════════════════════════════════════════════════════
    def _setup_discover_ui(self):
        lay = QVBoxLayout(self.discover_widget)
        lay.setSpacing(7); lay.setContentsMargins(10, 9, 10, 7)

        # 顶部输入栏
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("UID / 主页链接："))
        self.disc_uid_input = QLineEdit()
        self.disc_uid_input.setPlaceholderText("MS4wLjABAAAAxxx 或 https://www.douyin.com/user/xxx")
        input_row.addWidget(self.disc_uid_input, 1)
        disc_add_btn = QPushButton("搜索 / 添加用户")
        disc_add_btn.setStyleSheet(
            "QPushButton{background:#007acc;color:white;font-weight:bold;padding:6px 14px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#1a8fdd;}")
        disc_add_btn.clicked.connect(self._disc_add_user)
        input_row.addWidget(disc_add_btn)
        lay.addLayout(input_row)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧用户列表
        left_w = QWidget()
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 0, 0); left_lay.setSpacing(4)
        left_lay.addWidget(QLabel("用户列表"))
        self.disc_user_list = QListWidget()
        self.disc_user_list.setMinimumWidth(190)
        self.disc_user_list.setMaximumWidth(250)
        self.disc_user_list.setSpacing(0)
        self.disc_user_list.setUniformItemSizes(True)
        self.disc_user_list.currentRowChanged.connect(self._disc_on_user_selected)
        left_lay.addWidget(self.disc_user_list, 1)
        del_user_btn = QPushButton("删除用户")
        del_user_btn.setStyleSheet("color:#ff6666;")
        del_user_btn.clicked.connect(self._disc_delete_user)
        left_lay.addWidget(del_user_btn)
        splitter.addWidget(left_w)

        # 右侧详情
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0); right_lay.setSpacing(6)

        # 用户信息卡片 — 样式由主题 QSS 的 #discInfoCard 规则控制
        self.disc_info_card = QFrame()
        self.disc_info_card.setObjectName("discInfoCard")
        info_lay = QHBoxLayout(self.disc_info_card)
        info_lay.setContentsMargins(16, 12, 16, 12); info_lay.setSpacing(16)
        self.disc_avatar_lbl = QLabel()
        self.disc_avatar_lbl.setFixedSize(80, 80)
        self.disc_avatar_lbl.setObjectName("discAvatar")
        self.disc_avatar_lbl.setAlignment(Qt.AlignCenter)
        info_lay.addWidget(self.disc_avatar_lbl)
        meta_lay = QVBoxLayout(); meta_lay.setSpacing(4)
        self.disc_name_lbl = QLabel("请选择或添加用户")
        self.disc_name_lbl.setObjectName("discName")
        self.disc_sig_lbl = QLabel("")
        self.disc_sig_lbl.setObjectName("discSig")
        self.disc_sig_lbl.setWordWrap(True)
        self.disc_stats_lbl = QLabel("")
        self.disc_stats_lbl.setObjectName("discStats")
        meta_lay.addWidget(self.disc_name_lbl)
        meta_lay.addWidget(self.disc_sig_lbl)
        meta_lay.addWidget(self.disc_stats_lbl)
        info_lay.addLayout(meta_lay, 1)

        disc_refresh_btns = QVBoxLayout()
        self.disc_refresh_info_btn = QPushButton("刷新用户信息")
        self.disc_refresh_info_btn.setEnabled(False)
        self.disc_refresh_info_btn.setStyleSheet(
            "QPushButton{background:#5c6bc0;color:white;padding:5px 10px;border-radius:4px;border:none;}"
            "QPushButton:hover{background:#7986cb;} QPushButton:disabled{background:#555;color:#999;}")
        self.disc_refresh_info_btn.clicked.connect(self._disc_refresh_user_info)
        disc_refresh_btns.addWidget(self.disc_refresh_info_btn)
        self.disc_sync_post_btn = QPushButton("同步视频作品")
        self.disc_sync_post_btn.setEnabled(False)
        self.disc_sync_post_btn.setStyleSheet(
            "QPushButton{background:#007acc;color:white;padding:5px 10px;border-radius:4px;border:none;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.disc_sync_post_btn.clicked.connect(lambda: self._disc_start_sync("post"))
        disc_refresh_btns.addWidget(self.disc_sync_post_btn)
        info_lay.addLayout(disc_refresh_btns)
        right_lay.addWidget(self.disc_info_card)

        # 批量操作栏
        batch_row = QHBoxLayout()
        disc_sel_all = QPushButton("全选")
        disc_sel_all.setStyleSheet("padding:5px 10px;border-radius:4px;border:1px solid #555;")
        disc_sel_all.clicked.connect(self._disc_select_all)
        disc_sel_none = QPushButton("取消")
        disc_sel_none.setStyleSheet("padding:5px 10px;border-radius:4px;border:1px solid #555;")
        disc_sel_none.clicked.connect(self._disc_select_none)
        self.disc_batch_dl_btn = QPushButton("⬇ 批量下载")
        self.disc_batch_dl_btn.setEnabled(False)
        self.disc_batch_dl_btn.setStyleSheet(
            "QPushButton{background:#e65100;color:white;font-weight:bold;padding:5px 14px;border-radius:4px;border:none;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.disc_batch_dl_btn.clicked.connect(self._disc_batch_download)
        self.disc_status_lbl = QLabel("")
        self.disc_status_lbl.setStyleSheet("color:#aaa;")
        batch_row.addWidget(disc_sel_all)
        batch_row.addWidget(disc_sel_none)
        batch_row.addWidget(self.disc_batch_dl_btn)
        batch_row.addStretch()
        batch_row.addWidget(self.disc_status_lbl)
        right_lay.addLayout(batch_row)

        # 视频作品网格（不再有子 tab）
        self.disc_video_tabs = QWidget()
        disc_video_lay = QVBoxLayout(self.disc_video_tabs)
        disc_video_lay.setContentsMargins(0, 0, 0, 0)
        post_w = QWidget()
        self._disc_setup_video_grid(post_w, "post")
        disc_video_lay.addWidget(post_w)
        right_lay.addWidget(self.disc_video_tabs, 1)

        splitter.addWidget(right_w)
        splitter.setSizes([180, 820])
        lay.addWidget(splitter, 1)

        self._disc_current_uid = None
        self._disc_cards = {"post": {}, "like": {}}
        self._disc_selected = {"post": set(), "like": set()}
        self._disc_load_user_list()
        self._disc_set_avatar_placeholder()

    def _disc_setup_video_grid(self, widget, mode):
        lay = QVBoxLayout(widget)
        lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(8); grid.setContentsMargins(4, 4, 4, 4)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(container)
        lay.addWidget(scroll)
        setattr(self, f"_disc_{mode}_scroll", scroll)
        setattr(self, f"_disc_{mode}_grid", grid)
        if not hasattr(self, "_disc_col_count"):
            self._disc_col_count = {}
        self._disc_col_count[mode] = 0

    def _disc_make_user_item(self, uid, nickname, avatar_url="", info=None):
        """Create a QListWidgetItem + UserListItemWidget pair and start avatar load if URL given."""
        item = QListWidgetItem()
        item.setData(Qt.UserRole, uid)
        widget = UserListItemWidget(uid, nickname)
        item.setSizeHint(QSize(190, 76))
        if info:
            widget.set_unique_id(info.get("unique_id", ""))
            widget.set_stats(info.get("follower_count", 0), info.get("following_count", 0))
        if avatar_url:
            ldr = AvatarLoader(uid, avatar_url)
            ldr.loaded.connect(lambda u, pix, w=widget: w.set_avatar(pix) if u == w.uid else None)
            ldr.start()
        return item, widget

    def _disc_load_user_list(self):
        self.disc_user_list.clear()
        for u in load_users_index():
            info = load_user_cache(u["uid"]) or {}
            item, widget = self._disc_make_user_item(
                u["uid"], u.get("nickname", u["uid"]), u.get("avatar_url", ""), info=info)
            self.disc_user_list.addItem(item)
            self.disc_user_list.setItemWidget(item, widget)

    def _disc_add_user(self):
        raw = self.disc_uid_input.text().strip()
        if not raw:
            QMessageBox.warning(self, "需要输入", "请输入用户 UID 或主页链接"); return
        uid = self._extract_uid(raw)
        if not uid:
            QMessageBox.warning(self, "无效输入", "无法识别 UID，请检查输入"); return
        users = load_users_index()
        if any(u["uid"] == uid for u in users):
            for i in range(self.disc_user_list.count()):
                item = self.disc_user_list.item(i)
                if item.data(Qt.UserRole) == uid:
                    self.disc_user_list.setCurrentRow(i); return
        users.append({"uid": uid, "nickname": uid, "avatar_url": "", "synced_at": 0})
        save_users_index(users)
        item, widget = self._disc_make_user_item(uid, uid)
        self.disc_user_list.addItem(item)
        self.disc_user_list.setItemWidget(item, widget)
        self.disc_user_list.setCurrentRow(self.disc_user_list.count() - 1)
        # 新用户无缓存，立即同步以获取真实昵称/头像/视频
        self.disc_uid_input.clear()
        self._disc_start_sync("post")

    def _disc_on_user_selected(self, row):
        if row < 0: return
        item = self.disc_user_list.item(row)
        if not item: return
        uid = item.data(Qt.UserRole)
        self._disc_current_uid = uid
        for mode in ("post",):
            grid = getattr(self, f"_disc_{mode}_grid")
            while grid.count():
                w = grid.takeAt(0)
                if w.widget(): w.widget().deleteLater()
            self._disc_cards[mode].clear()
            self._disc_selected[mode].clear()
        self.disc_batch_dl_btn.setEnabled(False)
        info = load_user_cache(uid)
        if info:
            self._disc_update_info_card(info)
            for mode in ("post",):
                vcache = load_user_videos_cache(uid, mode)
                if vcache and vcache.get("videos"):
                    self._disc_populate_grid(mode, vcache["videos"])
                if vcache and vcache.get("synced_at"):
                    from datetime import datetime as _dt
                    ts = _dt.fromtimestamp(vcache["synced_at"]).strftime("%Y-%m-%d %H:%M")
                    self.disc_status_lbl.setText(f"上次同步：{ts}，共 {len(vcache.get('videos', []))} 个")
        else:
            self.disc_name_lbl.setText(uid)
            self.disc_sig_lbl.setText(""); self.disc_stats_lbl.setText("")
            self._disc_set_avatar_placeholder()
        self.disc_sync_post_btn.setEnabled(True)
        self.disc_refresh_info_btn.setEnabled(True)

    def _disc_update_info_card(self, info):
        self.disc_name_lbl.setText(info.get("nickname", info.get("uid", "")))
        self.disc_sig_lbl.setText(info.get("signature", ""))
        fc = info.get("follower_count", 0)
        fwc = info.get("following_count", 0)
        ac = info.get("aweme_count", 0)
        self.disc_stats_lbl.setText(f"粉丝 {fc:,}  关注 {fwc:,}  作品 {ac:,}")
        self._disc_set_avatar_placeholder()
        avatar_url = info.get("avatar_url", "")
        if avatar_url:
            ldr = AvatarLoader(info.get("uid", ""), avatar_url)
            ldr.loaded.connect(self._disc_on_avatar)
            ldr.start()

    def _disc_set_avatar_placeholder(self):
        s = 80
        ph = QPixmap(s, s); ph.fill(Qt.transparent)
        painter = QPainter(ph)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor("#444")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, s, s)
        painter.end()
        self.disc_avatar_lbl.setPixmap(ph)

    def _disc_on_avatar(self, uid, pixmap):
        if uid != self._disc_current_uid: return
        self.disc_avatar_lbl.setPixmap(_make_circle_pixmap(pixmap, 80))

    def _disc_populate_grid(self, mode, videos):
        grid = getattr(self, f"_disc_{mode}_grid")
        cards = self._disc_cards[mode]
        scroll = getattr(self, f"_disc_{mode}_scroll")
        avail = scroll.viewport().width() or (self.width() - 20)
        col_count = max(1, avail // (VideoCard.W + 10))
        if not hasattr(self, "_disc_col_count"):
            self._disc_col_count = {}
        self._disc_col_count[mode] = col_count
        for vm in videos:
            aid = vm.get("aweme_id", "")
            if not aid or aid in cards: continue
            card = VideoCard(vm, self._save_dir)
            if aid in self._disc_selected[mode]:
                card.set_selected(True)
            card._chk.stateChanged.connect(
                lambda state, a=aid, m=mode: self._disc_on_card_check(m, a, state))
            card.download_requested.connect(
                lambda v: self._do_add_download(v["title"], v["url"], v["aweme_id"],
                                                source="发现用户", author=v.get("author","")))
            card.remove_from_dl_requested.connect(self._remove_card_from_dl)
            card.delete_local_requested.connect(self._delete_local_file)
            idx = len(cards)
            grid.addWidget(card, idx // col_count, idx % col_count)
            cards[aid] = card

    def _disc_on_card_check(self, mode, aweme_id, state):
        if state: self._disc_selected[mode].add(aweme_id)
        else: self._disc_selected[mode].discard(aweme_id)
        total_sel = sum(len(s) for s in self._disc_selected.values())
        self.disc_batch_dl_btn.setEnabled(total_sel > 0)

    def _disc_select_all(self):
        mode = "post"
        for c in self._disc_cards[mode].values():
            c.set_selected(True)
        self.disc_batch_dl_btn.setEnabled(bool(self._disc_cards[mode]))

    def _disc_select_none(self):
        mode = "post"
        for c in self._disc_cards[mode].values():
            c.set_selected(False)
        self._disc_selected[mode].clear()
        total_sel = sum(len(s) for s in self._disc_selected.values())
        self.disc_batch_dl_btn.setEnabled(total_sel > 0)

    def _disc_batch_download(self):
        uid = self._disc_current_uid
        if not uid: return
        added = 0
        for mode in ("post", "like"):
            sel = self._disc_selected[mode]
            if not sel: continue
            vcache = load_user_videos_cache(uid, mode)
            if not vcache: continue
            for vm in vcache.get("videos", []):
                aid = vm.get("aweme_id", "")
                if aid in sel and not get_local_video_path(aid, self._save_dir):
                    self._do_add_download(vm["title"], vm["url"], aid,
                                          source="发现用户", author=vm.get("author","")); added += 1
        self._glog(f"已将 {added} 个选中视频加入下载队列")
        if added: self.top_tabs.setCurrentIndex(2)

    def _disc_delete_user(self):
        row = self.disc_user_list.currentRow()
        if row < 0: return
        item = self.disc_user_list.item(row)
        uid = item.data(Qt.UserRole)
        w = self.disc_user_list.itemWidget(item)
        display_name = w.name_lbl.text() if isinstance(w, UserListItemWidget) else uid
        r = QMessageBox.question(self, "确认删除", f"删除用户「{display_name}」及其缓存？",
                                 QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes: return
        save_users_index([u for u in load_users_index() if u["uid"] != uid])
        for suffix in ("_info.json", "_post.json", "_like.json"):
            p = os.path.join(USERS_CACHE_DIR, f"{uid}{suffix}")
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        self.disc_user_list.takeItem(row)
        self._disc_current_uid = None
        self.disc_name_lbl.setText("请选择或添加用户")
        self.disc_sig_lbl.setText(""); self.disc_stats_lbl.setText("")

    def _disc_start_sync(self, mode):
        uid = self._disc_current_uid
        if not uid:
            QMessageBox.warning(self, "未选择用户", "请先选择或添加用户"); return
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先在「我的收藏」设置 Cookie"); return
        # 若旧线程还在运行则拒绝重复启动
        if getattr(self, "_disc_uv_thread", None) and self._disc_uv_thread.isRunning():
            return
        grid = getattr(self, f"_disc_{mode}_grid")
        while grid.count():
            w = grid.takeAt(0)
            if w.widget(): w.widget().deleteLater()
        self._disc_cards[mode].clear(); self._disc_selected[mode].clear()
        self.disc_batch_dl_btn.setEnabled(False)
        self.disc_sync_post_btn.setEnabled(False)
        self.disc_refresh_info_btn.setEnabled(False)
        self._glog(f"▶ 开始同步用户「{uid}」视频作品")
        thread = QThread()
        worker = UserVideoWorker(mode, uid, self._cookie_str,
                                 show_browser=self._app_settings.get("show_browser", False))
        worker.moveToThread(thread)
        # 加入全局集合防止 Python GC 在线程结束前销毁对象
        _active_loaders.add(thread); _active_loaders.add(worker)
        thread.finished.connect(lambda t=thread, w=worker: (
            _active_loaders.discard(t), _active_loaders.discard(w)))
        worker.log.connect(self._glog)
        worker.user_info.connect(lambda info, u=uid: self._disc_on_user_info(info, u))
        worker.video_batch.connect(lambda batch, m=mode, u=uid: self._disc_on_video_batch(m, u, batch))
        worker.finished.connect(lambda cnt, m=mode: self._disc_on_sync_done(m, cnt))
        thread.started.connect(worker.run)
        self._disc_uv_thread = thread
        self._disc_uv_worker = worker
        thread.start()

    def _disc_on_user_info(self, info, uid):
        self._disc_update_info_card(info)
        save_user_cache(uid, info)
        nickname     = info.get("nickname", uid)
        avatar_url   = info.get("avatar_url", "")
        unique_id    = info.get("unique_id", "")
        follower_cnt = info.get("follower_count", 0)
        following_cnt = info.get("following_count", 0)
        for i in range(self.disc_user_list.count()):
            item = self.disc_user_list.item(i)
            if item and item.data(Qt.UserRole) == uid:
                w = self.disc_user_list.itemWidget(item)
                if isinstance(w, UserListItemWidget):
                    w.set_nickname(nickname)
                    w.set_unique_id(unique_id)
                    w.set_stats(follower_cnt, following_cnt)
                    if avatar_url:
                        ldr = AvatarLoader(uid, avatar_url)
                        ldr.loaded.connect(lambda u, pix, widget=w: widget.set_avatar(pix) if u == widget.uid else None)
                        ldr.start()
                break
        users = load_users_index()
        for u in users:
            if u["uid"] == uid:
                u.update({"nickname": nickname, "avatar_url": avatar_url,
                           "synced_at": time.time()}); break
        save_users_index(users)

    def _disc_on_video_batch(self, mode, uid, batch):
        if uid != self._disc_current_uid: return
        self._disc_populate_grid(mode, batch)
        vcache = load_user_videos_cache(uid, mode) or {"videos": []}
        existing = {v["aweme_id"] for v in vcache["videos"]}
        for vm in batch:
            if vm["aweme_id"] not in existing:
                vcache["videos"].append(vm)
        save_user_videos_cache(uid, mode, vcache["videos"])

    def _disc_on_sync_done(self, mode, count):
        from datetime import datetime as _dt
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M")
        self.disc_status_lbl.setText(f"上次同步：{now_str}，共 {count} 个")
        self._glog(f"{'✅' if count else '❌'} 用户视频同步完成，共 {count} 个  上次同步 {_dt.now().strftime('%m-%d %H:%M')}")
        self.disc_sync_post_btn.setEnabled(True)
        self.disc_refresh_info_btn.setEnabled(bool(self._disc_current_uid))
        if self._disc_uv_thread:
            # 只调 quit()，不调 wait()——避免在信号 slot 里死锁主线程
            self._disc_uv_thread.quit()
            self._disc_uv_thread = None; self._disc_uv_worker = None

    def _disc_refresh_user_info(self):
        uid = self._disc_current_uid
        if not uid:
            QMessageBox.warning(self, "未选择用户", "请先选择用户"); return
        if not getattr(self, "_cookie_str", ""):
            QMessageBox.warning(self, "未登录", "请先在「我的收藏」设置 Cookie"); return
        if getattr(self, "_disc_info_thread", None) and self._disc_info_thread.isRunning():
            return
        self.disc_refresh_info_btn.setEnabled(False)
        self.disc_refresh_info_btn.setText("获取中...")
        self._glog(f"▶ 正在刷新用户信息 UID={uid[:20]}...")
        thread = QThread()
        worker = UserInfoWorker(uid, self._cookie_str,
                                show_browser=self._app_settings.get("show_browser", False))
        worker.moveToThread(thread)
        _active_loaders.add(thread); _active_loaders.add(worker)
        thread.finished.connect(lambda t=thread, w=worker: (
            _active_loaders.discard(t), _active_loaders.discard(w)))
        worker.log.connect(self._glog)
        worker.user_info.connect(lambda info, u=uid: self._disc_on_user_info(info, u))
        worker.finished.connect(self._disc_on_info_refresh_done)
        thread.started.connect(worker.run)
        self._disc_info_thread = thread
        self._disc_info_worker = worker
        thread.start()

    def _disc_on_info_refresh_done(self):
        self.disc_refresh_info_btn.setText("刷新用户信息")
        self.disc_refresh_info_btn.setEnabled(bool(self._disc_current_uid))
        if self._disc_info_thread:
            self._disc_info_thread.quit()
            self._disc_info_thread = None; self._disc_info_worker = None

    # ══════════════════════════════════════════════════════════════════
    # Tab 3: 视频解析
    # ══════════════════════════════════════════════════════════════════
    def _setup_parse_ui(self):
        root = QVBoxLayout(self.parse_widget)
        root.setSpacing(0); root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle{background:#2a2a2a;}"
            "QSplitter::handle:hover{background:#3a3a3a;}")
        root.addWidget(splitter)

        # ══════════════════════════════════════════════════════════════
        # 上半部：当前解析
        # ══════════════════════════════════════════════════════════════
        top_panel = QWidget()
        top_panel.setObjectName("parseTopPanel")
        top_outer = QVBoxLayout(top_panel)
        top_outer.setContentsMargins(0, 0, 0, 0)
        top_outer.setSpacing(0)

        # 标题栏
        top_bar = QWidget()
        top_bar.setFixedHeight(38)
        top_bar.setStyleSheet("background:#1e1e1e;border-bottom:1px solid #2e2e2e;")
        top_bar_lay = QHBoxLayout(top_bar)
        top_bar_lay.setContentsMargins(16, 0, 16, 0)
        section_lbl = QLabel("当前解析")
        section_lbl.setStyleSheet("font-size:10pt;font-weight:bold;color:#888;letter-spacing:1px;")
        top_bar_lay.addWidget(section_lbl)
        top_bar_lay.addStretch()
        hint_lbl = QLabel("粘贴抖音分享文本，提取视频链接")
        hint_lbl.setStyleSheet("color:#555;font-size:9pt;")
        top_bar_lay.addWidget(hint_lbl)
        top_outer.addWidget(top_bar)

        # 内容区：居中限宽，输入框撑满剩余高度
        content_wrap = QWidget()
        content_lay = QVBoxLayout(content_wrap)
        content_lay.setContentsMargins(40, 20, 40, 16)
        content_lay.setSpacing(10)

        self.parse_input = QTextEdit()
        self.parse_input.setPlaceholderText(
            "粘贴抖音 App 分享复制的文本，例：\n"
            "2.84 07/23 T@y.tR  世间最难解的应该就是缘分\n"
            "https://v.douyin.com/L0hDLUdoYkg/ 复制此链接，打开Dou音搜索，直接观看视频！")
        self.parse_input.setMinimumHeight(60)
        self.parse_input.setStyleSheet(
            "QTextEdit{font-size:11pt;border-radius:6px;"
            "border:1px solid #3a3a3a;padding:6px;}")
        content_lay.addWidget(self.parse_input, 1)   # stretch=1：随面板高度拉伸

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.parse_btn = QPushButton("🔍  解析视频")
        self.parse_btn.setFixedHeight(36)
        self.parse_btn.setStyleSheet(
            "QPushButton{background:#007acc;color:white;font-weight:bold;"
            "padding:0 24px;border-radius:6px;border:none;font-size:11pt;}"
            "QPushButton:hover{background:#1a8fdd;} QPushButton:pressed{background:#005fa3;}"
            "QPushButton:disabled{background:#2a2a2a;color:#666;border:1px solid #3a3a3a;}")
        self.parse_btn.clicked.connect(self._parse_start)
        btn_row.addWidget(self.parse_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(36)
        clear_btn.setStyleSheet(
            "QPushButton{padding:0 16px;border-radius:6px;border:1px solid #3a3a3a;"
            "font-size:10pt;background:transparent;}"
            "QPushButton:hover{background:#2a2a2a;border-color:#555;}")
        clear_btn.clicked.connect(self._parse_clear)
        btn_row.addWidget(clear_btn)

        self.parse_status_lbl = QLabel("")
        self.parse_status_lbl.setStyleSheet("color:#aaa;font-size:10pt;padding-left:8px;")
        btn_row.addWidget(self.parse_status_lbl)
        btn_row.addStretch()
        content_lay.addLayout(btn_row)

        # 结果卡片（初始隐藏）
        self.parse_result_card = QFrame()
        self.parse_result_card.setObjectName("discInfoCard")
        self.parse_result_card.setVisible(False)
        result_lay = QHBoxLayout(self.parse_result_card)
        result_lay.setContentsMargins(18, 16, 18, 16); result_lay.setSpacing(18)

        self.parse_cover_lbl = QLabel()
        self.parse_cover_lbl.setFixedSize(108, 144)
        self.parse_cover_lbl.setStyleSheet(
            "background:#1a1a1a;border-radius:6px;border:1px solid #2a2a2a;")
        self.parse_cover_lbl.setAlignment(Qt.AlignCenter)
        result_lay.addWidget(self.parse_cover_lbl)

        meta_lay = QVBoxLayout(); meta_lay.setSpacing(6)
        self.parse_title_lbl = QLabel("")
        self.parse_title_lbl.setStyleSheet("font-size:13pt;font-weight:bold;")
        self.parse_title_lbl.setWordWrap(True)
        self.parse_author_lbl = QLabel("")
        self.parse_author_lbl.setStyleSheet("color:#aaa;font-size:10pt;")
        self.parse_id_lbl = QLabel("")
        self.parse_id_lbl.setStyleSheet("color:#555;font-size:9pt;")

        self.parse_dl_btn = QPushButton("⬇  加入下载")
        self.parse_dl_btn.setFixedHeight(34)
        self.parse_dl_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;"
            "padding:0 20px;border-radius:6px;border:none;font-size:11pt;}"
            "QPushButton:hover{background:#388e3c;} QPushButton:pressed{background:#1b5e20;}")
        self.parse_dl_btn.clicked.connect(self._parse_add_download)

        meta_lay.addWidget(self.parse_title_lbl)
        meta_lay.addWidget(self.parse_author_lbl)
        meta_lay.addWidget(self.parse_id_lbl)
        meta_lay.addStretch()
        meta_lay.addWidget(self.parse_dl_btn, 0, Qt.AlignLeft)
        result_lay.addLayout(meta_lay, 1)
        content_lay.addWidget(self.parse_result_card)  # stretch=0：固定高度

        top_outer.addWidget(content_wrap, 1)

        splitter.addWidget(top_panel)

        # ══════════════════════════════════════════════════════════════
        # 下半部：解析列表
        # ══════════════════════════════════════════════════════════════
        bot_panel = QWidget()
        bot_outer = QVBoxLayout(bot_panel)
        bot_outer.setContentsMargins(0, 0, 0, 0)
        bot_outer.setSpacing(0)

        # 标题栏
        bot_bar = QWidget()
        bot_bar.setFixedHeight(38)
        bot_bar.setStyleSheet("background:#1e1e1e;border-bottom:1px solid #2e2e2e;")
        bot_bar_lay = QHBoxLayout(bot_bar)
        bot_bar_lay.setContentsMargins(16, 0, 16, 0)
        hist_lbl = QLabel("解析列表")
        hist_lbl.setStyleSheet("font-size:10pt;font-weight:bold;color:#888;letter-spacing:1px;")
        bot_bar_lay.addWidget(hist_lbl)
        bot_bar_lay.addStretch()
        clear_hist_btn = QPushButton("清空列表")
        clear_hist_btn.setFixedHeight(24)
        clear_hist_btn.setStyleSheet(
            "QPushButton{padding:0 10px;border-radius:4px;border:1px solid #3a3a3a;"
            "font-size:9pt;background:transparent;}"
            "QPushButton:hover{background:#2a2a2a;border-color:#555;}")
        clear_hist_btn.clicked.connect(self._parse_clear_history)
        bot_bar_lay.addWidget(clear_hist_btn)
        bot_outer.addWidget(bot_bar)

        self.parse_hist_scroll = QScrollArea()
        self.parse_hist_scroll.setWidgetResizable(True)
        self.parse_hist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.parse_hist_scroll.setStyleSheet("QScrollArea{border:none;}")
        self.parse_hist_container = QWidget()
        self.parse_hist_layout = QVBoxLayout(self.parse_hist_container)
        self.parse_hist_layout.setSpacing(1)
        self.parse_hist_layout.setContentsMargins(0, 0, 0, 0)
        self.parse_hist_layout.addStretch()
        self.parse_hist_scroll.setWidget(self.parse_hist_container)
        bot_outer.addWidget(self.parse_hist_scroll, 1)

        splitter.addWidget(bot_panel)

        # 初始分割比例：上40% 下60%
        splitter.setSizes([400, 600])

        self._parse_result_meta = None
        self._parse_history_cards = {}   # aweme_id -> ParseHistoryCard
        self._parse_refresh_history()

    def _parse_refresh_history(self):
        records = load_parse_history()
        # clear existing cards
        while self.parse_hist_layout.count() > 1:
            item = self.parse_hist_layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
        self._parse_history_cards.clear()

        if not records:
            empty_lbl = QLabel("暂无解析记录")
            empty_lbl.setStyleSheet("color:#555;font-size:10pt;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self.parse_hist_layout.insertWidget(0, empty_lbl)
            return

        for record in reversed(records):
            card = ParseHistoryCard(record, self._save_dir)
            card.download_requested.connect(self._parse_hist_download)
            card.delete_requested.connect(self._parse_delete_record)
            self.parse_hist_layout.insertWidget(0, card)
            self._parse_history_cards[record["aweme_id"]] = card

    def _parse_hist_download(self, meta):
        self._do_add_download(meta["title"], meta["url"], meta["aweme_id"],
                              source="视频解析", author=meta.get("author", ""))
        self.top_tabs.setCurrentIndex(2)

    def _parse_delete_record(self, aweme_id):
        records = load_parse_history()
        records = [r for r in records if r.get("aweme_id") != aweme_id]
        save_parse_history(records)
        self._parse_refresh_history()

    def _parse_clear_history(self):
        save_parse_history([])
        self._parse_refresh_history()

    def _parse_start(self):
        text = self.parse_input.toPlainText().strip()
        if not text:
            self.parse_status_lbl.setText("请先粘贴分享内容"); return
        self._last_parse_input = text
        if getattr(self, "_parse_thread", None) and self._parse_thread.isRunning():
            return
        self.parse_btn.setEnabled(False)
        self.parse_status_lbl.setText("解析中...")
        self.parse_result_card.setVisible(False)
        self._parse_result_meta = None

        thread = QThread()
        worker = ShareLinkParser(text, getattr(self, "_cookie_str", ""))
        worker.moveToThread(thread)
        _active_loaders.add(thread); _active_loaders.add(worker)
        thread.finished.connect(lambda t=thread, w=worker: (
            _active_loaders.discard(t), _active_loaders.discard(w)))
        worker.log.connect(self._glog)
        worker.result.connect(self._parse_on_result)
        worker.failed.connect(self._parse_on_failed)
        thread.started.connect(worker.run)
        self._parse_thread = thread
        self._parse_worker = worker
        thread.start()

    def _parse_on_result(self, meta):
        self._parse_result_meta = meta
        self.parse_title_lbl.setText(meta.get("title", ""))
        self.parse_author_lbl.setText(f"作者：{meta.get('author', '')}")
        self.parse_id_lbl.setText(f"aweme_id：{meta.get('aweme_id', '')}")
        self.parse_cover_lbl.setText("⏳")
        self.parse_result_card.setVisible(True)
        self.parse_status_lbl.setText("✅ 解析成功")
        self.parse_btn.setEnabled(True)

        cover_url = meta.get("cover_url", "")
        if cover_url:
            ldr = CoverLoader(meta["aweme_id"], cover_url)
            ldr.loaded.connect(self._parse_on_cover)
            ldr.start()

        if self._parse_thread:
            self._parse_thread.quit()
            self._parse_thread = None; self._parse_worker = None

        # 保存到历史
        records = load_parse_history()
        # 去重：先移除同 aweme_id 的旧记录
        records = [r for r in records if r.get("aweme_id") != meta.get("aweme_id")]
        record = {
            "aweme_id":    meta.get("aweme_id", ""),
            "title":       meta.get("title", ""),
            "author":      meta.get("author", ""),
            "cover_url":   meta.get("cover_url", ""),
            "url":         meta.get("url", ""),
            "parsed_at":   time.time(),
            "raw_content": getattr(self, "_last_parse_input", ""),
        }
        records.append(record)
        save_parse_history(records)
        self._parse_refresh_history()

    def _parse_on_cover(self, _, pixmap):
        scaled = pixmap.scaled(120, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.parse_cover_lbl.setPixmap(scaled)

    def _parse_on_failed(self, msg):
        self.parse_status_lbl.setText(f"❌ {msg}")
        self._glog(f"解析失败：{msg}")
        self.parse_btn.setEnabled(True)
        if self._parse_thread:
            self._parse_thread.quit()
            self._parse_thread = None; self._parse_worker = None

    def _parse_add_download(self):
        meta = self._parse_result_meta
        if not meta: return
        self._do_add_download(meta["title"], meta["url"], meta["aweme_id"],
                              source="视频解析", author=meta.get("author", ""))
        self.top_tabs.setCurrentIndex(2)  # 跳转到下载 tab

    def _parse_clear(self):
        self.parse_input.clear()
        self.parse_result_card.setVisible(False)
        self.parse_status_lbl.setText("")
        self._parse_result_meta = None

    # ══════════════════════════════════════════════════════════════════
    # Tab 2: 下载中心
    # ══════════════════════════════════════════════════════════════════
    def _setup_dl_ui(self):
        lay = QVBoxLayout(self.dl_widget); lay.setSpacing(9)

        top = QHBoxLayout()
        top.addWidget(QLabel("下载到:"))
        self.dir_input = QLineEdit(self._save_dir); self.dir_input.setReadOnly(True)
        self.dir_input.setMinimumWidth(320); top.addWidget(self.dir_input)
        cb = QPushButton("选择"); cb.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        cb.clicked.connect(self._choose_dir); top.addWidget(cb)
        ob = QPushButton("打开"); ob.setIcon(self.style().standardIcon(QStyle.SP_DirLinkIcon))
        ob.clicked.connect(self._open_dir); top.addWidget(ob)
        top.addStretch()
        for txt, slot, ico in (("全部开始",self._dl_start_all,QStyle.SP_MediaPlay),
                                ("全部暂停",self._dl_pause_all,QStyle.SP_MediaPause),
                                ("清空",    self._dl_clear,    QStyle.SP_TrashIcon)):
            b = QPushButton(txt); b.setObjectName("ctrl")
            b.setIcon(self.style().standardIcon(ico))
            b.clicked.connect(slot); top.addWidget(b)
        self.dl_batch_del_btn = QPushButton("🗑 删除选中")
        self.dl_batch_del_btn.setStyleSheet(
            "QPushButton{background:#c62828;color:white;font-weight:bold;padding:5px 12px;"
            "border-radius:4px;border:none;}"
            "QPushButton:hover{background:#e53935;}"
            "QPushButton:pressed{background:#b71c1c;}"
            "QPushButton:disabled{background:#555;color:#999;}")
        self.dl_batch_del_btn.clicked.connect(self._dl_batch_delete)
        top.addWidget(self.dl_batch_del_btn)
        lay.addLayout(top)

        # 搜索栏
        search_bar = QHBoxLayout()
        search_bar.addWidget(QLabel("🔍"))
        self.dl_search = QLineEdit()
        self.dl_search.setPlaceholderText("搜索标题...")
        self.dl_search.setClearButtonEnabled(True)
        self.dl_search.textChanged.connect(self._filter_dl_table)
        search_bar.addWidget(self.dl_search)
        search_bar.addStretch()
        self.dl_stat_lbl = QLabel("")
        self.dl_stat_lbl.setStyleSheet("color:#aaa;font-size:9pt;")
        search_bar.addWidget(self.dl_stat_lbl)
        lay.addLayout(search_bar)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep)

        self.dl_table = QTableWidget()
        self.dl_table.setColumnCount(10)
        self.dl_table.setHorizontalHeaderLabels(["视频标题","作者","进度","状态","操作","大小","添加时间 ▼","ID","本地路径","来源"])
        self.dl_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.dl_table.setAlternatingRowColors(True)
        self.dl_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.dl_table.verticalHeader().setVisible(False)
        self.dl_table.setColumnWidth(1, 90); self.dl_table.setColumnWidth(2,120)
        self.dl_table.setColumnWidth(3, 90); self.dl_table.setColumnWidth(4,240)
        self.dl_table.setColumnWidth(5, 100); self.dl_table.setColumnWidth(6, 140)
        self.dl_table.setColumnWidth(9, 160)
        self.dl_table.hideColumn(7); self.dl_table.hideColumn(8)
        self.dl_table.verticalHeader().setDefaultSectionSize(54)
        self.dl_table.setSortingEnabled(False)
        self._dl_time_desc = True  # 当前排序方向：True=倒序（新→旧）
        self.dl_table.horizontalHeader().sectionClicked.connect(self._dl_header_clicked)
        self.dl_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.dl_table.customContextMenuRequested.connect(self._dl_context_menu)
        lay.addWidget(self.dl_table)

    # ── 下载记录持久化恢复 ───────────────────────────────────────────

    def _dl_context_menu(self, pos):
        row = self.dl_table.rowAt(pos.y())
        if row < 0:
            return
        tid_item = self.dl_table.item(row, 7)
        if not tid_item:
            return
        tid = tid_item.text()
        rec = _dl_records.get(tid, {})
        dl_url = rec.get("url", "")
        if not dl_url:
            return
        menu = QMenu(self.dl_table)
        cp_act = menu.addAction("复制下载链接")
        cp_act.triggered.connect(lambda: QApplication.clipboard().setText(dl_url))
        menu.exec_(self.dl_table.viewport().mapToGlobal(pos))
    def _restore_dl_records(self):
        global _dl_records
        records = load_dl_records()
        # 默认按添加时间倒序（新→旧）
        records = sorted(records, key=lambda r: r.get("added_at", 0), reverse=True)
        has_pending = False
        for rec in records:
            tid   = rec.get("task_id", "")
            title = rec.get("title", "")
            url   = rec.get("url", "")
            aid   = rec.get("aweme_id", "") or tid
            lp    = rec.get("local_path", "")
            added = rec.get("added_at", 0)

            if lp and not os.path.exists(lp):
                lp = ""
            if not lp and aid:
                lp = get_local_video_path(aid, self._save_dir) or ""

            status = rec.get("status", "已完成")
            if status in ("已完成", "文件已删除"):
                status = "已完成" if lp else "文件已删除"

            _dl_records[tid] = {"task_id": tid, "title": title, "url": url,
                                 "aweme_id": aid, "status": status,
                                 "local_path": lp, "added_at": added,
                                 "source": rec.get("source", ""),
                                 "author": rec.get("author", "")}
            self._insert_dl_row(tid, title, status, lp)

            # 对等待中的任务重建 DownloadTask，使其可被 schedule() 启动
            if status == "等待中" and url:
                existing = self.dl_mgr.tasks.get(tid)
                if not existing:
                    self.dl_mgr.add_task(url, title, aid)
                task = self.dl_mgr.tasks.get(tid)
                if task:
                    try: task.progress_updated.connect(self._dl_prog)
                    except Exception: pass
                    try: task.status_updated.connect(self._dl_stat)
                    except Exception: pass
                    try: task.download_finished.connect(self._dl_fin)
                    except Exception: pass
                has_pending = True

        self._update_dl_stat_label()
        if has_pending:
            self.dl_mgr.schedule()  # 启动等待中任务

    def _save_dl_records(self):
        save_dl_records(list(_dl_records.values()))

    def _do_add_download(self, title, url, aweme_id, source="", author=""):
        """统一入口：创建任务 + 加行 + 持久化"""
        tid = self.dl_mgr.add_task(url, title, aweme_id)
        task = self.dl_mgr.tasks[tid]
        # 总是重新连接信号（add_task 可能已替换了旧的失败任务对象）
        try: task.progress_updated.connect(self._dl_prog)
        except Exception: pass
        try: task.status_updated.connect(self._dl_stat)
        except Exception: pass
        try: task.download_finished.connect(self._dl_fin)
        except Exception: pass
        if self._find_row(tid) is not None:
            # 行已存在（重新下载相同视频）：更新状态显示，直接调度
            r = self._find_row(tid)
            item = self.dl_table.item(r, 3)
            if item: item.setText("等待中"); self._color_status_item(item, "等待中")
            self._update_dl_row_buttons(r, tid, "等待中", None)
            _update_dl_record(tid, status="等待中")
            self._update_dl_stat_label()
            self.dl_mgr.schedule()
            return
        _update_dl_record(tid, title=title, url=url, aweme_id=aweme_id,
                          status="等待中", added_at=time.time(), source=source, author=author)
        self._insert_dl_row(tid, title, "等待中", "")
        self._update_dl_stat_label()
        self.dl_mgr.schedule()  # 自动开始（受并发限制）

    def _remove_card_from_dl(self, aweme_id: str):
        """从三点菜单触发：从下载列表删除该任务。"""
        tid = aweme_id
        task = self.dl_mgr.tasks.get(tid)
        if task:
            task.cancel()
        self.dl_mgr.tasks.pop(tid, None)
        _dl_records.pop(tid, None)
        r = self._find_row(tid)
        if r is not None:
            self.dl_table.removeRow(r)
        self._cards.pop(tid, None)
        self._save_dl_records()
        self._update_dl_stat_label()
        # 恢复该卡片的下载按钮
        self._update_card_dl_status(tid, "已取消")

    def _delete_local_file(self, aweme_id: str):
        """从 VideoCard ⋮ 菜单触发：删除本地文件，不影响下载记录。"""
        local_path = get_local_video_path(aweme_id, self._save_dir)
        if not local_path or not os.path.exists(local_path):
            QMessageBox.information(self, "提示", "本地文件不存在"); return
        reply = QMessageBox.question(
            self, "删除本地文件",
            f"确认删除本地文件？\n{local_path}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(local_path)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e)); return
        # 更新下载记录状态
        _update_dl_record(aweme_id, status="文件已删除", local_path="")
        r = self._find_row(aweme_id)
        if r is not None:
            item = self.dl_table.item(r, 3)
            if item: item.setText("文件已删除"); self._color_status_item(item, "文件已删除")
            self.dl_table.setItem(r, 8, QTableWidgetItem(""))
            self._update_dl_row_buttons(r, aweme_id, "文件已删除", None)
        # 刷新所有相关卡片
        for card_dict in (self._cards,
                          *getattr(self, "_self_cards", {}).values(),
                          *getattr(self, "_disc_cards", {}).values()):
            card = card_dict.get(aweme_id)
            if card: card._refresh()
        self._save_dl_records()

    def _insert_dl_row(self, tid, title, status, local_path):
        """插入一行（恢复或新建）— 插到顶部保持倒序"""
        row = 0; self.dl_table.insertRow(row)
        self.dl_table.setItem(row, 0, QTableWidgetItem(title))
        author = _dl_records.get(tid, {}).get("author", "")
        auth_item = QTableWidgetItem(author)
        auth_item.setTextAlignment(Qt.AlignCenter)
        self.dl_table.setItem(row, 1, auth_item)
        pb = QProgressBar(); pb.setTextVisible(True)
        if status in ("已完成", "文件已删除"): pb.setRange(0,100); pb.setValue(100)
        self.dl_table.setCellWidget(row, 2, pb)
        stat_item = QTableWidgetItem(status)
        self._color_status_item(stat_item, status)
        self.dl_table.setItem(row, 3, stat_item)
        bw = QWidget(); bl = QHBoxLayout(bw)
        bl.setContentsMargins(2,2,2,2); bl.setSpacing(3)
        self.dl_table.setCellWidget(row, 4, bw)
        self._update_dl_row_buttons(row, tid, status, local_path)
        self.dl_table.setItem(row, 5, QTableWidgetItem("0 MB"))
        added_at = _dl_records.get(tid, {}).get("added_at", 0)
        if added_at:
            time_str = datetime.fromtimestamp(added_at).strftime("%Y-%m-%d %H:%M")
        else:
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.dl_table.setItem(row, 6, QTableWidgetItem(time_str))
        self.dl_table.setItem(row, 7, QTableWidgetItem(tid))
        self.dl_table.setItem(row, 8, QTableWidgetItem(local_path or ""))
        source = _dl_records.get(tid, {}).get("source", "")
        src_item = QTableWidgetItem(source)
        src_item.setTextAlignment(Qt.AlignCenter)
        self.dl_table.setItem(row, 9, src_item)

    def _update_dl_row_buttons(self, row, tid, status, local_path):
        """根据状态重建操作按钮区域。"""
        bw = self.dl_table.cellWidget(row, 4)
        if bw is None: return
        bl = bw.layout()
        while bl.count():
            item = bl.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        btn_style = ("QPushButton{font-size:10pt;padding:2px 6px;border-radius:3px;}"
                     "QPushButton:hover{background:#5a6678;} QPushButton:pressed{background:#3a4658;}")
        open_style = ("QPushButton{font-size:10pt;padding:2px 4px;border-radius:3px;}"
                      "QPushButton:hover{background:#5a6678;} QPushButton:pressed{background:#3a4658;}")
        file_exists = bool(local_path and os.path.exists(local_path))

        def mk(label, slot, w=None, style=btn_style, enabled=True):
            b = DlBtn(label, tid); b.setFixedHeight(28)
            if w: b.setFixedWidth(w)
            b.setStyleSheet(style); b.setEnabled(enabled)
            b.clicked.connect(slot); bl.addWidget(b)

        if status in ("等待中",):
            mk("开始", self._dl_start)
            mk("取消", self._dl_cancel)
        elif status == "下载中":
            mk("暂停", self._dl_pause)
            mk("取消", self._dl_cancel)
        elif status == "已暂停":
            mk("继续", self._dl_start)
            mk("取消", self._dl_cancel)
        elif status == "已完成":
            if file_exists:
                mk("📂", self._dl_open_file, w=34, style=open_style)
            else:
                mk("重新下载", self._dl_retry)
        elif status in ("下载失败", "已取消") or status.startswith("失败") or status.startswith("错误"):
            mk("重试", self._dl_retry)
            mk("取消", self._dl_cancel)
        elif status == "文件已删除":
            mk("重新下载", self._dl_retry)
        else:
            mk("📂", self._dl_open_file, w=34, style=open_style, enabled=file_exists)
            mk("取消", self._dl_cancel)

    @staticmethod
    def _color_status_item(item, status):
        colors = {"已完成": "#4caf50", "下载中": "#42a5f5",
                  "文件已删除": "#ff7043", "下载失败": "#ef5350",
                  "等待中": "#aaa", "已暂停": "#ffa726"}
        c = colors.get(status)
        if c: item.setForeground(QColor(c))

    def _find_row(self, tid):
        for r in range(self.dl_table.rowCount()):
            it = self.dl_table.item(r, 7)
            if it and it.text() == tid: return r
        return None

    def _dl_header_clicked(self, col):
        if col != 6: return  # 只响应"添加时间"列
        self._dl_time_desc = not self._dl_time_desc
        arrow = "▼" if self._dl_time_desc else "▲"
        self.dl_table.setHorizontalHeaderItem(6, QTableWidgetItem(f"添加时间 {arrow}"))
        # 收集所有行数据（tid + added_at）
        rows_data = []
        for r in range(self.dl_table.rowCount()):
            tid_item = self.dl_table.item(r, 7)
            time_item = self.dl_table.item(r, 6)
            if tid_item:
                tid = tid_item.text()
                ts = _dl_records.get(tid, {}).get("added_at", 0)
                rows_data.append((tid, ts))
        rows_data.sort(key=lambda x: x[1], reverse=self._dl_time_desc)
        # 按新顺序重建表格
        self.dl_table.setRowCount(0)
        for tid, _ in rows_data:
            rec = _dl_records.get(tid)
            if not rec: continue
            lp = rec.get("local_path", "")
            self._insert_dl_row(tid, rec.get("title",""), rec.get("status",""), lp)
            # 恢复进度条百分比
            r = 0
            pb = self.dl_table.cellWidget(r, 2)
            if pb and rec.get("status") in ("已完成", "文件已删除"):
                pb.setRange(0,100); pb.setValue(100)
            # 重新连接信号
            task = self.dl_mgr.tasks.get(tid)
            if task:
                try:
                    task.progress_updated.disconnect()
                    task.status_updated.disconnect()
                    task.download_finished.disconnect()
                except Exception:
                    pass
                task.progress_updated.connect(self._dl_prog)
                task.status_updated.connect(self._dl_stat)
                task.download_finished.connect(self._dl_fin)

    def _dl_start(self):
        b = self.sender()
        if isinstance(b, DlBtn):
            self.dl_mgr.start_task(b.tid)
            r = self._find_row(b.tid)
            if r is not None:
                self.dl_table.item(r,3).setText("下载中")
                self._update_dl_row_buttons(r, b.tid, "下载中", None)

    def _dl_pause(self):
        b = self.sender()
        if isinstance(b, DlBtn):
            self.dl_mgr.pause_task(b.tid)
            r = self._find_row(b.tid)
            if r is not None:
                self.dl_table.item(r,3).setText("已暂停")
                self._update_dl_row_buttons(r, b.tid, "已暂停", None)

    def _dl_cancel(self):
        b = self.sender()
        if isinstance(b, DlBtn):
            self.dl_mgr.cancel_task(b.tid)
            r = self._find_row(b.tid)
            if r is not None: self.dl_table.removeRow(r)
            _dl_records.pop(b.tid, None)
            self._save_dl_records()
            self._update_dl_stat_label()
            if b.tid in self._cards:
                self._cards[b.tid]._refresh()

    def _dl_retry(self):
        b = self.sender()
        if not isinstance(b, DlBtn): return
        tid = b.tid
        rec = _dl_records.get(tid, {})
        url = rec.get("url", "")
        title = rec.get("title", "")
        if not url: return
        r = self._find_row(tid)
        if r is not None:
            item = self.dl_table.item(r, 3)
            if item:
                item.setText("等待中"); self._color_status_item(item, "等待中")
            self._update_dl_row_buttons(r, tid, "等待中", None)
        _update_dl_record(tid, status="等待中")
        task = self.dl_mgr.tasks.get(tid)
        if task:
            task.cancel()
            self.dl_mgr.tasks.pop(tid, None)
        # 从旧队列位置移除，防止残留
        if tid in self.dl_mgr._queue:
            self.dl_mgr._queue.remove(tid)
        # 重新创建任务（复用 tid），插入队首立即参与调度
        new_task = DownloadTask(tid, url, title, self._save_dir)
        self.dl_mgr.tasks[tid] = new_task
        self.dl_mgr._queue.insert(0, tid)
        new_task.progress_updated.connect(self._dl_prog)
        new_task.status_updated.connect(self._dl_stat)
        new_task.download_finished.connect(self._dl_fin)
        self.dl_mgr.schedule()

    def _dl_prog(self, tid, cur, total):
        r = self._find_row(tid)
        if r is not None:
            pb = self.dl_table.cellWidget(r,2)
            if pb:
                if total > 0: pb.setRange(0,100); pb.setValue(int(cur*100/total))
                else: pb.setRange(0,0)
            mb = cur/1048576; tm = total/1048576
            self.dl_table.item(r,5).setText(f"{mb:.1f}/{tm:.1f} MB" if total else f"{mb:.1f} MB")

    def _dl_stat(self, tid, status):
        r = self._find_row(tid)
        if r is not None:
            item = self.dl_table.item(r, 3)
            if item:
                item.setText(status)
                self._color_status_item(item, status)
            lp = (self.dl_table.item(r, 8) or QTableWidgetItem("")).text()
            self._update_dl_row_buttons(r, tid, status, lp)
        _update_dl_record(tid, status=status)
        self._update_card_dl_status(tid, status)

    def _dl_fin(self, tid, ok, local_path):
        status = "已完成" if ok else "下载失败"
        r = self._find_row(tid)
        if r is not None:
            item = self.dl_table.item(r, 3)
            if item:
                item.setText(status)
                self._color_status_item(item, status)
            if ok:
                pb = self.dl_table.cellWidget(r, 2)
                if pb: pb.setRange(0,100); pb.setValue(100)
                self.dl_table.setItem(r, 8, QTableWidgetItem(local_path or ""))
            self._update_dl_row_buttons(r, tid, status, local_path if ok else None)
        _update_dl_record(tid, status=status, local_path=local_path or "")
        if ok and local_path:
            if tid in self._cards:
                self._cards[tid].mark_downloaded(local_path)
            for mode_dict in getattr(self, "_self_cards", {}).values():
                card = mode_dict.get(tid)
                if card: card.mark_downloaded(local_path)
            for mode_dict in getattr(self, "_disc_cards", {}).values():
                card = mode_dict.get(tid)
                if card: card.mark_downloaded(local_path)
            hist_card = getattr(self, "_parse_history_cards", {}).get(tid)
            if hist_card: hist_card.mark_downloaded(local_path)
            self._update_card_dl_status(tid, "已完成")
        else:
            if tid in self._cards:
                self._cards[tid]._refresh()
            for mode_dict in getattr(self, "_self_cards", {}).values():
                card = mode_dict.get(tid)
                if card: card._refresh()
            for mode_dict in getattr(self, "_disc_cards", {}).values():
                card = mode_dict.get(tid)
                if card: card._refresh()
            self._update_card_dl_status(tid, status)
        self._update_dl_stat_label()
        self.dl_mgr.on_task_finished(tid)  # 调度下一个等待中任务

    def _update_card_dl_status(self, aweme_id: str, status: str):
        """跨所有 card 字典更新 VideoCard 的下载状态显示。"""
        for card_dict in (self._cards,):
            card = card_dict.get(aweme_id)
            if card:
                card.update_dl_status(status)
                return
        for mode_dict in getattr(self, "_self_cards", {}).values():
            card = mode_dict.get(aweme_id)
            if card:
                card.update_dl_status(status); return
        for mode_dict in getattr(self, "_disc_cards", {}).values():
            card = mode_dict.get(aweme_id)
            if card:
                card.update_dl_status(status); return

    def _dl_start_all(self):
        for r in range(self.dl_table.rowCount()):
            it = self.dl_table.item(r,3)
            if it and it.text() in ("等待中","已暂停","下载失败"):
                self.dl_mgr.start_task(self.dl_table.item(r,7).text())

    def _dl_pause_all(self):
        for r in range(self.dl_table.rowCount()):
            it = self.dl_table.item(r,3)
            if it and it.text() == "下载中":
                self.dl_mgr.pause_task(self.dl_table.item(r,7).text())

    def _dl_clear(self):
        if QMessageBox.question(self,"确认","清空所有下载任务？",
                                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            for r in range(self.dl_table.rowCount()):
                it = self.dl_table.item(r,7)
                if it: self.dl_mgr.cancel_task(it.text())
            self.dl_table.setRowCount(0)
            _dl_records.clear()
            save_dl_records([])
            self._update_dl_stat_label()

    def _dl_batch_delete(self):
        rows = list({idx.row() for idx in self.dl_table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "未选择", "请先选择要删除的任务")
            return
        tids = []
        for r in rows:
            it = self.dl_table.item(r, 7)
            if it:
                tids.append(it.text())
        if not tids:
            return
        # 自定义确认对话框，带"同时删除本地文件"勾选项
        dlg = QDialog(self)
        dlg.setWindowTitle("确认删除")
        dlg_lay = QVBoxLayout(dlg)
        dlg_lay.addWidget(QLabel(f"确认从下载列表删除选中的 {len(tids)} 个任务？"))
        chk = QCheckBox("同时删除本地文件")
        dlg_lay.addWidget(chk)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("确认删除"); btn_ok.setDefault(True)
        btn_no = QPushButton("取消")
        btn_row.addStretch(); btn_row.addWidget(btn_ok); btn_row.addWidget(btn_no)
        dlg_lay.addLayout(btn_row)
        btn_ok.clicked.connect(dlg.accept); btn_no.clicked.connect(dlg.reject)
        if dlg.exec_() != QDialog.Accepted:
            return
        delete_files = chk.isChecked()
        for tid in tids:
            if delete_files:
                lp = _dl_records.get(tid, {}).get("local_path", "")
                if not lp:
                    lp = get_local_video_path(tid, self._save_dir) or ""
                if lp and os.path.exists(lp):
                    try: os.remove(lp)
                    except Exception: pass
            self.dl_mgr.cancel_task(tid)
            _dl_records.pop(tid, None)
            r = self._find_row(tid)
            if r is not None:
                self.dl_table.removeRow(r)
            self._cards.pop(tid, None)
        self._save_dl_records()
        self._update_dl_stat_label()

    def _dl_open_file(self):
        b = self.sender()
        if not isinstance(b, DlBtn): return
        r = self._find_row(b.tid)
        if r is None: return
        it = self.dl_table.item(r, 8)
        lp = it.text() if it else ""
        if lp and os.path.exists(lp):
            subprocess.Popen(["open", lp])
        else:
            QMessageBox.information(self, "提示", "文件不存在")

    def _filter_dl_table(self, text):
        text = text.strip().lower()
        for r in range(self.dl_table.rowCount()):
            it = self.dl_table.item(r, 0)
            hide = bool(text and it and text not in it.text().lower())
            self.dl_table.setRowHidden(r, hide)

    def _update_dl_stat_label(self):
        total    = self.dl_table.rowCount()
        done     = sum(1 for r in range(total)
                       if self.dl_table.item(r,3) and
                       self.dl_table.item(r,3).text() == "已完成")
        deleted  = sum(1 for r in range(total)
                       if self.dl_table.item(r,3) and
                       self.dl_table.item(r,3).text() == "文件已删除")
        parts = [f"共 {total} 条"]
        if done:    parts.append(f"已完成 {done}")
        if deleted: parts.append(f"文件已删除 {deleted}")
        self.dl_stat_lbl.setText("  |  ".join(parts))

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self,"选择下载目录",self._save_dir)
        if d:
            self._save_dir = d
            self.dl_mgr.set_save_path(d)
            self.dir_input.setText(d)

    def _open_dir(self):
        if os.path.isdir(self._save_dir): subprocess.Popen(["open",self._save_dir])
        else: QMessageBox.warning(self,"不存在",f"'{self._save_dir}' 不存在")

    # ══════════════════════════════════════════════════════════════════
    # Cookie / 登录
    # ══════════════════════════════════════════════════════════════════
    def open_cookie_dialog(self):
        dlg = QWidget(self, Qt.Window)
        dlg.setWindowTitle("设置 Cookie")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.resize(720, 360)
        scr = QApplication.desktop().screenGeometry()
        dlg.move((scr.width()-dlg.width())//2, (scr.height()-dlg.height())//2)
        lay = QVBoxLayout(dlg); lay.setSpacing(9); lay.setContentsMargins(18,14,18,14)
        steps = QLabel(
            "获取 Cookie 步骤：\n"
            "1. 系统浏览器打开 https://www.douyin.com 并登录（支持扫码）\n"
            "2. F12 → Network → 刷新页面 → 点任意 www.douyin.com 请求\n"
            "3. Headers → 找到「cookie:」这行 → 复制完整内容 → 粘贴到下方"
        )
        steps.setWordWrap(True); steps.setStyleSheet("color:#ccc;")
        lay.addWidget(steps)
        lay.addWidget(QLabel("Cookie 内容："))
        ce = QTextEdit()
        if getattr(self,"_cookie_str",""): ce.setPlainText(self._cookie_str)
        lay.addWidget(ce)
        br = QHBoxLayout(); br.addStretch()
        ok = QPushButton("确认登录")
        ok.setStyleSheet("background:#007acc;color:white;font-weight:bold;min-width:90px;padding:6px;")
        ok.clicked.connect(lambda: self._save_cookie_from_dlg(ce.toPlainText().strip(), dlg))
        br.addWidget(ok)
        cn = QPushButton("取消"); cn.clicked.connect(dlg.close); br.addWidget(cn)
        lay.addLayout(br); dlg.show()

    def _save_cookie_from_dlg(self, s, dlg):
        if not s: QMessageBox.warning(dlg,"提示","请粘贴 Cookie 内容"); return
        self._cookie_str = s
        save_cookie(s); dlg.close(); self._on_login_ok()

    def _load_cookie(self):
        c, ts = load_cookie()
        if c:
            self._cookie_str = c
            age = int((time.time()-ts)/3600) if ts else 0
            self._on_login_ok(f"（{age}小时前保存）" if ts else "")

    def _on_login_ok(self, age=""):
        txt = f"●{age}" if age else "●"
        self.my_login.setText(txt); self.my_login.setStyleSheet("color:#ffcc00;font-weight:bold;")
        self.my_ck_btn.setText("② 更新 Cookie")
        self.my_ck_btn.setStyleSheet("QPushButton{background:#388e3c;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;}"
                                     "QPushButton:hover{background:#43a047;} QPushButton:pressed{background:#2e7d32;}")
        # 异步获取登录账号昵称
        self._nick_age = age
        self._nick_thread = QThread()
        self._nick_worker = SelfNicknameWorker(self._cookie_str)
        self._nick_worker.moveToThread(self._nick_thread)
        self._nick_thread.started.connect(self._nick_worker.run)
        self._nick_worker.nickname_ready.connect(self._on_self_nickname)
        self._nick_worker.finished.connect(self._nick_thread.quit)
        self._nick_worker.finished.connect(self._on_nick_fetch_done)
        self._nick_thread.start()

    def _on_nick_fetch_done(self):
        if self.my_login.styleSheet().startswith("color:#ffcc00"):
            self.my_login.setStyleSheet("color:#66cc66;font-weight:bold;")

    def _on_self_nickname(self, nickname):
        age = getattr(self, "_nick_age", "")
        txt = f"● {nickname}{age}"
        self.my_login.setText(txt)
        self.my_login.setStyleSheet("color:#66cc66;font-weight:bold;")

    def _on_cookie_expired(self):
        for t in (self._fl_thread, self._fv_thread, self._afv_thread):
            if t and t.isRunning(): t.quit(); t.wait()
        self._fl_worker = self._fv_worker = self._afv_worker = None
        self.refresh_list_btn.setEnabled(True)
        self.resync_btn.setEnabled(True)
        self._glog("⚠️ Cookie 已过期")
        self.my_login.setText("● Cookie 已过期"); self.my_login.setStyleSheet("color:#ff9800;font-weight:bold;")
        self.my_ck_btn.setText("② 重新设置 Cookie")
        self.my_ck_btn.setStyleSheet("QPushButton{background:#e53935;color:white;font-weight:bold;padding:5px 10px;border-radius:4px;border:none;}"
                                     "QPushButton:hover{background:#ef5350;} QPushButton:pressed{background:#c62828;}")
        self._cookie_str = ""
        QMessageBox.warning(self,"Cookie 已过期",
            "Cookie 已失效，请重新登录后再同步。\n点击「② 重新设置 Cookie」。")
        self.open_cookie_dialog()

    def _on_verification_needed(self):
        """检测到人机验证时：若浏览器为无头模式，提示用户开启「显示浏览器」后恢复；
        若已显示浏览器，提示用户在浏览器中完成验证后点击继续。"""
        w = self._afv_worker
        is_headless = not self._app_settings.get("show_browser", False)
        self._glog("⚠️ 检测到人机验证（滑块/验证码），同步已暂停")
        if is_headless:
            ret = QMessageBox.warning(
                self, "检测到人机验证",
                "同步过程中触发了抖音人机验证（滑块/验证码）。\n\n"
                "当前浏览器运行在后台（无界面）模式，无法手动完成验证。\n\n"
                "建议：\n"
                "① 在「设置」中勾选「同步时显示浏览器窗口」\n"
                "② 取消本次同步，重新开始\n\n"
                "是否立即取消同步？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if ret == QMessageBox.Yes:
                if w: w.cancel()
            else:
                if w: w.resume()
        else:
            QMessageBox.information(
                self, "检测到人机验证",
                "同步过程中触发了抖音人机验证（滑块/验证码）。\n\n"
                "请在已打开的浏览器窗口中手动完成验证，\n"
                "完成后点击「确定」继续同步。"
            )
            if w: w.resume()



    @staticmethod
    def _extract_uid(text):
        if not text: return ""
        if "douyin.com/user/" in text:
            return text.split("/user/")[-1].split("?")[0].strip()
        return text.strip()

    def closeEvent(self, event):
        self._save_dl_records()
        # 停所有封面加载线程
        for card in list(self._cards.values()):
            card.stop_loader()
        for task in list(self.dl_mgr.tasks.values()): task.cleanup()
        for attr in ("_fl_thread", "_fv_thread", "_afv_thread", "_uv_thread"):
            t = getattr(self, attr, None)
            if t and t.isRunning(): t.quit(); t.wait()
        event.accept()


if __name__ == "__main__":
    app.setStyle("Fusion")
    _startup_settings = _load_app_settings()
    _startup_theme = _startup_settings.get("theme", "深色 (默认)")
    app.setStyleSheet(THEMES.get(_startup_theme, STYLE))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
