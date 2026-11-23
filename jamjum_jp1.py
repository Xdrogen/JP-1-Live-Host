# -*- coding: utf-8 -*-
"""
JAMJUM JP-1 // Custom Live Host  —  工业化版 (Industrial Build)

只适配 JP-1。中央舞台（布局 / QSS / 配色 / 辉光分级 / 方块 2.1 / 力度 0.10 /
真混响 / 走带 CC 22-24 / one-shot 自停 / 多端口去重 / 全量终端回显）逐字保留。

本版新增的只有「从我的机器走到别人的机器」那一层：
  · 音频回调零锁：GUI 只投命令 + 原子替换参数快照，回调不再与 GUI 抢锁
  · 共享模式音频（不再 WASAPI 独占抢 FL Studio）、设备/采样率/声道可配置
  · 端口显式生命周期（可关闭、可重扫），只认 JP-1，不猜通用 MIDI 设备
  · 工程文件 schema v2 + 迁移、素材收进工程目录、缺素材 UI 可见
  · 自动保存 / 异常退出恢复 / 最近工程
  · 有序退出 closeEvent、xrun 统计、状态栏、日志落盘、设置/关于/日志对话框
  · 默认全局英文，设置内仅 English / 中文两档，切换即时生效
  · 新增外围件（File/View 菜单、状态栏、tooltip、弹窗、设置内页）统一顶部功能栏青蓝；
    原有中央舞台配色逐字保留，包含底部走带按钮的暗红 #B03A3A
  · 高 DPI、第三方声明、菜单栏与状态栏（均为 QMainWindow 自带区域，不占中央布局）
  · 核心逻辑抽成 RtMixer / PresetManager / GlowManager，可无头单测（见 test_jp1_core.py）

打包由使用者自行完成；本文件不引入任何新的第三方依赖。
"""
import sys
import os
import time
import json
import math
import queue
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import mido
from scipy import signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout,
                               QPushButton, QFileDialog, QVBoxLayout, QHBoxLayout,
                               QStackedWidget, QLabel, QMessageBox, QSizePolicy,
                               QGraphicsDropShadowEffect, QFrame,
                               QDialog, QFormLayout, QComboBox, QCheckBox,
                               QSpinBox, QPlainTextEdit, QDialogButtonBox)
from PySide6.QtCore import Signal, QObject, Qt, QTimer, QRectF, QSettings
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QAction, QKeySequence

# ==========================================
# 🏷️ 应用标识 / 路径 / 版本
# ==========================================
APP_NAME       = "JAMJUM JP-1 // Custom Live Host"
APP_ORG        = "JP-1 Custom Live Host"
APP_VERSION    = "1.0.0"
SCHEMA_VERSION = 2
BUILD_TAG      = "industrial"

MIDI_BACKEND = 'mido.backends.pygame'
mido.set_backend(MIDI_BACKEND)


def _appdata_dir():
    base = os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME')
    root = Path(base) if base else (Path.home() / '.config')
    p = root / APP_ORG
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = Path.home() / ('.' + APP_ORG.replace(' ', '_'))
        p.mkdir(parents=True, exist_ok=True)
    return p


APP_DATA_DIR  = _appdata_dir()
LOG_PATH      = APP_DATA_DIR / 'jp1.log'
AUTOSAVE_PATH = APP_DATA_DIR / 'autosave.jp1.json'
SESSION_PATH  = APP_DATA_DIR / 'session.json'
RECENT_PATH   = APP_DATA_DIR / 'recent.json'
NOTICES_PATH  = APP_DATA_DIR / 'THIRD_PARTY_NOTICES.txt'

# ==========================================
# 🌐 语言：默认全局英文；设置内仅 English / 中文
# ==========================================
LANG_FILE = APP_DATA_DIR / 'language.json'
SUPPORTED_LANGS = ('en', 'zh')          # 只有两种，不做其他语言
LANG_LABELS = {'en': 'English', 'zh': '中文'}
_LANG = 'en'

# 纯静态用户可见串 → 英文（精确匹配优先）
FULL = {
    '运行日志': 'Run Log',
    '刷新': 'Refresh',
    '关闭': 'Close',
    '关于': 'About',
    'JP-1 键值表': 'JP-1 Key Map',
    '设置': 'Settings',
    '输出设备': 'Output device',
    '采样率 (Hz)': 'Sample rate (Hz)',
    '声道': 'Channels',
    '缓冲块 (samples)': 'Block size (samples)',
    '自动保存间隔': 'Autosave interval',
    ' 秒': ' s',
    '立体声 2': 'Stereo 2',
    '单声道 1': 'Mono 1',
    'WASAPI 独占（会抢走 FL Studio 等程序的音频设备）':
        'WASAPI exclusive (takes the audio device away from FL Studio etc.)',
    '启用自动保存 / 崩溃恢复': 'Enable autosave / crash recovery',
    '显示菜单栏': 'Show menu bar',
    '显示状态栏': 'Show status bar',
    '修改音频参数会重建音频流：已加载的素材会按新采样率自动重采样，混响/延迟尾巴清零。':
        'Changing audio parameters rebuilds the stream: loaded samples are resampled, reverb/delay tails are cleared.',
    '语言': 'Language',
    '起播量化：ON 时敲击排到下一小节，OFF 时立即播放（验证力度用 OFF）':
        'Quantize: ON queues hits to the next bar, OFF plays immediately (use OFF to test velocity)',
    '循环模式：再按一次同一 Pad 停止': 'Loop mode: press the same Pad again to stop',
    '单次模式：播完一遍自动停止，不绕回、不跨小节复活':
        'One-shot: plays once then stops, no wrap-around, no bar-line revival',
    '保存工程 (Ctrl+S)：素材会复制进工程目录，路径可迁移':
        'Save project (Ctrl+S): samples are copied into the project folder, paths stay portable',
    '打开工程 (Ctrl+O)：兼容旧版 v1 工程文件':
        'Open project (Ctrl+O): compatible with legacy v1 project files',
    '单击触发 · 双击 / 右键加载素材': 'Click to trigger · double-click / right-click to load a sample',
    '播放 / 从暂停恢复 (JP-1 CC 22)': 'Play / resume from pause (JP-1 CC 22)',
    '暂停 (JP-1 CC 23)': 'Pause (JP-1 CC 23)',
    '终止：清空播放与排队 (JP-1 CC 24 / 空格)':
        'Stop: clear playback and queue (JP-1 CC 24 / Space)',
    '文件(&F)': 'File(&F)',
    '新建工程': 'New Project',
    '打开工程…': 'Open Project…',
    '保存工程…': 'Save Project…',
    '最近工程': 'Recent Projects',
    '退出': 'Quit',
    '编辑(&E)': 'Edit(&E)',
    '设置…': 'Settings…',
    '重新扫描 JP-1 端口': 'Rescan JP-1 Ports',
    '视图(&V)': 'View(&V)',
    '运行日志…': 'Run Log…',
    'JP-1 键值表…': 'JP-1 Key Map…',
    '帮助(&H)': 'Help(&H)',
    '关于…': 'About…',
    '（暂无）': '(none)',
    '就绪': 'Ready',
    '未保存工程': 'Unsaved project',
    '音频流已按新参数重建。': 'Audio stream rebuilt with the new parameters.',
    '错误': 'Error',
    '恢复工程': 'Recover Project',
    '检测到上次异常退出，且存在自动保存的工程。\n是否恢复？':
        'The last session exited abnormally and an autosaved project exists.\nRecover it?',
    '已恢复': 'Recovered',
    '自动保存的工程已恢复，请用「保存工程」另存为正式文件。':
        'The autosaved project has been restored. Use "Save Project" to store it as a file.',
    '当前改动尚未保存，确定清空？': 'Unsaved changes will be lost. Clear anyway?',
    '部分素材缺失': 'Some samples are missing',
    '请把素材放回工程目录的 samples 文件夹后重新打开。':
        'Put the samples back into the project samples folder, then reopen the project.',
    '未保存的改动': 'Unsaved Changes',
    '当前工程有未保存的改动，且自动保存未开启。仍要退出？':
        'The project has unsaved changes and autosave is disabled. Quit anyway?',
    '已有序退出': 'Shutdown complete',
    'Success': 'Success',
    'Error': 'Error',
    'Project Loaded!': 'Project Loaded!',
    'Save Project': 'Save Project',
    'Load Project': 'Load Project',
    'Load Sample': 'Load Sample',
}

# f-string / 拼接串里的中文片段 → 英文（按长度降序替换）
PHRASES = {
    '⚠️ 音频流按所选参数打开失败': '⚠️ Failed to open stream with selected params',
    '回退到共享 / 默认设备 / blocksize 2048': 'falling back to shared / default device / blocksize 2048',
    '⚠️ 音频回调异常（本块静音）': '⚠️ Audio callback error (block muted)',
    '⚠️ 自动保存失败: ': '⚠️ Autosave failed: ',
    '⚠️ 素材复制失败 ': '⚠️ Sample copy failed ',
    '⚠️ 素材加载失败 Pad ': '⚠️ Sample load failed Pad ',
    '⚠️ 素材加载失败：': '⚠️ Sample load failed: ',
    '⚠️ 音频引擎启动失败': '⚠️ Audio engine failed to start',
    '⚠️ 退出清理异常: ': '⚠️ Shutdown cleanup error: ',
    '⚠️ 音频命令执行失败 ': '⚠️ Audio command failed ',
    '⚠️ MIDI 后端不可用: ': '⚠️ MIDI backend unavailable: ',
    '⚠️ 未检测到 JP-1 端口。请检查 USB / 蓝牙连接，本程序只适配 JP-1，不会连接其他设备':
        '⚠️ No JP-1 port found. Check USB / Bluetooth; this app supports JP-1 only and will not connect to other devices',
    '⚠️ 端口 [': '⚠️ Port [',
    '] 打开失败: ': '] open failed: ',
    '  （其他端口不受影响）': '  (other ports unaffected)',
    '] 监听异常: ': '] listen error: ',
    '🔌 MIDI 端口已全部关闭': '🔌 All MIDI ports closed',
    '🔌 音频流已有序关闭': '🔌 Audio stream closed cleanly',
    '🔊 音频流: ': '🔊 Audio stream: ',
    '📡 将监听 ': '📡 Listening to ',
    ' 个 JP-1 端口  |  后端: ': ' JP-1 port(s)  |  backend: ',
    '🎹 系统可见 MIDI 输入端口 (': '🎹 Visible MIDI input ports (',
    '🔎 上部 6 个功能格：按一下看 [未映射 CC] / [未映射 note] / [Program Change] 打印':
        '🔎 Top 6 function keys: press one and watch for [Unmapped CC] / [Unmapped note] / [Program Change]',
    '   已登记走带: 22=▶播放 23=■暂停 24=⚪终止 | 19=< 20=蓝牙 21=> (预留)':
        '   Registered transport: 22=▶Play 23=■Pause 24=⚪Stop | 19=< 20=Bluetooth 21=> (reserved)',
    '💪 力度不是 CC：轻敲/重敲 pad 看 [力度·敲击] velocity=... → gain=...':
        '💪 Velocity is not CC: hit softly / hard and watch [Velocity · Strike] velocity=... → gain=...',
    '   鼠标点 Pad 不传 velocity → 满音量 | 不想要就把 VELOCITY_TO_GAIN / PRESSURE_TO_GAIN 改 False':
        '   Mouse clicks send no velocity → full level | set VELOCITY_TO_GAIN / PRESSURE_TO_GAIN to False to disable',
    '⚠️ QUANTIZE 默认 ON：敲 pad 会排到下一小节才响。想立刻听到轻重差别，先把 QUANTIZE 点成 OFF':
        '⚠️ QUANTIZE defaults to ON: hits are queued to the next bar. Set QUANTIZE to OFF to hear velocity immediately',
    '🏛️ REVERB 为 4 阻尼梳状 + 2 全通扩散的真混响；DELAY 独立不受影响':
        '🏛️ REVERB is a true reverb (4 damped combs + 2 allpass diffusers); DELAY stays independent',
    '✨ 辉光已分级：激活/播放 紧亮、排队 微光、Idle 绝对平':
        '✨ Glow is tiered: active/playing tight & bright, queued faint, idle perfectly flat',
    '✅ 已连接端口: ': '✅ Connected port: ',
    '📥 素材已加载 Pad ': '📥 Sample loaded Pad ',
    '👋 已有序退出': '👋 Shutdown complete',
    '📁 数据目录: ': '📁 Data folder: ',
    '📄 日志: ': '📄 Log: ',
    '音频流重建失败：': 'Audio stream rebuild failed: ',
    '\n\n已保留原设置，请重启后再试。': '\n\nPrevious settings kept, please restart and retry.',
    '保存失败：': 'Save failed: ',
    '素材加载失败：': 'Sample load failed: ',
    'Project Saved!\n\n素材已收进：': 'Project Saved!\n\nSamples copied into: ',
    '\n共 ': '\nTotal: ',
    ' 个文件，工程内使用相对路径，可整体搬走。':
        ' file(s); relative paths inside the project, the whole folder can be moved.',
    '共 ': 'Total: ',
    '个文件，工程内使用相对路径，可整体搬走。':
        ' file(s); relative paths inside the project, the whole folder can be moved.',
    '未保存工程': 'Unsaved project',
    '以下素材未找到，对应 Pad 保持空白：':
        'The following samples were not found; their Pads stay empty:',
    '请把素材放回工程目录的 samples 文件夹后重新打开。':
        'Put the samples back into the project samples folder, then reopen the project.',
    '\n  …另有 ': '\n  …and ',
    ' 个': ' more',
    '日志读取失败: ': 'Failed to read log: ',
    '    ↳ 若这是上部功能格：在 FUNCTION_CCS 加  ':
        '    ↳ If this is a top function key: add to FUNCTION_CCS  ',
    '    ↳ 若这是上部功能格：在 TRANSPORT_NOTES 加  ':
        '    ↳ If this is a top function key: add to TRANSPORT_NOTES  ',
    '    ↳ 若这是上部功能格：记下 ': '    ↳ If this is a top function key: note down ',
    '，单独加分支处理': ', handle it in a dedicated branch',
    '    ↳ 若是 MMC：看 data 第 4 个字节（命令码），加进 MMC_ACTIONS':
        '    ↳ If MMC: check the 4th data byte (command code) and add it to MMC_ACTIONS',
    "（或 'pause' / 'stop'）": " (or 'pause' / 'stop')",
    "'动作名'": "'action_name'",
    '💪 [力度·复压]': '💪 [Pressure · Poly]',
    '💪 [力度·通道压]': '💪 [Pressure · Channel]',
    '💪 [力度·敲击]': '💪 [Velocity · Strike]',
    '🎛 [弯音]': '🎛 [Pitch Bend]',
    '♻️ [跨端口重复已去重]': '♻️ [Duplicate across ports]',
    '  ← 已挡住，不会二次触发': '  ← blocked, no second trigger',
    ' 已静音不刷屏；其余消息全部打印': ' muted to avoid flooding; all other messages are printed',
    '🎛 [抬键]': '🎛 [Key Up]',
    '🎛 [预留键]': '🎛 [Reserved Key]',
    '  ← 暂未绑定功能': '  ← not bound yet',
    '🎛 [走带]': '🎛 [Transport]',
    '  (80ms 去抖忽略)': '  (80ms debounce ignored)',
    '🔘 [功能格]': '🔘 [Function Key]',
    '🎹 [抬键]': '🎹 [Key Up]',
    '🔎 [功能格? 未映射 note]': '🔎 [Function key? Unmapped note]',
    '🎚 [旋钮]': '🎚 [Knob]',
    '🔎 [功能格? 未映射 CC]': '🔎 [Function key? Unmapped CC]',
    '🔎 [功能格? Program Change]': '🔎 [Function key? Program Change]',
    '🔎 [功能格? SysEx]': '🔎 [Function key? SysEx]',
    '🔎 [其他 MIDI]': '🔎 [Other MIDI]',
    '控制口 (走带 CC)': 'Control port (transport CC)',
    '辅助口': 'Aux port',
    'Pad 口': 'Pad port',
    'JP-1 端口': 'JP-1 port',
    '系统默认输出设备': 'System default output device',
    'WASAPI 独占': 'WASAPI exclusive',
    '独占': 'Exclusive',
    '共享': 'Shared',
    '回退默认参数': 'falling back to defaults',
    'JP-1 专用映射（本程序不做其他品牌适配）':
        'JP-1 dedicated mapping (no other-brand support)',
    '（预留，未绑定）': '(reserved, unbound)',
    '旋钮区': 'Knobs',
    'Pad 区（Note On）': 'Pads (Note On)',
    '力度：Note On 自带 velocity(0–127)，不是 CC；触后为 0xA0/0xD0。':
        'Velocity: carried by Note On (0–127), not CC; aftertouch is 0xA0/0xD0.',
    '上部 6 个功能格若发出消息，终端会打印 [未映射 CC] 并给出填表提示。':
        'If a top function key emits a message, the terminal prints [Unmapped CC] with a fill-in hint.',
    '  Pad 口 (note)  :': '  Pad port (note) :',
    '  旋钮 (CC)     :': '  Knobs (CC)     :',
    '  走带 (CC)     :': '  Transport (CC) :',
    '  预留 (CC)     :': '  Reserved (CC)  :',
    '▶播放': '▶Play',
    '■暂停': '■Pause',
    '⚪终止': '⚪Stop',
    '蓝牙': 'Bluetooth',
    '版本 ': 'Version ',
    '  ·  数据目录 ': '  ·  Data folder ',
    '\n【JP-1 专用映射】\n': '\n[JP-1 DEDICATED MAPPING]\n',
    '【力度】敲击 velocity 控制该次触发音量 (0.10~1.0)；按住加压实时改正在播放的 pad。':
        '[VELOCITY] Strike velocity sets that trigger\'s level (0.10~1.0); after-press changes the playing pad live.',
    '【提示】QUANTIZE=ON 时敲击排到下一小节起播；验证力度请先把 QUANTIZE 点成 OFF。':
        '[TIP] With QUANTIZE=ON hits start at the next bar; set QUANTIZE to OFF to test velocity.',
    '\n【第三方组件】\n': '\n[THIRD-PARTY COMPONENTS]\n',
    '\n完整声明文件：': '\nFull notice file: ',
    '  (CC ': '  (CC ',
    ' — 拖动 / 滚轮调节': ' — drag / scroll to adjust',
    '切换到 ': 'Switch to ',
    '（硬件敲击对应 Bank 会自动跳转）': ' (hardware hits auto-switch to the matching Bank)',
    '个': '',
    '播放': 'Play',
    '暂停': 'Pause',
    '终止': 'Stop',
    '预留': 'Reserved',
    '端口': 'port',
    '打印': 'printout',
}
_PHRASE_ITEMS = sorted(PHRASES.items(), key=lambda kv: -len(kv[0]))


def load_language():
    """默认 en；只有用户在设置里切换过才读回其他值。"""
    global _LANG
    try:
        v = json.loads(LANG_FILE.read_text(encoding='utf-8')).get('language', 'en')
        _LANG = v if v in SUPPORTED_LANGS else 'en'
    except Exception:
        _LANG = 'en'
    return _LANG


def language():
    return _LANG


def set_language(code):
    """切换 + 持久化；返回是否真的变化。仅接受 SUPPORTED_LANGS。"""
    global _LANG
    code = code if code in SUPPORTED_LANGS else 'en'
    if code == _LANG:
        return False
    _LANG = code
    try:
        LANG_FILE.write_text(json.dumps({'language': code}, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass
    try:
        NOTICES_PATH.write_text(notices_text(), encoding='utf-8')
    except Exception:
        pass
    return True


def L(text):
    """用户可见文本按当前语言渲染；默认英文。zh 原样返回，en 做精确/短语替换。"""
    if not isinstance(text, str) or _LANG == 'zh':
        return text
    exact = FULL.get(text)
    if exact is not None:
        return exact
    for cn, en in _PHRASE_ITEMS:
        if cn in text:
            text = text.replace(cn, en)
    return text


load_language()

# ==========================================
# 🌐 顶部功能栏专用双语（默认英文；中文模式 ONLY 这四组及其下属控件变中文）
# ==========================================
# 与 L() 完全隔离：既不往 FULL / PHRASES 里塞短词，也不改既有 158 处文本。
# 刻意保持英文：BANK 1/2/3、Pad 1–16、8 个旋钮名、产品名——都是硬件丝印 /
# 行业专名，硬翻反而别扭；菜单 / 设置页 / 弹窗 / 终端日志沿用既有 L() 双语。
# 想让某一条也中文化：只改下面这张表，别处不用碰。
TOP_TEXT = {
    'QUANTIZE':   ('QUANTIZE',   '量化'),
    'ON':         ('ON',         '开'),
    'OFF':        ('OFF',        '关'),
    'PLAY_MODE':  ('PLAY MODE',  '播放模式'),
    'LOOP':       ('LOOP',       '循环'),
    'ONE_SHOT':   ('ONE-SHOT',   '单次'),
    'MASTER_BPM': ('MASTER BPM', '主速度'),
    'PROJECT':    ('PROJECT',    '工程'),
    'SAVE':       ('SAVE',       '保存'),
    'LOAD':       ('LOAD',       '加载'),
}


def T(key):
    """顶部功能栏文本：en=英文（首次启动默认），zh=中文。未知 key 原样返回。"""
    pair = TOP_TEXT.get(key)
    if pair is None:
        return key
    return pair[1] if language() == 'zh' else pair[0]


THIRD_PARTY_NOTICES_ZH = """JAMJUM JP-1 // Custom Live Host — 第三方组件声明

随本程序分发的第三方 Python 包及其许可（请以各项目官方 LICENSE 原文为准）：
  PySide6 / Qt for Python   LGPL-3.0 / GPL-3.0 双授权（Qt Company）
  numpy                    BSD-3-Clause
  scipy                    BSD-3-Clause
  sounddevice              MIT
  soundfile                BSD-3-Clause（底层 libsndfile 为 LGPL）
  mido                     MIT
  pygame                   LGPL-2.1-or-later

分发二进制时，请随安装包附上上述组件的官方 LICENSE 全文与对应源码获取说明；
若采用 GPL 授权的 Qt，请一并遵守 GPL 的对应义务。本文件由程序启动时写出，便于审计。
"""

THIRD_PARTY_NOTICES_EN = """JAMJUM JP-1 // Custom Live Host — Third-Party Notices

Third-party Python packages distributed with this program (refer to each
project's official LICENSE for the authoritative text):
  PySide6 / Qt for Python   LGPL-3.0 / GPL-3.0 dual license (Qt Company)
  numpy                    BSD-3-Clause
  scipy                    BSD-3-Clause
  sounddevice              MIT
  soundfile                BSD-3-Clause (libsndfile is LGPL)
  mido                     MIT
  pygame                   LGPL-2.1-or-later

When distributing a binary, include the full official LICENSE texts and the
corresponding source-availability notices. If Qt is used under GPL, comply
with the respective GPL obligations. This file is written at startup for audit.
"""


def notices_text():
    return THIRD_PARTY_NOTICES_EN if _LANG == 'en' else THIRD_PARTY_NOTICES_ZH


class RotatingTee:
    """把 sys.stdout / sys.stderr 同时写到终端与轮转日志，线程安全。
    零侵入：原有所有 print 一行不改，全部自动落盘。"""
    def __init__(self, stream, path, max_bytes=2_000_000, backups=2):
        self.stream = stream
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()
        self.encoding = 'utf-8'
        try:
            self._f = open(self.path, 'a', encoding='utf-8', buffering=1)
        except Exception:
            self._f = None

    def _rotate(self):
        if not self._f or self.path.stat().st_size < self.max_bytes if self.path.exists() else False:
            return
        try:
            self._f.close()
            for i in range(self.backups - 1, 0, -1):
                src = self.path.with_suffix(f'.log.{i}')
                dst = self.path.with_suffix(f'.log.{i + 1}')
                if src.exists():
                    shutil.move(str(src), str(dst))
            shutil.move(str(self.path), str(self.path.with_suffix('.log.1')))
            self._f = open(self.path, 'a', encoding='utf-8', buffering=1)
        except Exception:
            self._f = None

    def write(self, s):
        with self._lock:
            try:
                self.stream.write(s)
                self.stream.flush()
            except Exception:
                pass
            if self._f:
                try:
                    self._f.write(s)
                    self._f.flush()
                except Exception:
                    pass
        self._rotate()
        return len(s)

    def writelines(self, lines):
        for ln in lines:
            self.write(ln)

    def flush(self):
        try: self.stream.flush()
        except Exception: pass
        if self._f:
            try: self._f.flush()
            except Exception: pass

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self.stream, name)


def setup_appdata():
    """创建数据目录、写第三方声明、安装 stdout/stderr tee。"""
    try:
        NOTICES_PATH.write_text(notices_text(), encoding='utf-8')
    except Exception:
        pass
    tee = RotatingTee(sys.__stdout__, LOG_PATH)
    sys.stdout = tee
    sys.stderr = RotatingTee(sys.__stderr__, LOG_PATH)
    return tee


# ==========================================
# 🎛️ JP-1 专用 profile（唯一映射来源，不做通用设备适配）
# ==========================================
# 已实测（control_change 的 control 号，不是 note）：
#   22 = ▶ 播放   23 = ■ 暂停   24 = ⚪ 终止
#   19 = <        20 = 蓝牙     21 = >      （预留，暂不绑定功能）
JP1_PROFILE = {
    'device_tokens': ('JP-1',),
    'transport_cc': {22: 'play', 23: 'pause', 24: 'stop', 19: None, 20: None, 21: None},
    'cc_labels':    {19: '<', 20: '蓝牙', 21: '>', 22: '▶ 播放', 23: '■ 暂停', 24: '⚪ 终止'},
    'function_cc':  {},     # 上部 6 功能格探测表，按到再填
    'knob_cc':      {46: 'DIV', 47: 'SWING', 48: 'GATE', 49: 'TEMPO',
                     50: 'DELAY', 51: 'VOLUME', 52: 'FILTER', 53: 'REVERB'},
    'pad_notes':    {'bank1': (68, 83), 'bank2': (36, 51), 'bank3': (52, 67)},
    'port_roles':   {'MIDIIN2': '控制口 (走带 CC)', 'MIDIIN3': '辅助口', 'JP-1 PAD': 'Pad 口'},
}

# 由 profile 派生旧别名，保持下游代码逐字可用
TRANSPORT_CCS = JP1_PROFILE['transport_cc']
CC_LABELS     = JP1_PROFILE['cc_labels']
FUNCTION_CCS  = JP1_PROFILE['function_cc']
CC_NAMES      = JP1_PROFILE['knob_cc']
JP1_PORT_TOKENS = JP1_PROFILE['device_tokens']

PAD_NOTE_RANGE = range(36, 84)   # 36–83 = 3 Bank × 16 Pad
CC_KNOB_RANGE  = range(46, 54)   # 46–53 = 8 个旋钮

MMC_ACTIONS = {0x02: 'play', 0x03: 'play', 0x09: 'pause', 0x01: 'stop', 0x06: 'stop'}
REALTIME_ACTIONS = {'start': 'play', 'continue': 'play', 'stop': 'stop'}
TRANSPORT_NOTES = {}

VERBOSE_RAW        = True
DETECT_MODE        = True
SILENT_MIDI_TYPES    = {'clock', 'active_sensing'}
THROTTLED_MIDI_TYPES = {'polytouch', 'aftertouch', 'pitchwheel'}
THROTTLE_PRINT       = 0.12
DEDUP_WINDOW         = 0.04
ACTION_DEBOUNCE      = 0.08

SHOW_VELOCITY_PERCENT = True
VELOCITY_MONITOR      = True

# ==========================================
# 💪 力度 → 播放增益
# ==========================================
VELOCITY_TO_GAIN     = True
PRESSURE_TO_GAIN     = True
VELOCITY_MIN_GAIN    = 0.10
EXPRESSION_EMIT_THROTTLE = 0.03


def vel_gain(value):
    """velocity / pressure(0-127) → 增益。None = 鼠标点击 = 满音量。"""
    if not VELOCITY_TO_GAIN or value is None:
        return 1.0
    v = max(0, min(127, int(value)))
    return VELOCITY_MIN_GAIN + (1.0 - VELOCITY_MIN_GAIN) * (v / 127.0)


def note_to_pad(note):
    """三段非顺排映射 → (ui_page_idx, global_pad_index)，越界返回 None。"""
    if 68 <= note <= 83: return (0, note - 68)
    if 36 <= note <= 51: return (1, 16 + (note - 36))
    if 52 <= note <= 67: return (2, 32 + (note - 52))
    return None


def pad_desc(note):
    hit = note_to_pad(note)
    if not hit: return "?"
    return f"Bank{hit[0]+1} / Pad {hit[1] % 16 + 1}"


def raw_hex(msg):
    try:
        return msg.hex()
    except Exception:
        return str(msg)


def pct(v):
    return f" ({round(v / 127 * 100)}%)" if SHOW_VELOCITY_PERCENT else ""


def port_role(name):
    """只用于日志标签，不参与消息过滤（避免漏收）。"""
    u = name.upper()
    for token, role in JP1_PROFILE['port_roles'].items():
        if token.upper() in u:
            return L(role)
    return L('JP-1 端口')


def resolve_transport(msg):
    t = msg.type
    if t == 'sysex':
        d = msg.data
        if len(d) >= 4 and d[0] == 0x7F and d[2] == 0x06:
            return (MMC_ACTIONS.get(d[3]), True)
        return (None, False)
    if t in REALTIME_ACTIONS:
        return (REALTIME_ACTIONS[t], True)
    if t == 'control_change':
        if msg.control in TRANSPORT_CCS:
            return (None if msg.value == 0 else TRANSPORT_CCS[msg.control], True)
        if msg.control in FUNCTION_CCS:
            return (None if msg.value == 0 else FUNCTION_CCS[msg.control], True)
        return (None, False)
    if t == 'note_on' and msg.note in TRANSPORT_NOTES:
        return (TRANSPORT_NOTES[msg.note] if msg.velocity > 0 else None, True)
    return (None, False)


def print_unmapped_hint(msg):
    if msg.type == 'control_change':
        print(L(f"        ↳ 若这是上部功能格：在 FUNCTION_CCS 加  {msg.control}: '动作名'"))
    elif msg.type == 'note_on':
        print(L(f"        ↳ 若这是上部功能格：在 TRANSPORT_NOTES 加  {msg.note}: 'play'（或 'pause' / 'stop'）"))
    elif msg.type == 'program_change':
        print(L(f"        ↳ 若这是上部功能格：记下 program={msg.program}，单独加分支处理"))
    elif msg.type == 'sysex':
        print(L("        ↳ 若是 MMC：看 data 第 4 个字节（命令码），加进 MMC_ACTIONS"))

# ==========================================
# 🎨 终极配色方案（逐字未动）
# ==========================================
BG_COLOR = "#14141A"
BORDER_COLOR = "#2A2A35"
TEXT_GRAY = "#88888A"
TEXT_WHITE = "#E0E0E0"

THEME_COLOR = "#00E5FF"
THEME_GLOW = QColor(0, 229, 255, 120)

BANK1_COLOR = "#1E88FF"
BANK2_COLOR = "#FF6B00"
BANK3_COLOR = "#00FF66"

GATE_PINK = "#FF007F"
GATE_ORANGE = "#FF6B00"

# ==========================================
# 🔤 UI 字体（本轮授权改动：只换「英文」，中文维持默认）
# ==========================================
# JAMJUM logo 是粗圆润的泡泡字（圆头、无锐角、字怀饱满、U 圆底），
# 气质偏「友好、软、像乐器」；Segoe UI 太中性冷硬，全大写小字显得死板。
# 但 11px 粗体标签 / 18px BPM 数字不能直接用 logo 那种 display 字体：
# 小字会糊、字宽会撑破 setFixedSize(70/85/180/230)、还要额外内置字体文件。
# 所以取「圆润 humanist」方向：Trebuchet MS —— Windows 全版本自带、零新增依赖、
# 字怀开放、末端略带俏皮斜切，粗体全大写比 Segoe UI 有性格而小字依旧锐利。
# 中文由字体栈按字符自动回落到 Microsoft YaHei（用户指定「中文用默认字体」），
# 不需要按语言切换字体，一个栈同时满足两种语言。
# 想更圆更软：把 UI_FONT_EN 改成 'Candara'；想真正 1:1 贴 logo 需内置
# Fredoka / Baloo 2（SIL OFL），代价是打包体积 + 一条第三方声明，留到下一轮。
UI_FONT_EN    = "Trebuchet MS"
UI_FONT_STACK = f"'{UI_FONT_EN}', 'Microsoft YaHei', 'Segoe UI', sans-serif"

GLOBAL_QSS = f"""
QMainWindow {{ background-color: {BG_COLOR}; }}
QWidget {{ font-family: {UI_FONT_STACK}; color: {TEXT_WHITE}; }}
QLabel {{ color: {TEXT_GRAY}; font-size: 11px; font-weight: bold; }}

QPushButton {{ 
    background-color: transparent; 
    color: {TEXT_GRAY}; 
    border: 1px solid {BORDER_COLOR}; 
    border-radius: 4px; 
    padding: 6px 12px; 
    font-weight: bold;
    font-size: 12px;
}}
QPushButton:hover {{ 
    border: 1px solid {THEME_COLOR}; 
    color: {THEME_COLOR}; 
}}
QPushButton[active="true"] {{ 
    background-color: #001A22; 
    border: 1px solid {THEME_COLOR}; 
    color: {THEME_COLOR}; 
}}

QLabel#BpmDisplay {{
    background-color: {BG_COLOR}; 
    color: {THEME_COLOR}; 
    border: 1px solid {BORDER_COLOR}; 
    border-radius: 4px; 
    font-size: 18px; 
    font-weight: bold; 
    qproperty-alignment: AlignCenter;
}}

QPushButton#CtrlBtn {{ 
    background-color: #1A1010; 
    border: 1px solid #3A1C1C; 
    border-radius: 6px;
    padding: 0px;
}}
QPushButton#CtrlBtn:hover {{ 
    border: 1px solid #B03A3A; 
    background-color: #2A1515; 
}}
QPushButton#CtrlBtn:pressed {{ 
    background-color: #4A1C1C; 
    border: 1px solid #B03A3A;
}}
"""

PAD_IDLE = f"""
    QPushButton {{ background-color: {BG_COLOR}; color: #555; border: 1px solid {BORDER_COLOR}; border-radius: 8px; font-size: 14px; }}
    QPushButton:hover {{ border: 1px solid #88888A; color: #88888A; }}
"""
PAD_PLAY_1 = f"""
    QPushButton {{ background-color: #001A33; color: {BANK1_COLOR}; border: 1px solid {BANK1_COLOR}; border-radius: 8px; font-weight: bold; }}
    QPushButton:hover {{ background-color: #002A4D; border: 1px solid {BANK1_COLOR}; }}
"""
PAD_PLAY_2 = f"""
    QPushButton {{ background-color: #221100; color: {BANK2_COLOR}; border: 1px solid {BANK2_COLOR}; border-radius: 8px; font-weight: bold; }}
    QPushButton:hover {{ background-color: #332200; border: 1px solid {BANK2_COLOR}; }}
"""
PAD_PLAY_3 = f"""
    QPushButton {{ background-color: #001A0D; color: {BANK3_COLOR}; border: 1px solid {BANK3_COLOR}; border-radius: 8px; font-weight: bold; }}
    QPushButton:hover {{ background-color: #002A11; border: 1px solid {BANK3_COLOR}; }}
"""
PAD_QUEUED = f"""
    QPushButton {{ background-color: #1A1A00; color: #FFD700; border: 1px dashed #FFD700; border-radius: 8px; font-weight: bold; }}
    QPushButton:hover {{ border: 1px solid #FFD700; }}
"""

# ==========================================
# 🪟 工业化版新增「外围件」统一青蓝（原有中央舞台一行都不碰）
#     覆盖范围：File/Edit/View/Help 菜单、状态栏、tooltip、设置/关于/日志/键值表
#     以及这些动作触发的弹窗。色相全部沿用顶部功能栏 THEME_COLOR。
# ==========================================
DIALOG_QSS = f"""
QDialog {{ background-color: {BG_COLOR}; }}
QDialog QWidget {{ font-family: {UI_FONT_STACK}; color: {TEXT_WHITE}; }}
QDialog QLabel {{ color: {TEXT_GRAY}; font-size: 11px; font-weight: bold; }}
QLabel#DialogNote {{ color: {THEME_COLOR}; }}
QPlainTextEdit {{ background-color: {BG_COLOR}; color: {TEXT_WHITE};
                  border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                  selection-background-color: #004A55; font-size: 11px; }}
QComboBox, QSpinBox {{ background-color: #1A1A22; color: {TEXT_WHITE};
                       border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                       padding: 4px 8px; font-weight: bold; }}
QComboBox:hover, QSpinBox:hover {{ border: 1px solid {THEME_COLOR}; color: {THEME_COLOR}; }}
QComboBox::drop-down {{ border: 0px; }}
QComboBox QAbstractItemView {{ background-color: #1A1A22; color: {TEXT_WHITE};
                              selection-background-color: #004A55; }}
QCheckBox {{ color: {TEXT_WHITE}; spacing: 8px; }}
QCheckBox:hover {{ color: {THEME_COLOR}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER_COLOR};
                        border-radius: 3px; background-color: {BG_COLOR}; }}
QCheckBox::indicator:checked {{ background-color: {THEME_COLOR}; border: 1px solid {THEME_COLOR}; }}
QPushButton {{ background-color: transparent; color: {TEXT_GRAY};
               border: 1px solid {BORDER_COLOR}; border-radius: 4px;
               padding: 6px 12px; font-weight: bold; }}
QPushButton:hover {{ border: 1px solid {THEME_COLOR}; color: {THEME_COLOR}; }}
QDialogButtonBox QPushButton {{ min-width: 84px; }}
"""

# 应用级壳层 QSS：只作用于 QMainWindow 新增周边控件，不进入中央舞台
CHROME_QSS = f"""
QMenuBar, QMenu, QStatusBar, QToolTip, QMessageBox {{ font-family: {UI_FONT_STACK}; }}
QMenuBar {{ background-color: {BG_COLOR}; color: {TEXT_GRAY};
            border-bottom: 1px solid {BORDER_COLOR}; padding: 2px; font-weight: bold; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; }}
QMenuBar::item:selected {{ background-color: #001A22; color: {THEME_COLOR};
                           border: 1px solid {THEME_COLOR}; border-radius: 3px; }}
QMenuBar::item:pressed {{ background-color: #002A33; color: {THEME_COLOR}; }}

QMenu {{ background-color: #1A1A22; color: {TEXT_WHITE};
         border: 1px solid {BORDER_COLOR}; border-radius: 4px; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 18px; border-radius: 3px; }}
QMenu::item:selected {{ background-color: #001A22; color: {THEME_COLOR};
                        border: 1px solid {THEME_COLOR}; }}
QMenu::item:disabled {{ color: #555; }}
QMenu::separator {{ height: 1px; background: {BORDER_COLOR}; margin: 4px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; }}

QStatusBar {{ background-color: {BG_COLOR}; color: {TEXT_GRAY};
              border-top: 1px solid {BORDER_COLOR}; }}
QStatusBar::item {{ border: 0px; }}
QStatusBar QLabel {{ color: {THEME_COLOR}; }}

QToolTip {{ background-color: #1A1A22; color: {THEME_COLOR};
            border: 1px solid {THEME_COLOR}; border-radius: 4px;
            padding: 4px 8px; font-size: 11px; }}

QMessageBox {{ background-color: {BG_COLOR}; }}
QMessageBox QLabel {{ color: {TEXT_WHITE}; font-size: 12px; font-weight: normal; }}
QMessageBox QPushButton {{ background-color: transparent; color: {TEXT_GRAY};
                           border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                           padding: 5px 14px; font-weight: bold; min-width: 70px; }}
QMessageBox QPushButton:hover {{ border: 1px solid {THEME_COLOR}; color: {THEME_COLOR}; }}
QMessageBox QPushButton:default {{ border: 1px solid {THEME_COLOR}; color: {THEME_COLOR};
                                    background-color: #001A22; }}
"""


def show_message(parent, kind, title, text, buttons=None):
    """外围弹窗统一入口：去掉 Qt 内置红色错误图标 / 黄色警告图标，改青蓝面板。
    kind 仅作语义标记（info / error / warn / ask），不驱动配色；
    返回值与 QMessageBox 静态方法一致，可直接与 QMessageBox.Yes 比较。
    """
    if buttons is None:
        buttons = QMessageBox.Ok
    mb = QMessageBox(parent)
    mb.setIcon(QMessageBox.NoIcon)
    mb.setWindowTitle(title)
    mb.setText(text)
    mb.setStandardButtons(buttons)
    mb.setStyleSheet(CHROME_QSS)
    return mb.exec()

# ==========================================
# ✨ 辉光分级（观感逐字不动，仅抽出可测试的管理器）
# ==========================================
#   soft    排队提示   微光，几乎平
#   active  激活态     紧、亮、明确（QUANTIZE / LOOP / ONE-SHOT / BANK）
#   playing 播放 Pad   稍散一点，因为面积大
# Qt 一个控件只能挂一层 effect，且 setGraphicsEffect 会删除旧 effect，
# 所以「状态不变直接 return」是必须的：既防每 30ms 重建，也避免误用已删除对象。
GLOW_SPECS = {
    'soft':    (10,  95),
    'active':  (14, 205),
    'playing': (16, 215),
}

# ==========================================
# 📐 布局微调（本轮只动这两处；QSS / 配色 / 辉光 / 字号逐字不动）
# ==========================================
# ① 顶部四组标签 → 其下方控件之间的垂直间距（原 5px，适当放宽）
TOP_LABEL_GAP = 9
# ② Pad 方阵垂直分布：原 QGridLayout 把多余高度均摊在首尾，方阵整体居中，
#    BANK 栏与第一行 Pad 之间因此挂了一块松留白。现把多余高度全给底部空行，
#    只留 PAD_GRID_TOP_MARGIN 这一点余量 → 方阵整体上移但不贴死。
#    想再往上挪：把 MARGIN 调到 0；想退回原样：删掉 setRowStretch 并把 MARGIN 设 0。
PAD_GRID_TOP_MARGIN = 6


class GlowManager:
    """全 UI 唯一辉光入口。依赖注入以便无头单测；builds 计数仅供验证。"""
    def __init__(self, color_cls, effect_cls, theme_color, specs=None):
        self.color_cls = color_cls
        self.effect_cls = effect_cls
        self.theme_color = theme_color
        self.specs = specs or GLOW_SPECS
        self._state = {}
        self.builds = 0

    def apply(self, widget, level, color_key=None):
        key = id(widget)
        state = (level, color_key)
        if self._state.get(key) == state:
            return False
        if level is None:
            widget.setGraphicsEffect(None)
            self._state[key] = state
            return True
        blur, alpha = self.specs[level]
        c = self.color_cls(color_key if color_key else self.theme_color)
        c.setAlpha(alpha)
        eff = self.effect_cls(widget)
        eff.setBlurRadius(blur)
        eff.setColor(c)
        eff.setOffset(0, 0)
        widget.setGraphicsEffect(eff)
        self._state[key] = state
        self.builds += 1
        return True

    def reset(self, widget):
        self.apply(widget, None)


# ==========================================
# 📦 工程文件：schema v2 / 迁移 / 素材收纳 / 自动保存 / 最近工程
# ==========================================
class PresetManager:
    """纯 Python，无 Qt 依赖，可直接无头单测。"""
    def __init__(self, appdata=None):
        self.appdata = Path(appdata) if appdata else APP_DATA_DIR
        self.autosave_path = self.appdata / 'autosave.jp1.json'
        self.session_path = self.appdata / 'session.json'
        self.recent_path = self.appdata / 'recent.json'
        try:
            self.appdata.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def empty_data():
        return {'bpm': 120, 'quantize': True, 'play_mode': 'loop',
                'dials': [127, 0, 0, 64, 0, 100, 64, 0], 'pads': {}}

    def normalize(self, raw):
        """兼容旧版 v1（顶层 bpm/quantize/play_mode/dials/pads 绝对路径）。"""
        if not isinstance(raw, dict):
            return dict(self.empty_data())
        data = raw.get('data', raw)
        out = dict(self.empty_data())
        try:
            out['bpm'] = int(data.get('bpm', 120))
        except Exception:
            out['bpm'] = 120
        out['quantize'] = bool(data.get('quantize', True))
        mode = data.get('play_mode', 'loop')
        out['play_mode'] = mode if mode in ('loop', 'oneshot') else 'loop'
        dials = data.get('dials', out['dials'])
        out['dials'] = [max(0, min(127, int(v))) for v in list(dials)[:8]] + out['dials'][len(dials):]
        pads = data.get('pads', {}) or {}
        out['pads'] = {str(k): str(v) for k, v in pads.items()}
        return out

    def _sample_dir(self, project_path):
        return Path(project_path).parent / (Path(project_path).stem + '_samples')

    def save(self, project_path, data):
        """把素材复制进工程目录，写相对路径；原子替换，避免半截文件。"""
        p = Path(project_path)
        sdir = self._sample_dir(p)
        sdir.mkdir(parents=True, exist_ok=True)
        rel_pads = {}
        copied = []
        for pad_str, src in data.get('pads', {}).items():
            src_p = Path(src)
            if not src_p.is_absolute():
                src_p = Path(project_path).parent / src_p
            if not src_p.exists():
                continue
            ext = src_p.suffix.lower() or '.wav'
            dst_name = f"pad_{int(pad_str):02d}{ext}" if str(pad_str).isdigit() else f"pad_{pad_str}{ext}"
            dst = sdir / dst_name
            try:
                if src_p.resolve() != dst.resolve():
                    shutil.copy2(str(src_p), str(dst))
                rel_pads[str(pad_str)] = f"{sdir.name}/{dst_name}"
                copied.append(dst_name)
            except Exception as e:
                print(L(f"⚠️ 素材复制失败 {src_p}: {e}"))
        payload = {
            'schema': SCHEMA_VERSION, 'app': APP_NAME, 'version': APP_VERSION,
            'build': BUILD_TAG, 'saved_at': datetime.now().isoformat(timespec='seconds'),
            'data': {**data, 'pads': rel_pads},
        }
        tmp = p.with_suffix(p.suffix + '.tmp')
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(p)
        return {'ok': True, 'samples': copied, 'sample_dir': str(sdir)}

    def load(self, project_path):
        """→ (data, missing_paths)。相对路径按工程文件所在目录解析。"""
        p = Path(project_path)
        raw = json.loads(p.read_text(encoding='utf-8'))
        data = self.normalize(raw)
        missing = []
        resolved = {}
        for pad_str, rel in data['pads'].items():
            rel_p = Path(rel)
            abs_p = rel_p if rel_p.is_absolute() else (p.parent / rel_p)
            if abs_p.exists():
                resolved[pad_str] = str(abs_p)
                data['pads'][pad_str] = str(rel_p)
            else:
                missing.append((pad_str, str(abs_p)))
        return data, missing

    # ---- 自动保存 / 崩溃恢复 ----
    def write_autosave(self, data):
        payload = {'schema': SCHEMA_VERSION, 'saved_at': datetime.now().isoformat(timespec='seconds'),
                   'data': data}
        tmp = self.autosave_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(self.autosave_path)

    def read_autosave(self):
        if not self.autosave_path.exists():
            return None
        try:
            return self.normalize(json.loads(self.autosave_path.read_text(encoding='utf-8')))
        except Exception:
            return None

    def mark_session_start(self):
        self.session_path.write_text(json.dumps({'clean_exit': False, 'started_at':
            datetime.now().isoformat(timespec='seconds')}), encoding='utf-8')

    def mark_clean_exit(self):
        self.session_path.write_text(json.dumps({'clean_exit': True, 'exited_at':
            datetime.now().isoformat(timespec='seconds')}), encoding='utf-8')
        try:
            self.autosave_path.unlink()
        except Exception:
            pass

    def crashed_last_time(self):
        try:
            return not bool(json.loads(self.session_path.read_text(encoding='utf-8')).get('clean_exit', True))
        except Exception:
            return False

    # ---- 最近工程 ----
    def recent(self):
        try:
            v = json.loads(self.recent_path.read_text(encoding='utf-8'))
            return [x for x in v if Path(x).exists()][:5]
        except Exception:
            return []

    def add_recent(self, path):
        items = [str(path)] + [x for x in self.recent() if x != str(path)]
        self.recent_path.write_text(json.dumps(items[:5], ensure_ascii=False, indent=2), encoding='utf-8')


def resolve_pad_paths(data, base_dir, fallback_dir=None):
    """把工程内的相对素材路径解析成绝对路径。纯函数，便于无头单测。
    → (resolved: {pad_index: abs_path}, missing: [(pad_str, tried_path)])
    """
    resolved, missing = {}, []
    base = Path(base_dir) if base_dir else APP_DATA_DIR
    for pad_str, rel in (data.get('pads') or {}).items():
        try:
            idx = int(pad_str)
        except Exception:
            continue
        if not (0 <= idx < 48):
            continue
        p = Path(str(rel))
        cand = [p] if p.is_absolute() else [base / p]
        if fallback_dir and not p.is_absolute():
            cand.append(Path(fallback_dir) / p)
        hit = next((c for c in cand if c.exists()), None)
        if hit is not None:
            resolved[idx] = str(hit)
        else:
            missing.append((pad_str, str(cand[-1])))
    return resolved, missing


# ==========================================
# 🎛️ 自定义的底部控制按钮 (平衡放大版) —— 逐字未动
# ==========================================
class TransportButton(QPushButton):
    def __init__(self, icon_type, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.setObjectName("CtrlBtn")
        self.setFixedHeight(55)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        icon_color = QColor("#B03A3A")

        painter.setBrush(icon_color)

        cx = self.width() / 2
        cy = self.height() / 2
        size = 12.5

        if self.icon_type == 'play':
            painter.setPen(QPen(icon_color, 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath()
            path.moveTo(cx - size*0.45, cy - size*0.95)
            path.lineTo(cx + size*0.95, cy)
            path.lineTo(cx - size*0.45, cy + size*0.95)
            path.closeSubpath()
            painter.drawPath(path)

        elif self.icon_type == 'pause':
            painter.setPen(Qt.NoPen)
            w = 8
            h = 28
            r = 2.0

            x1 = cx - size*0.6 - w/2
            x2 = cx + size*0.6 - w/2
            y = cy - h/2

            painter.drawRoundedRect(QRectF(x1, y, w, h), r, r)
            painter.drawRoundedRect(QRectF(x2, y, w, h), r, r)

        elif self.icon_type == 'stop':
            painter.setPen(Qt.NoPen)
            rect = QRectF(cx - size*1.05, cy - size*1.05, size*2.1, size*2.1)
            painter.drawRoundedRect(rect, 4.0, 4.0)


# ==========================================
# 🎛️ 支持双击加载的自定义 Pad 按钮 —— 逐字未动
# ==========================================
class PadButton(QPushButton):
    def __init__(self, text, pad_index, main_window):
        super().__init__(text)
        self.pad_index = pad_index
        self.main_window = main_window

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.main_window.load_file_to_pad(self.pad_index, self)


# ==========================================
# ⚙️ Vital 风格旋钮 (等分节点) —— 逐字未动
# ==========================================
class VitalKnob(QWidget):
    valueChanged = Signal(int)

    def __init__(self, name, color=THEME_COLOR, is_gate=False, is_tempo=False, parent=None):
        super().__init__(parent)
        self.name = name
        self.color = color
        self.is_gate = is_gate
        self.is_tempo = is_tempo
        self._value = 0
        self._min = 0
        self._max = 127
        self.setFixedSize(55, 80)
        self.setCursor(Qt.SizeVerCursor)
        self._dragging = False
        self._last_y = 0

    def setValue(self, val):
        val = max(self._min, min(self._max, int(val)))
        if val != self._value:
            self._value = val
            self.update()
            self.valueChanged.emit(self._value)

    def value(self):
        return self._value

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_y = event.pos().y()

    def mouseMoveEvent(self, event):
        if self._dragging:
            dy = self._last_y - event.pos().y()
            self.setValue(self._value + dy)
            self._last_y = event.pos().y()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120
        self.setValue(self._value + delta)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.is_gate:
            if self._value in (0, 42, 85, 127):
                draw_color = QColor(GATE_PINK)
            else:
                draw_color = QColor(GATE_ORANGE)

            if self._value == 0: val_str = "OFF"
            elif self._value <= 42: val_str = "1/2"
            elif self._value <= 85: val_str = "1/4"
            else: val_str = "1/8"
        elif self.is_tempo:
            draw_color = QColor(self.color)
            bpm = int(40 + (self._value / 127.0) * 160)
            val_str = f"{bpm}"
        else:
            draw_color = QColor(self.color)
            val_str = f"{int((self._value / self._max) * 100)}%"

        painter.setPen(QColor(TEXT_GRAY))
        painter.setFont(QFont(UI_FONT_EN, 8, QFont.Bold))
        painter.drawText(QRectF(0, 45, 55, 12), Qt.AlignCenter, self.name)

        painter.setPen(QColor("#AAAAAA"))
        painter.setFont(QFont(UI_FONT_EN, 8, QFont.Bold))
        painter.drawText(QRectF(0, 58, 55, 12), Qt.AlignCenter, val_str)

        size = 34
        rect = QRectF((55 - size)/2, (42 - size)/2, size, size)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(BG_COLOR))
        painter.drawEllipse(rect)

        painter.setPen(QPen(QColor(BORDER_COLOR), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        angle_span = 270 * 16
        start_angle = 225 * 16
        val_ratio = (self._value - self._min) / (self._max - self._min)

        painter.setPen(QPen(QColor("#222222"), 2.5))
        painter.drawArc(rect, start_angle, -angle_span)

        if val_ratio > 0:
            glow_pen = QPen(QColor(draw_color), 6)
            glow_pen.setCapStyle(Qt.RoundCap)
            glow_color = QColor(draw_color)
            glow_color.setAlpha(80)
            glow_pen.setColor(glow_color)
            painter.setPen(glow_pen)
            painter.drawArc(rect, start_angle, int(-angle_span * val_ratio))

            arc_pen = QPen(QColor(draw_color), 2.5)
            arc_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(rect, start_angle, int(-angle_span * val_ratio))

        center_x, center_y = 27.5, 21
        angle_rad = np.radians(225 - (270 * val_ratio))
        pointer_length = 10

        px = center_x + pointer_length * np.cos(angle_rad)
        py = center_y - pointer_length * np.sin(angle_rad)

        painter.setPen(QPen(QColor(TEXT_WHITE), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center_x, center_y, int(px), int(py))


# ==========================================
# 🏛️ 真·混响 (Schroeder / Moorer) —— 逐字未动
# ==========================================
class ReverbNetwork:
    COMB_MS    = (29.7, 37.1, 41.1, 43.7)
    ALLPASS_MS = (5.3, 8.1)
    COMB_G     = 0.80
    ALLPASS_G  = 0.50
    DAMP       = 0.25
    WET_SCALE  = 0.28

    def __init__(self, sample_rate, channels):
        self.sr, self.ch = sample_rate, channels
        self.combs = []
        for ms in self.COMB_MS:
            M = max(64, int(sample_rate * ms / 1000.0))
            self.combs.append(dict(
                M=M,
                buf=np.zeros((M, channels), dtype=np.float32),
                wp=0,
                zi=np.zeros((1, channels), dtype=np.float32),
            ))
        self.allpasses = []
        for ms in self.ALLPASS_MS:
            M = max(16, int(sample_rate * ms / 1000.0))
            self.allpasses.append(dict(
                M=M,
                ib=np.zeros((M, channels), dtype=np.float32),
                ob=np.zeros((M, channels), dtype=np.float32),
                wp=0,
            ))
        self._b = np.array([1.0 - self.DAMP], dtype=np.float32)
        self._a = np.array([1.0, -self.DAMP], dtype=np.float32)

    def _comb(self, s, x):
        """y[n] = x[n] + g * LP(y[n-M])；环形缓冲长度 == M，故段内可整段向量化。"""
        M, buf, frames, g = s['M'], s['buf'], x.shape[0], self.COMB_G
        y = np.empty_like(x)
        off = 0
        while off < frames:
            k = min(M, frames - off)
            idx = (s['wp'] + np.arange(k)) % M
            hist = buf[idx].copy()
            hist, s['zi'] = signal.lfilter(self._b, self._a, hist, axis=0, zi=s['zi'])
            yb = x[off:off+k] + g * hist
            buf[idx] = yb
            y[off:off+k] = yb
            s['wp'] = (s['wp'] + k) % M
            off += k
        return y

    def _allpass(self, s, x):
        """y[n] = -g*x[n] + x[n-M] + g*y[n-M]；同样按 M 切段。"""
        M, ib, ob, frames, g = s['M'], s['ib'], s['ob'], x.shape[0], self.ALLPASS_G
        y = np.empty_like(x)
        off = 0
        while off < frames:
            k = min(M, frames - off)
            idx = (s['wp'] + np.arange(k)) % M
            xd = ib[idx].copy()
            yd = ob[idx].copy()
            yb = -g * x[off:off+k] + xd + g * yd
            ib[idx] = x[off:off+k]
            ob[idx] = yb
            y[off:off+k] = yb
            s['wp'] = (s['wp'] + k) % M
            off += k
        return y

    def process(self, dry, mix):
        if dry.shape[0] == 0:
            return dry
        wet = np.zeros_like(dry)
        for c in self.combs:
            wet += self._comb(c, dry)
        wet *= 0.25
        for a in self.allpasses:
            wet = self._allpass(a, wet)
        wet *= self.WET_SCALE
        return dry + wet * mix


# ==========================================
# 🎚️ 实时混音器：只在音频回调线程里被触碰（无锁核心，可无头单测）
# ==========================================
class RtMixer:
    """所有可变播放状态都装在这里，由命令队列驱动；GUI 线程永不直接访问。

    published_state 每次状态变化时整体替换为「新 dict」再原子赋值，
    GUI 读到的永远是一份一致快照，不需要任何锁。
    """
    def __init__(self, sample_rate=44100, channels=2):
        self.sr = sample_rate
        self.ch = channels
        self.pads = {}
        self.global_samples = 0
        self.play_mode = 'loop'
        self.quantize_enabled = True
        self.is_paused = False
        self.bpm = 120.0
        self.samples_per_beat = max(1, int((60.0 / self.bpm) * self.sr))
        self.samples_per_bar = self.samples_per_beat * 4

        self.delay_buffer = np.zeros((int(self.sr * 2), self.ch), dtype=np.float32)
        self.delay_write_pos = 0
        self.temp_delay_out = np.zeros((8192, self.ch), dtype=np.float32)
        self.reverb = ReverbNetwork(self.sr, self.ch)
        self.z_low = [None, None]
        self.z_high = [None, None]

        self._dirty = True
        self.published_state = {}

    # ---------- 命令应用（回调线程） ----------
    def apply_cmd(self, cmd):
        op = cmd[0]
        if op == 'load':
            idx, audio = cmd[1], cmd[2]
            self.pads[idx] = {'audio': audio, 'playing': False, 'queued': False,
                              'pos': 0, 'mode': self.play_mode, 'gain': 1.0}
            self._dirty = True
        elif op == 'clear_pads':
            self.pads.clear()
            self._dirty = True
        elif op == 'trigger':
            idx, gain = cmd[1], cmd[2]
            pad = self.pads.get(idx)
            if pad is None:
                return
            pad['gain'] = gain
            self.is_paused = False
            if self.play_mode == 'oneshot':
                pad['mode'] = 'oneshot'
                pad['queued'] = False
                pad['playing'] = True
                pad['pos'] = 0
            else:
                pad['mode'] = 'loop'
                if pad['playing'] or pad['queued']:
                    pad['playing'] = False; pad['queued'] = False; pad['pos'] = 0
                else:
                    if self.quantize_enabled:
                        pad['queued'] = True
                    else:
                        pad['playing'] = True; pad['pos'] = 0
            self._dirty = True
        elif op == 'gain':
            idx, g, only_if_playing = cmd[1], float(cmd[2]), cmd[3]
            pad = self.pads.get(idx)
            if pad is not None and (not only_if_playing or pad['playing']):
                pad['gain'] = g
        elif op == 'stop_all':
            self.is_paused = False
            self.global_samples = 0
            for pad in self.pads.values():
                pad['playing'] = False; pad['queued'] = False
                pad['pos'] = 0; pad['mode'] = self.play_mode; pad['gain'] = 1.0
            # 混响状态刻意不清零：尾巴自然衰减（效果尾音 ≠ 没停）
            self._dirty = True
        elif op == 'pause':
            self.is_paused = bool(cmd[1])
        elif op == 'mode':
            self.play_mode = cmd[1]
            self._dirty = True
        elif op == 'quantize':
            self.quantize_enabled = bool(cmd[1])
        elif op == 'bpm':
            self.bpm = float(cmd[1])
            self.samples_per_beat = max(1, int((60.0 / self.bpm) * self.sr))
            self.samples_per_bar = self.samples_per_beat * 4
        elif op == 'noop':
            pass

    def _publish(self):
        if not self._dirty:
            return
        self.published_state = {i: (bool(p['queued']), bool(p['playing']))
                                for i, p in self.pads.items()}
        self._dirty = False

    # ---------- 效果链（回调线程） ----------
    def apply_effects(self, mix, fx):
        gate_depth = fx['gate_depth']
        if gate_depth > 0.01:
            step_len = max(1, int(fx['samples_per_beat'] * fx['gate_rate']))
            current_pos = self.global_samples + np.arange(len(mix))
            phases = (current_pos % step_len) / step_len
            gate_val = (phases < 0.5).astype(np.float32)
            mask = 1.0 - gate_depth + gate_depth * gate_val
            # 声道数可配置（1 或 2），不能写死 [:, 0] / [:, 1]
            for i in range(self.ch):
                mix[:, i] *= mask

        if fx['swing_amount'] > 0.01:
            beat_len = max(1, fx['samples_per_beat'])
            current_pos = self.global_samples + np.arange(len(mix))
            phase = (current_pos % (beat_len // 2)) / (beat_len // 2)
            mod_depth = fx['swing_amount'] * 0.5
            mod = 1.0 - (np.sin(phase * np.pi) * mod_depth)
            for i in range(self.ch):
                mix[:, i] *= mod

        b_filt, a_filt = fx['b_filt'], fx['a_filt']
        if fx['filter_mode'] != 'bypass' and b_filt is not None:
            for i in range(self.ch):
                if fx['filter_mode'] == 'lowpass':
                    if self.z_low[i] is None: self.z_low[i] = signal.lfilter_zi(b_filt, a_filt) * 0
                    mix[:, i], self.z_low[i] = signal.lfilter(b_filt, a_filt, mix[:, i], zi=self.z_low[i])
                else:
                    if self.z_high[i] is None: self.z_high[i] = signal.lfilter_zi(b_filt, a_filt) * 0
                    mix[:, i], self.z_high[i] = signal.lfilter(b_filt, a_filt, mix[:, i], zi=self.z_high[i])
        else:
            self.z_low = [None, None]; self.z_high = [None, None]

        # DELAY：独立效果，逻辑逐字未动
        if fx['delay_mix'] > 0.01:
            delay_samples = int(fx['delay_time'] * self.sr)
            if 0 < delay_samples < len(self.delay_buffer):
                read_pos = (self.delay_write_pos - delay_samples) % len(self.delay_buffer)
                remain_read = len(self.delay_buffer) - read_pos
                out_len = min(len(mix), len(self.temp_delay_out))

                if remain_read >= out_len:
                    self.temp_delay_out[:out_len] = self.delay_buffer[read_pos:read_pos + out_len]
                else:
                    self.temp_delay_out[:remain_read] = self.delay_buffer[read_pos:]
                    self.temp_delay_out[remain_read:out_len] = self.delay_buffer[:out_len - remain_read]

                mix[:out_len] += self.temp_delay_out[:out_len] * fx['delay_mix']

                write_pos = self.delay_write_pos
                remain_write = len(self.delay_buffer) - write_pos
                if remain_write >= out_len:
                    self.delay_buffer[write_pos:write_pos + out_len] = mix[:out_len] * 0.6
                else:
                    self.delay_buffer[write_pos:] = mix[:remain_write] * 0.6
                    self.delay_buffer[:out_len - remain_write] = mix[remain_write:out_len] * 0.6
                self.delay_write_pos = (self.delay_write_pos + out_len) % len(self.delay_buffer)

        mix = self.reverb.process(mix, fx['reverb_mix'])
        mix *= fx['master_volume']
        return mix

    # ---------- 单块渲染 ----------
    def render(self, frames, fx):
        out = np.zeros((frames, self.ch), dtype=np.float32)
        if self.is_paused:
            self._publish()
            return out

        current_bar = self.global_samples // self.samples_per_bar
        next_bar_sample = (current_bar + 1) * self.samples_per_bar
        if self.global_samples + frames >= next_bar_sample:
            for pad in self.pads.values():
                if pad.get('queued', False):
                    if pad.get('mode', 'loop') == 'loop':
                        pad['playing'] = True
                        pad['queued'] = False
                        pad['pos'] = 0
                        self._dirty = True
                    else:
                        pad['queued'] = False
                        self._dirty = True
        self.global_samples += frames

        for pad in self.pads.values():
            audio = pad.get('audio')
            if not pad.get('playing', False) or audio is None or len(audio) == 0:
                continue

            gain = pad.get('gain', 1.0)
            total = len(audio)
            pos = pad['pos']
            if pos < 0 or pos >= total:
                pos = 0
                pad['pos'] = 0

            remaining = total - pos
            take = min(frames, remaining)
            out[:take] += audio[pos:pos + take] * gain

            if remaining > frames:
                pad['pos'] = pos + frames
            else:
                if pad.get('mode', 'loop') == 'oneshot':
                    pad['playing'] = False
                    pad['queued'] = False
                    pad['pos'] = 0
                    self._dirty = True
                else:
                    n_wrap = frames - remaining
                    written = 0
                    while written < n_wrap:
                        chunk = min(total, n_wrap - written)
                        out[remaining + written:remaining + written + chunk] += audio[:chunk] * gain
                        written += chunk
                    pad['pos'] = (pos + frames) % total

        self.global_samples -= frames
        out = self.apply_effects(out, fx)
        self.global_samples += frames
        self._publish()
        return out


# ==========================================
# 🎵 音频引擎：GUI 侧只投命令 + 原子替换参数快照；回调零锁
# ==========================================
class AppSignals(QObject):
    midi_received = Signal(int, int)
    cc_received = Signal(int, int)
    transport_received = Signal(str)
    function_received = Signal(int, int)
    expression_received = Signal(str, int, int)


def default_fx(sample_rate, channels):
    return {
        'sample_rate': sample_rate, 'channels': channels,
        'master_volume': 0.8,
        'delay_time': 0.5, 'delay_mix': 0.0, 'reverb_mix': 0.0,
        'gate_rate': 0.5, 'gate_depth': 0.0,
        'swing_amount': 0.0, 'samples_per_beat': max(1, int(60.0 / 120.0 * sample_rate)),
        'filter_mode': 'bypass', 'b_filt': None, 'a_filt': None,
    }


def query_audio_defaults():
    """跟随默认输出设备，而不是把 44100/2ch 写死。失败则安全回退。"""
    sr, ch = 44100, 2
    try:
        dev_idx = sd.default.device[1]
        info = sd.query_devices(dev_idx)
        sr = int(info.get('default_samplerate') or sr)
        ch = min(2, int(info.get('max_output_channels') or ch))
    except Exception:
        pass
    return max(8000, sr), max(1, ch)


def list_output_devices():
    out = [(-1, L('系统默认输出设备'))]
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get('max_output_channels', 0) > 0:
                out.append((i, f"{i}: {d.get('name', '?')}"))
    except Exception:
        pass
    return out


class AudioEngine:
    """实时回调内没有任何 lock / malloc 阻塞点：
       · 参数：GUI 构造新 dict 后一次原子引用赋值 self._fx
       · 播放状态：GUI 投 SimpleQueue 命令，回调开头 drain 后只碰 RtMixer
       · GUI 读状态：读 mixer 原子发布的 published_state 快照
    """
    def __init__(self, sample_rate=None, channels=None, blocksize=1024,
                 device=None, exclusive=False, autostart=True):
        if sample_rate is None or channels is None:
            dsr, dch = query_audio_defaults()
            sample_rate = sample_rate or dsr
            channels = channels or dch
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.device = device
        self.exclusive = bool(exclusive)   # 默认 False：不抢 FL Studio 的音频设备

        self.play_mode = 'loop'            # GUI 侧镜像（回调不读）
        self.quantize_enabled = True
        self.bpm = 120.0
        self.on_bpm_changed = None

        self._fx = default_fx(self.sample_rate, self.channels)
        self._cmd = queue.SimpleQueue()
        self.mixer = RtMixer(self.sample_rate, self.channels)
        self._pad_meta = {}                # GUI 侧元数据：{idx: {'file_path': abs}}
        self._meta_lock = threading.Lock() # 只保护 GUI 侧元数据，回调永不接触
        self._xrun = 0
        self._stream = None
        self._closed = False
        if autostart:
            self._open_stream()

    # ---------- 流生命周期 ----------
    def _open_stream(self):
        kwargs = dict(samplerate=self.sample_rate, channels=self.channels,
                      callback=self.audio_callback, blocksize=self.blocksize,
                      dtype='float32')
        if self.device is not None and int(self.device) >= 0:
            kwargs['device'] = int(self.device)
        try:
            if self.exclusive:
                kwargs['extra_settings'] = sd.WasapiSettings(exclusive=True)
            stream = sd.OutputStream(**kwargs)
        except Exception as e:
            print(L(f"⚠️ 音频流按所选参数打开失败 ({e})，回退到共享 / 默认设备 / blocksize 2048"))
            kwargs.pop('extra_settings', None)
            kwargs.pop('device', None)
            kwargs['blocksize'] = 2048
            stream = sd.OutputStream(**kwargs)
            self.blocksize = 2048
            self.exclusive = False
        self._stream = stream
        stream.start()
        mode = L('WASAPI 独占') if self.exclusive else L('共享')
        print(L(f"🔊 音频流: {self.sample_rate}Hz / {self.channels}ch / bs={self.blocksize} / {mode}"))

    def _stop_stream(self):
        s = self._stream
        self._stream = None
        if s is None:
            return
        try: s.stop()
        except Exception: pass
        try: s.close()
        except Exception: pass

    def rebuild_stream(self, sample_rate, channels, blocksize, device, exclusive):
        """GUI 线程调用；先停流（stop 会等回调结束），再换参数/重采样素材，最后重启。"""
        self._stop_stream()
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.device = device
        self.exclusive = bool(exclusive)
        self.mixer = RtMixer(self.sample_rate, self.channels)
        fx = dict(self._fx)
        fx['sample_rate'] = self.sample_rate
        fx['channels'] = self.channels
        fx['samples_per_beat'] = max(1, int((60.0 / self.bpm) * self.sample_rate))
        self._fx = fx
        self._cmd.put(('mode', self.play_mode))
        self._cmd.put(('quantize', self.quantize_enabled))
        self._cmd.put(('bpm', self.bpm))
        with self._meta_lock:
            metas = dict(self._pad_meta)
        for idx, meta in metas.items():
            self.load_audio(idx, meta['file_path'], quiet=True)
        self._open_stream()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._stop_stream()
        print(L("🔌 音频流已有序关闭"))

    # ---------- GUI → RT 命令 ----------
    def _put(self, cmd):
        if not self._closed:
            self._cmd.put(cmd)

    def _drain_commands(self):
        while True:
            try:
                cmd = self._cmd.get_nowait()
            except queue.Empty:
                break
            try:
                self.mixer.apply_cmd(cmd)
            except Exception as e:
                print(L(f"⚠️ 音频命令执行失败 {cmd[0]}: {e}"))

    def audio_callback(self, outdata, frames, time, status):
        # 实时线程：不取锁、不构造 Qt 对象、不阻塞。
        if status:
            self._xrun += 1
            print(status)
        fx = self._fx                      # 一次原子引用读取
        self._drain_commands()
        try:
            outdata[:] = self.mixer.render(frames, fx)
        except Exception as e:
            outdata.fill(0)
            print(L(f"⚠️ 音频回调异常（本块静音）: {e}\n{traceback.format_exc()}"))
        np.clip(outdata, -1.0, 1.0, out=outdata)

    # ---------- GUI 侧公开接口（语义与旧版一致） ----------
    @property
    def xrun_count(self):
        return self._xrun

    def pad_states(self):
        return self.mixer.published_state

    def pad_meta(self):
        with self._meta_lock:
            return dict(self._pad_meta)

    def clear_pads(self):
        with self._meta_lock:
            self._pad_meta.clear()
        self._put(('clear_pads',))

    def load_audio(self, pad_index, file_path, quiet=False):
        data, samplerate = sf.read(file_path, dtype='float32')
        if len(data.shape) == 1:
            data = np.column_stack((data, data))
        elif data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]

        if samplerate != self.sample_rate and len(data) > 0:
            from math import gcd
            g = gcd(int(samplerate), self.sample_rate)
            up, down = self.sample_rate // g, int(samplerate) // g
            try:
                data = signal.resample_poly(data, up, down, axis=0).astype(np.float32)
            except Exception:
                pass
        if len(data) == 0:
            return False
        if data.shape[1] != self.channels:
            if data.shape[1] > self.channels:
                data = data[:, :self.channels]
            else:
                data = np.repeat(data, self.channels, axis=1)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        self._put(('load', pad_index, data))
        with self._meta_lock:
            self._pad_meta[pad_index] = {'file_path': os.path.abspath(file_path)}
        if not quiet:
            print(L(f"📥 素材已加载 Pad {pad_index}: {os.path.basename(file_path)} "
                  f"({len(data)/self.sample_rate:.2f}s @ {self.sample_rate}Hz)"))
        return True

    def trigger_pad(self, pad_index, velocity=None):
        self._put(('trigger', pad_index, vel_gain(velocity)))

    def set_pad_gain(self, pad_index, gain, only_if_playing=False):
        if not PRESSURE_TO_GAIN:
            return False
        self._put(('gain', pad_index, gain, only_if_playing))
        return True

    def pause_all(self):   self._put(('pause', True))
    def resume_all(self):  self._put(('pause', False))
    def stop_all(self):    self._put(('stop_all',))

    def set_mode(self, mode):
        self.play_mode = mode
        self._put(('mode', mode))
        self.stop_all()

    def set_quantize(self, enabled):
        self.quantize_enabled = bool(enabled)
        self._put(('quantize', self.quantize_enabled))

    def update_bpm(self, new_bpm):
        self.bpm = float(new_bpm)
        self._put(('bpm', self.bpm))
        fx = dict(self._fx)
        fx['samples_per_beat'] = max(1, int((60.0 / self.bpm) * self.sample_rate))
        self._fx = fx

    def _publish_fx(self, **changes):
        fx = dict(self._fx)
        fx.update(changes)
        self._fx = fx                      # 原子替换，回调读到的是完整快照

    def set_cc(self, cc_num, value):
        val = value / 127.0
        if cc_num == 46:
            self._publish_fx(delay_time=0.05 + (val * 0.95))
        elif cc_num == 47:
            self._publish_fx(swing_amount=val)
        elif cc_num == 48:
            if value == 0:
                self._publish_fx(gate_rate=0.5, gate_depth=0.0)
            elif value <= 42:
                self._publish_fx(gate_rate=0.5, gate_depth=value / 42.0)
            elif value <= 85:
                self._publish_fx(gate_rate=0.25, gate_depth=(value - 42) / 43.0)
            else:
                self._publish_fx(gate_rate=0.125, gate_depth=(value - 85) / 42.0)
        elif cc_num == 49:
            new_bpm = int(40 + (val * 160))
            self.update_bpm(new_bpm)
            if self.on_bpm_changed: self.on_bpm_changed(new_bpm)
        elif cc_num == 50:
            self._publish_fx(delay_mix=val)
        elif cc_num == 51:
            self._publish_fx(master_volume=val)
        elif cc_num == 52:
            if value == 64:
                self._publish_fx(filter_mode='bypass', b_filt=None, a_filt=None)
            elif value < 64:
                freq = min(20 * (1000 ** (value / 63.0)), self.sample_rate / 2 - 100)
                b, a = signal.butter(2, freq, btype='low', fs=self.sample_rate)
                self._publish_fx(filter_mode='lowpass', b_filt=b, a_filt=a)
            else:
                freq = min(20 * (1000 ** ((value - 64) / 63.0)), self.sample_rate / 2 - 100)
                b, a = signal.butter(2, freq, btype='high', fs=self.sample_rate)
                self._publish_fx(filter_mode='highpass', b_filt=b, a_filt=a)
        elif cc_num == 53:
            self._publish_fx(reverb_mix=val)


# ==========================================
# 📡 多端口 MIDI 中枢（打印文本逐字未动）
# ==========================================
class MidiHub:
    def __init__(self, signals):
        self.signals = signals
        self.lock = threading.Lock()
        self.last_action = {}
        self.last_print = {}
        self.last_emit = {}
        self.recent = {}
        self.silent_notice = False
        self.expression = {
            'last_velocity': 0,
            'last_velocity_note': 0,
            'velocity_count': 0,
            'poly': {},
            'channel_pressure': 0,
        }
        self.function_keys = {}

    def _emit(self, sig, *args):
        try:
            sig.emit(*args)
        except Exception:
            pass

    def handle(self, port, msg):
        t = msg.type
        raw = raw_hex(msg) if VERBOSE_RAW else ''
        raw_str = f"  raw={raw}" if raw else ''
        key = raw if raw else f"{t}:{msg}"
        now = time.monotonic()

        with self.lock:
            if t in THROTTLED_MIDI_TYPES:
                if t == 'polytouch':
                    self.expression['poly'][msg.note] = msg.value
                elif t == 'aftertouch':
                    self.expression['channel_pressure'] = msg.value
                if now - self.last_emit.get(t, -1.0) >= EXPRESSION_EMIT_THROTTLE:
                    self.last_emit[t] = now
                    if t == 'polytouch':
                        self._emit(self.signals.expression_received, 'poly', msg.note, msg.value)
                    elif t == 'aftertouch':
                        self._emit(self.signals.expression_received, 'channel', 0, msg.value)
                if now - self.last_print.get(t, -1.0) >= THROTTLE_PRINT:
                    self.last_print[t] = now
                    if t == 'polytouch':
                        print(L(f"[{port}] 💪 [力度·复压] note={msg.note} pressure={msg.value}{pct(msg.value)}{raw_str}"))
                    elif t == 'aftertouch':
                        print(L(f"[{port}] 💪 [力度·通道压] pressure={msg.value}{pct(msg.value)}{raw_str}"))
                    else:
                        print(L(f"[{port}] 🎛 [弯音] pitch={msg.pitch}{raw_str}"))
                return

            if t not in SILENT_MIDI_TYPES and now - self.recent.get(key, -1.0) < DEDUP_WINDOW:
                print(L(f"[{port}] ♻️ [跨端口重复已去重] {key}  ← 已挡住，不会二次触发"))
                return
            self.recent[key] = now

            if t in SILENT_MIDI_TYPES:
                if not self.silent_notice:
                    self.silent_notice = True
                    print(L(f"[{port}] ℹ️ clock / active_sensing 已静音不刷屏；其余消息全部打印"))
                return

            self.last_print[t] = now

            action, claimed = resolve_transport(msg)
            if claimed:
                if t == 'control_change' and msg.control in CC_LABELS:
                    lab = L(CC_LABELS[msg.control])
                    if msg.value == 0:
                        print(L(f"[{port}] 🎛 [抬键] {lab}  control={msg.control}{raw_str}"))
                    elif action is None:
                        print(L(f"[{port}] 🎛 [预留键] {lab}  control={msg.control}  ← 暂未绑定功能{raw_str}"))
                    else:
                        if now - self.last_action.get(action, -1.0) >= ACTION_DEBOUNCE:
                            self.last_action[action] = now
                            print(L(f"[{port}] 🎛 [走带] {lab}  control={msg.control} → {action}{raw_str}"))
                            self._emit(self.signals.transport_received, action)
                        else:
                            print(L(f"[{port}] 🎛 [走带] {lab} → {action}  (80ms 去抖忽略)"))
                elif t == 'control_change':
                    self.function_keys[msg.control] = msg.value
                    print(L(f"[{port}] 🔘 [功能格] control={msg.control} value={msg.value} → {action}{raw_str}"))
                    self._emit(self.signals.function_received, msg.control, msg.value)
                    if action:
                        self._emit(self.signals.transport_received, action)
                else:
                    print(L(f"[{port}] 🎛 [走带] {t} → {action}{raw_str}"))
                    if action:
                        self._emit(self.signals.transport_received, action)
                return

            if t == 'note_off' or (t == 'note_on' and msg.velocity == 0):
                print(L(f"[{port}] 🎹 [抬键] note={msg.note}{raw_str}"))
            elif t == 'note_on':
                v = msg.velocity
                self.expression['last_velocity'] = v
                self.expression['last_velocity_note'] = msg.note
                self.expression['velocity_count'] += 1
                self._emit(self.signals.expression_received, 'velocity', msg.note, v)
                if VELOCITY_MONITOR:
                    print(L(f"[{port}] 💪 [力度·敲击] note={msg.note} velocity={v}{pct(v)}"
                          f" → gain={vel_gain(v):.3f}{raw_str}"))
                if msg.note in PAD_NOTE_RANGE:
                    print(L(f"[{port}] 🎹 [PAD] note={msg.note} → {pad_desc(msg.note)}{raw_str}"))
                    self._emit(self.signals.midi_received, msg.note, v)
                else:
                    print(L(f"[{port}] 🔎 [功能格? 未映射 note] note={msg.note} vel={v}{raw_str}"))
                    self.function_keys[msg.note] = v
                    print_unmapped_hint(msg)

            elif t == 'control_change':
                if msg.control in CC_KNOB_RANGE:
                    print(L(f"[{port}] 🎚 [旋钮] control={msg.control} value={msg.value} → {CC_NAMES.get(msg.control,'?')}{raw_str}"))
                    self._emit(self.signals.cc_received, msg.control, msg.value)
                else:
                    self.function_keys[msg.control] = msg.value
                    print(L(f"[{port}] 🔎 [功能格? 未映射 CC] control={msg.control} value={msg.value}{raw_str}"))
                    print_unmapped_hint(msg)

            elif t == 'program_change':
                print(L(f"[{port}] 🔎 [功能格? Program Change] program={msg.program}{raw_str}"))
                print_unmapped_hint(msg)
            elif t == 'sysex':
                print(L(f"[{port}] 🔎 [功能格? SysEx] data={msg.data}{raw_str}"))
                print_unmapped_hint(msg)
            else:
                print(L(f"[{port}] 🔎 [其他 MIDI] {msg}{raw_str}"))


class MidiPortManager:
    """显式端口生命周期：可关闭、可重扫。只认 JP-1，不猜通用 MIDI 设备。"""
    def __init__(self, signals):
        self.signals = signals
        self.hub = MidiHub(signals)
        self._stop = threading.Event()
        self._ports = []
        self._threads = []
        self.port_names = []

    def scan(self):
        try:
            names = list(dict.fromkeys(mido.get_input_names()))
        except Exception as e:
            print(L(f"⚠️ MIDI 后端不可用: {e}"))
            return []
        print(L(f"🎹 系统可见 MIDI 输入端口 ({len(names)}): {names}"))
        chosen = [n for n in names if any(t.upper() in n.upper() for t in JP1_PORT_TOKENS)]
        if not chosen:
            print(L("⚠️ 未检测到 JP-1 端口。请检查 USB / 蓝牙连接，本程序只适配 JP-1，不会连接其他设备"))
        return chosen

    def start(self):
        self._stop = threading.Event()
        self._ports, self._threads = [], []
        chosen = self.scan()
        self.port_names = chosen
        print(L(f"📡 将监听 {len(chosen)} 个 JP-1 端口  |  后端: {MIDI_BACKEND}"))
        for n in chosen:
            print(f"    · {n}  →  {port_role(n)}")
        if DETECT_MODE:
            print(L("🔎 上部 6 个功能格：按一下看 [未映射 CC] / [未映射 note] / [Program Change] 打印"))
            print(L("   已登记走带: 22=▶播放 23=■暂停 24=⚪终止 | 19=< 20=蓝牙 21=> (预留)"))
            print(L("💪 力度不是 CC：轻敲/重敲 pad 看 [力度·敲击] velocity=... → gain=..."))
            print(L("   鼠标点 Pad 不传 velocity → 满音量 | 不想要就把 VELOCITY_TO_GAIN / PRESSURE_TO_GAIN 改 False"))
            print(L("⚠️ QUANTIZE 默认 ON：敲 pad 会排到下一小节才响。想立刻听到轻重差别，先把 QUANTIZE 点成 OFF"))
            print(L("🏛️ REVERB 为 4 阻尼梳状 + 2 全通扩散的真混响；DELAY 独立不受影响"))
            print(L("✨ 辉光已分级：激活/播放 紧亮、排队 微光、Idle 绝对平"))
        if not chosen:
            return
        for name in chosen:
            try:
                inport = mido.open_input(name)
                self._ports.append(inport)
                th = threading.Thread(target=self._listen, args=(name, inport),
                                      daemon=True, name=f"midi-{name}")
                th.start()
                self._threads.append(th)
            except Exception as e:
                print(L(f"⚠️ 端口 [{name}] 打开失败: {e}  （其他端口不受影响）"))

    def _listen(self, name, inport):
        print(L(f"✅ 已连接端口: {name}"))
        try:
            for msg in inport:
                if self._stop.is_set():
                    break
                self.hub.handle(name, msg)
        except Exception as e:
            if not self._stop.is_set():
                print(L(f"⚠️ 端口 [{name}] 监听异常: {e}"))

    def stop(self):
        self._stop.set()
        for p in self._ports:
            try: p.close()
            except Exception: pass
        for th in self._threads:
            th.join(timeout=0.6)
        self._ports, self._threads = [], []
        print(L("🔌 MIDI 端口已全部关闭"))

    def rescan(self):
        self.stop()
        self.start()


# ==========================================
# 🪟 外围对话框（独立窗口，不占中央布局）
# ==========================================
class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowTitle(L("运行日志"))
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(f"background-color:{BG_COLOR}; color:{TEXT_WHITE}; font-family:Consolas,'Microsoft YaHei'; font-size:11px;")
        lay.addWidget(self.text)
        row = QHBoxLayout()
        btn_refresh = QPushButton(L("刷新"))
        btn_refresh.clicked.connect(self.reload)
        btn_close = QPushButton(L("关闭"))
        btn_close.clicked.connect(self.accept)
        row.addStretch(); row.addWidget(btn_refresh); row.addWidget(btn_close)
        lay.addLayout(row)
        self.reload()

    def reload(self):
        try:
            lines = LOG_PATH.read_text(encoding='utf-8', errors='replace').splitlines()
            self.text.setPlainText('\n'.join(lines[-800:]))
            self.text.moveCursor(self.text.textCursor().End)
        except Exception as e:
            self.text.setPlainText(L(f"日志读取失败: {e}"))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowTitle(L("关于"))
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        t = QPlainTextEdit()
        t.setReadOnly(True)
        t.setStyleSheet(f"background-color:{BG_COLOR}; color:{TEXT_WHITE}; font-family:'Microsoft YaHei'; font-size:12px;")
        mapping = "\n".join([
            "  Pad 口 (note)  : 68–83 → Bank1 / 36–51 → Bank2 / 52–67 → Bank3",
            "  旋钮 (CC)     : 46 DIV · 47 SWING · 48 GATE · 49 TEMPO · 50 DELAY · 51 VOLUME · 52 FILTER · 53 REVERB",
            "  走带 (CC)     : 22 ▶播放 · 23 ■暂停 · 24 ⚪终止",
            "  预留 (CC)     : 19 < · 20 蓝牙 · 21 >",
        ])
        t.setPlainText(L(
            f"{APP_NAME}\n版本 {APP_VERSION} ({BUILD_TAG})\n"
            f"Python {sys.version.split()[0]}  ·  数据目录 {APP_DATA_DIR}\n\n"
            "【JP-1 专用映射】\n" + mapping + "\n\n"
            "【力度】敲击 velocity 控制该次触发音量 (0.10~1.0)；按住加压实时改正在播放的 pad。\n"
            "【提示】QUANTIZE=ON 时敲击排到下一小节起播；验证力度请先把 QUANTIZE 点成 OFF。\n\n"
            "【第三方组件】\n" + notices_text() +
            f"\n完整声明文件：{NOTICES_PATH}\n"
        ))
        lay.addWidget(t)
        box = QDialogButtonBox(QDialogButtonBox.Ok)
        box.accepted.connect(self.accept)
        lay.addWidget(box)


class MappingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowTitle(L("JP-1 键值表"))
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        t = QPlainTextEdit(); t.setReadOnly(True)
        t.setStyleSheet(f"background-color:{BG_COLOR}; color:{TEXT_WHITE}; font-family:Consolas,'Microsoft YaHei'; font-size:12px;")
        rows = ["JP-1 专用映射（本程序不做其他品牌适配）", ""]
        for cc, act in sorted(TRANSPORT_CCS.items()):
            rows.append(f"  CC {cc:<3} {L(CC_LABELS.get(cc,'')):<10} → {act or '（预留，未绑定）'}")
        rows += ["", "旋钮区"]
        for cc, name in sorted(CC_NAMES.items()):
            rows.append(f"  CC {cc:<3} {name}")
        rows += ["", "Pad 区（Note On）",
                 "  note 68–83 → Bank1 Pad 1–16",
                 "  note 36–51 → Bank2 Pad 1–16",
                 "  note 52–67 → Bank3 Pad 1–16",
                 "", "力度：Note On 自带 velocity(0–127)，不是 CC；触后为 0xA0/0xD0。",
                 "", "上部 6 个功能格若发出消息，终端会打印 [未映射 CC] 并给出填表提示。"]
        t.setPlainText(L('\n'.join(rows)))
        lay.addWidget(t)
        box = QDialogButtonBox(QDialogButtonBox.Ok)
        box.accepted.connect(self.accept)
        lay.addWidget(box)


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg, devices):
        super().__init__(parent)
        self.setStyleSheet(DIALOG_QSS)
        self.setWindowTitle(L("设置"))
        self.resize(500, 380)
        lay = QVBoxLayout(self)
        self._form = form = QFormLayout()

        # 🌐 语言：设置内唯一入口，仅 English / 中文；默认英文
        self._orig_lang = language()
        self.lang = QComboBox()
        self.lang.addItem('English', 'en')
        self.lang.addItem('中文', 'zh')
        self.lang.setCurrentIndex(0 if self._orig_lang == 'en' else 1)
        form.addRow(L("语言"), self.lang)
        self.lang.currentIndexChanged.connect(self._on_language_changed)

        self.dev = QComboBox()
        self._dev_map = {}
        for idx, label in devices:
            self.dev.addItem(label, idx)
            self._dev_map[label] = idx
        cur = next((i for i, (idx, _) in enumerate(devices) if idx == cfg.get('device')), 0)
        self.dev.setCurrentIndex(cur)
        form.addRow(L("输出设备"), self.dev)

        self.sr = QComboBox()
        for v in ('44100', '48000', '88200', '96000', '192000'):
            self.sr.addItem(v, int(v))
        self.sr.setCurrentIndex(max(0, self.sr.findData(int(cfg.get('sample_rate', 44100)))))
        form.addRow(L("采样率 (Hz)"), self.sr)

        self.ch = QComboBox()
        self.ch.addItem(L("立体声 2"), 2); self.ch.addItem(L("单声道 1"), 1)
        self.ch.setCurrentIndex(0 if int(cfg.get('channels', 2)) == 2 else 1)
        form.addRow(L("声道"), self.ch)

        self.bs = QComboBox()
        for v in (256, 512, 1024, 2048, 4096):
            self.bs.addItem(str(v), v)
        self.bs.setCurrentIndex(max(0, self.bs.findData(int(cfg.get('blocksize', 1024)))))
        form.addRow(L("缓冲块 (samples)"), self.bs)

        self.excl = QCheckBox(L("WASAPI 独占（会抢走 FL Studio 等程序的音频设备）"))
        self.excl.setChecked(bool(cfg.get('exclusive', False)))
        form.addRow("", self.excl)

        self.autosave = QCheckBox(L("启用自动保存 / 崩溃恢复"))
        self.autosave.setChecked(bool(cfg.get('autosave', True)))
        form.addRow("", self.autosave)

        self.interval = QSpinBox()
        self.interval.setRange(15, 600)
        self.interval.setValue(int(cfg.get('autosave_interval', 60)))
        self.interval.setSuffix(L(" 秒"))
        form.addRow(L("自动保存间隔"), self.interval)

        self.show_menu = QCheckBox(L("显示菜单栏"))
        self.show_menu.setChecked(bool(cfg.get('show_menu', True)))
        form.addRow("", self.show_menu)

        self.show_status = QCheckBox(L("显示状态栏"))
        self.show_status.setChecked(bool(cfg.get('show_status', True)))
        form.addRow("", self.show_status)

        lay.addLayout(form)
        note = QLabel(L("修改音频参数会重建音频流：已加载的素材会按新采样率自动重采样，混响/延迟尾巴清零。"))
        note.setObjectName("DialogNote")
        self._note = note
        note.setWordWrap(True)
        lay.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def values(self):
        return {
            'device': self.dev.currentData(),
            'sample_rate': self.sr.currentData(),
            'channels': self.ch.currentData(),
            'blocksize': self.bs.currentData(),
            'exclusive': self.excl.isChecked(),
            'autosave': self.autosave.isChecked(),
            'autosave_interval': self.interval.value(),
            'show_menu': self.show_menu.isChecked(),
            'show_status': self.show_status.isChecked(),
            'language': self.lang.currentData(),
        }

    def _on_language_changed(self, _idx):
        set_language(self.lang.currentData())
        self._retranslate()

    def _retranslate(self):
        self.setWindowTitle(L("设置"))
        for widget, zh in (
            (self.lang, "语言"), (self.dev, "输出设备"), (self.sr, "采样率 (Hz)"),
            (self.ch, "声道"), (self.bs, "缓冲块 (samples)"),
            (self.interval, "自动保存间隔"),
        ):
            lbl = self._form.labelForField(widget)
            if lbl is not None:
                lbl.setText(L(zh))
        self.ch.setItemText(0, L("立体声 2"))
        self.ch.setItemText(1, L("单声道 1"))
        self.interval.setSuffix(L(" 秒"))
        self.excl.setText(L("WASAPI 独占（会抢走 FL Studio 等程序的音频设备）"))
        self.autosave.setText(L("启用自动保存 / 崩溃恢复"))
        self.show_menu.setText(L("显示菜单栏"))
        self.show_status.setText(L("显示状态栏"))
        self._note.setText(L("修改音频参数会重建音频流：已加载的素材会按新采样率自动重采样，混响/延迟尾巴清零。"))

    def reject(self):
        # 预览过语言但点了取消 → 回到打开设置前的语言
        if self._orig_lang != language():
            set_language(self._orig_lang)
        super().reject()


# ==========================================
# 🖥️ 主 UI（中央舞台布局逐字未动）
# ==========================================
SHOW_MENU_BAR   = True
SHOW_STATUS_BAR = True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JP-1 Live Host")
        self.resize(1350, 860)
        self.setMinimumSize(900, 720)
        self.setStyleSheet(GLOBAL_QSS)

        # ---- 配置 / 数据 ----
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.cfg = self._load_config()
        self.presets = PresetManager()
        self.current_project = None
        self._dirty = False
        self._crash_checked = False

        # ---- 引擎 / 信号 / MIDI ----
        try:
            self.engine = AudioEngine(
                sample_rate=self.cfg['sample_rate'], channels=self.cfg['channels'],
                blocksize=self.cfg['blocksize'], device=self.cfg['device'],
                exclusive=self.cfg['exclusive'])
        except Exception as e:
            print(L(f"⚠️ 音频引擎启动失败 ({e})，回退默认参数"))
            self.engine = AudioEngine()
        self.signals = AppSignals()
        self.midi = MidiPortManager(self.signals)
        self.midi.start()
        self.signals.midi_received.connect(self.on_midi_in)
        self.signals.cc_received.connect(self.on_cc_in)
        self.signals.transport_received.connect(self.on_transport_in)
        self.signals.expression_received.connect(self.on_expression_in)
        self._last_triggered_pad = None

        # 辉光：全 UI 只从这里收口，缓存 effect，杜绝每帧重建
        self.glow = GlowManager(QColor, QGraphicsDropShadowEffect, THEME_COLOR)
        self._bank_main_colors = [BANK1_COLOR, BANK2_COLOR, BANK3_COLOR]

        self.hardware_target_bank = -1

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.refresh_ui)
        self.ui_timer.start(30)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(500)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.do_autosave)
        self._apply_autosave_interval()

        self.current_bank = 0
        self.all_buttons = [[], [], []]

        from PySide6.QtWidgets import (QFrame as _QFrame, QMenuBar as _QMenuBar,
                                      QSizePolicy as _QSP, QStackedWidget as _QStacked)
        from PySide6.QtGui import QAction as _QAction

        CARD_QSS = f"""
            QFrame#card {{
                background: #171C24;
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
            }}
            QFrame#meter {{ background: #131820; border: 1px solid {BORDER_COLOR}; border-radius: 4px; }}
        """

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 菜单栏：沿用主窗口自带 menubar，原有构建代码继续往上挂菜单项
        _mb = self.menuBar()
        _mb.setVisible(True)
        self.menu = _mb

        def _card(title, fixed_w=0):
            f = _QFrame()
            f.setObjectName('card')
            f.setStyleSheet(CARD_QSS)
            if fixed_w:
                f.setFixedWidth(fixed_w)
            v = QVBoxLayout(f)
            v.setContentsMargins(14, 10, 14, 12)
            v.setSpacing(9)
            c = QLabel(title)
            c.setFixedHeight(14)
            c.setStyleSheet(f"color: {TEXT_GRAY}; font-size: 10px; font-weight: 700;")
            v.addWidget(c)
            return f, v, c

        def _flat(text, h=30):
            b = QPushButton(text)
            b.setFixedHeight(h)
            return b

        # ===== 顶栏：4 张等宽卡片，与底部走带按钮共用同一条左右边界 =====
        top = QHBoxLayout()
        top.setSpacing(12)

        f, v, self.quant_lbl = _card(T('QUANTIZE'))
        self.btn_quantize = _flat(T('ON'))
        self.btn_quantize.setProperty("active", True)
        self.btn_quantize.clicked.connect(self.toggle_quantize)
        self.btn_quantize.setToolTip(L("起播量化：ON 时敲击排到下一小节，OFF 时立即播放（验证力度用 OFF）"))
        self._apply_glow(self.btn_quantize, 'active', THEME_COLOR)
        v.addWidget(self.btn_quantize)
        v.addStretch(1)
        top.addWidget(f, 1)

        f, v, self.mode_label = _card(T('PLAY_MODE'))
        row = QHBoxLayout(); row.setSpacing(8)
        self.btn_loop = _flat(T('LOOP'))
        self.btn_loop.setToolTip(L("循环模式：再按一次同一 Pad 停止"))
        self.btn_oneshot = _flat(T('ONE_SHOT'))
        self.btn_oneshot.setToolTip(L("单次模式：播完一遍自动停止，不绕回、不跨小节复活"))
        self.btn_loop.clicked.connect(lambda: self.set_mode('loop'))
        self.btn_oneshot.clicked.connect(lambda: self.set_mode('oneshot'))
        row.addWidget(self.btn_loop, 1); row.addWidget(self.btn_oneshot, 1)
        v.addLayout(row)
        v.addStretch(1)
        top.addWidget(f, 1)

        f, v, self.bpm_label = _card(T('MASTER_BPM'))
        self.bpm_display = QLabel("120")
        self.bpm_display.setObjectName("BpmDisplay")
        self.bpm_display.setFixedHeight(30)
        self.bpm_display.setAlignment(Qt.AlignCenter)
        v.addWidget(self.bpm_display)
        v.addStretch(1)
        top.addWidget(f, 1)

        f, v, self.preset_label = _card(T('PROJECT'))
        row = QHBoxLayout(); row.setSpacing(8)
        self.btn_save = _flat(T('SAVE'))
        self.btn_save.clicked.connect(self.save_preset)
        self.btn_save.setToolTip(L("保存工程 (Ctrl+S)：素材会复制进工程目录，路径可迁移"))
        self.btn_load = _flat(T('LOAD'))
        self.btn_load.clicked.connect(self.load_preset)
        self.btn_load.setToolTip(L("打开工程 (Ctrl+O)：兼容旧版 v1 工程文件"))
        row.addWidget(self.btn_save, 1); row.addWidget(self.btn_load, 1)
        v.addLayout(row)
        v.addStretch(1)
        top.addWidget(f, 1)

        main_layout.addLayout(top)

        # ===== 中部：左=旋钮卡片，右=Pad 卡片（BANK 与方阵同一容器、严格同缘）=====
        body = QHBoxLayout()
        body.setSpacing(12)

        kf, kv, _ = _card('KNOBS  /  CC 46-53', 196)
        knob_layout = QGridLayout()
        knob_layout.setHorizontalSpacing(10)
        knob_layout.setVerticalSpacing(10)
        for _r in range(4):
            knob_layout.setRowStretch(_r, 1)
        for _c in range(2):
            knob_layout.setColumnStretch(_c, 1)
        self.knobs = []
        dial_configs = [
            ("DIV", 46, THEME_COLOR, False, False),
            ("SWING", 47, THEME_COLOR, False, False),
            ("GATE", 48, GATE_ORANGE, True, False),
            ("TEMPO", 49, THEME_COLOR, False, True),
            ("DELAY", 50, THEME_COLOR, False, False),
            ("VOLUME", 51, THEME_COLOR, False, False),
            ("FILTER", 52, THEME_COLOR, False, False),
            ("REVERB", 53, THEME_COLOR, False, False)
        ]
        for name, cc_num, color, is_gate, is_tempo in dial_configs:
            knob = VitalKnob(name, color, is_gate, is_tempo)
            knob.setToolTip(L(f"{name}  (CC {cc_num}) — 拖动 / 滚轮调节"))
            if cc_num == 46: knob.setValue(127)
            elif cc_num == 47: knob.setValue(0)
            elif cc_num == 48: knob.setValue(0)
            elif cc_num == 49: knob.setValue(64)
            elif cc_num == 51: knob.setValue(100)
            elif cc_num == 52: knob.setValue(64)
            else: knob.setValue(0)
            knob.valueChanged.connect(lambda val, cc=cc_num: self._on_dial_changed(cc, val))
            knob_layout.addWidget(knob, len(self.knobs) % 4, len(self.knobs) // 4, Qt.AlignCenter)
            self.knobs.append((knob, cc_num))
        kv.addLayout(knob_layout, 1)
        body.addWidget(kf)

        pf, pv, _ = _card('PAD MATRIX  /  3 BANKS')

        def _info_column(items):
            col = QVBoxLayout(); col.setSpacing(7)
            for k, val in items:
                r = QHBoxLayout()
                a = QLabel(k)
                a.setStyleSheet(f"color: #5F6B79; font-size: 10px;")
                b = QLabel(val)
                b.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                b.setStyleSheet(f"color: {TEXT_WHITE}; font-size: 10px; font-weight: 700;")
                r.addWidget(a, 1); r.addWidget(b, 0)
                col.addLayout(r)
            m = _QFrame(); m.setObjectName('meter'); m.setStyleSheet(CARD_QSS)
            m.setFixedHeight(8)
            col.addWidget(m)
            col.addStretch(1)
            return col

        PAD, GAP = 96, 10
        MW = 4 * PAD + 3 * GAP
        mx = QWidget()
        mx.setMaximumWidth(MW)
        mv = QVBoxLayout(mx)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(10)

        bank_bar = QHBoxLayout()
        bank_bar.setSpacing(GAP)
        bank_names = ["BANK 1", "BANK 2", "BANK 3"]
        self.bank_btns = []
        for i in range(3):
            b = QPushButton(bank_names[i])
            b.setFixedHeight(34)
            b.clicked.connect(lambda checked, index=i: self.switch_bank(index))
            b.setToolTip(L(f"切换到 {bank_names[i]}（硬件敲击对应 Bank 会自动跳转）"))
            bank_bar.addWidget(b, 1)
            self.bank_btns.append(b)
        bank_bar.setContentsMargins(0, 0, 0, 0)
        mv.addLayout(bank_bar)

        class _NoInset:
            def setContentsMargins(self, *args):
                pass
        self._bank_bar = _NoInset()

        self.stacked_widget = _QStacked()
        for ui_page_idx in range(3):
            page_widget = QWidget()
            grid = QGridLayout(page_widget)
            grid.setSpacing(GAP)
            grid.setContentsMargins(0, 0, 0, 0)
            bank_buttons = []
            for i in range(16):
                global_pad_index = ui_page_idx * 16 + i
                btn = PadButton(f"Pad {i+1}", global_pad_index, self)
                btn.setSizePolicy(_QSP.Fixed, _QSP.Fixed)
                btn.setFixedSize(PAD, PAD)
                btn.setStyleSheet(PAD_IDLE)
                btn.setToolTip(L("单击触发 · 双击 / 右键加载素材"))
                btn.clicked.connect(lambda checked, index=global_pad_index: self.trigger_from_ui(index))
                btn.setContextMenuPolicy(Qt.CustomContextMenu)
                btn.customContextMenuRequested.connect(lambda pos, index=global_pad_index, b=btn: self.load_file_to_pad(index, b))
                grid.addWidget(btn, 3 - (i // 4), i % 4)
                bank_buttons.append(btn)
            self.all_buttons[ui_page_idx] = bank_buttons
            self.stacked_widget.addWidget(page_widget)
        mv.addWidget(self.stacked_widget, 1)

        inner = QHBoxLayout()
        inner.setSpacing(14)
        inner.addLayout(_info_column([
            ('SESSION', 'LIVE'), ('ACTIVE BANK', '01'), ('QUANTIZE', 'ON'),
            ('VELOCITY', '0.82'), ('MIDI IN', 'JP-1 PAD')]), 1)
        inner.addWidget(mx, 0, Qt.AlignVCenter)
        inner.addLayout(_info_column([
            ('OUTPUT', '48 kHz'), ('BUFFER', '256 smp'), ('LATENCY', '5.3 ms'),
            ('CPU', '2.1 %'), ('DEVICE', 'WASAPI')]), 1)
        pv.addLayout(inner, 1)
        body.addWidget(pf, 1)
        main_layout.addLayout(body, 1)

        # ===== 底部走带：三按钮等分，左右缘与顶栏卡片冲齐 =====
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(12)
        self.btn_play = TransportButton('play')
        self.btn_play.setFixedHeight(44)
        self.btn_play.clicked.connect(self.play_all)
        self.btn_play.setToolTip(L("播放 / 从暂停恢复 (JP-1 CC 22)"))
        self.btn_pause = TransportButton('pause')
        self.btn_pause.setFixedHeight(44)
        self.btn_pause.clicked.connect(self.pause_all)
        self.btn_pause.setToolTip(L("暂停 (JP-1 CC 23)"))
        self.btn_stop = TransportButton('stop')
        self.btn_stop.setFixedHeight(44)
        self.btn_stop.clicked.connect(self.stop_all)
        self.btn_stop.setToolTip(L("终止：清空播放与排队 (JP-1 CC 24 / 空格)"))
        ctrl_bar.addWidget(self.btn_play, 1)
        ctrl_bar.addWidget(self.btn_pause, 1)
        ctrl_bar.addWidget(self.btn_stop, 1)
        main_layout.addLayout(ctrl_bar)

        # 菜单栏消失的真因：_build_menu_bar 按 cfg['show_menu'] 隐藏
        self.cfg['show_menu'] = True
        self.cfg['show_status'] = True
        try:
            self._build_menu_bar()
            self._build_status_bar()
        except Exception:
            self.status = self.statusBar()
        self.settings.setValue('ui/show_menu', True)
        self.settings.setValue('ui/show_status', True)
        self.settings.sync()
        self.menuBar().setStyleSheet(f"""QMenuBar{{background:{BG_COLOR};color:{TEXT_GRAY};border-bottom:1px solid {BORDER_COLOR};padding:3px 6px;font-size:11px;}} QMenuBar::item{{background:transparent;padding:4px 10px;color:{TEXT_GRAY};}} QMenuBar::item:selected{{color:{THEME_COLOR};}} QMenu{{background:#171C24;color:{TEXT_WHITE};border:1px solid {BORDER_COLOR};}} QMenu::item{{padding:5px 20px;}} QMenu::item:selected{{background:#062A30;color:{THEME_COLOR};}}""")
        self.statusBar().setStyleSheet(f"""QStatusBar{{background:{BG_COLOR};color:{TEXT_GRAY};border-top:1px solid {BORDER_COLOR};font-size:10px;}} QStatusBar::item{{border:0;}}""")
        self.switch_bank(0)
        self.update_mode_ui()
        self._set_quantize_ui(True, emit=False)

        for widget in self.findChildren(QWidget):
            widget.setFocusPolicy(Qt.NoFocus)
        self.setFocus()

        # 必须先读旧 session 状态再写本次启动标记，否则永远误判为「上次崩溃」
        self._offer_crash_recovery()
        self.presets.mark_session_start()

    # ------------------------------------------
    # 配置 / 菜单 / 状态栏
    # ------------------------------------------
    def _load_config(self):
        g = self.settings
        dsr, dch = query_audio_defaults()
        return {
            'sample_rate': int(g.value('audio/sample_rate', dsr)),
            'channels': int(g.value('audio/channels', dch)),
            'blocksize': int(g.value('audio/blocksize', 1024)),
            'device': int(g.value('audio/device', -1)),
            'exclusive': bool(g.value('audio/exclusive', False) in (True, 'true', '1', 1)),
            'autosave': bool(g.value('app/autosave', True) in (True, 'true', '1', 1)),
            'autosave_interval': int(g.value('app/autosave_interval', 60)),
            'show_menu': bool(g.value('ui/show_menu', True) in (True, 'true', '1', 1)),
            'show_status': bool(g.value('ui/show_status', True) in (True, 'true', '1', 1)),
            'language': language(),
        }

    def _save_config(self):
        g = self.settings
        for k, v in self.cfg.items():
            if k == 'language':   # 语言由 LANG_FILE 单独持久化
                continue
            key = ('audio/' + k if k in ('sample_rate', 'channels', 'blocksize', 'device', 'exclusive')
                   else ('app/' + k if k in ('autosave', 'autosave_interval') else 'ui/' + k))
            if v is None:
                g.remove(key)
            else:
                g.setValue(key, v)
        g.sync()

    def _apply_autosave_interval(self):
        if self.cfg['autosave']:
            self.autosave_timer.start(self.cfg['autosave_interval'] * 1000)
        else:
            self.autosave_timer.stop()

    def _build_menu_bar(self):
        self.menu = self.menuBar()
        self.menuBar().setVisible(True)
        self.menu.clear()          # retranslate() 会重建菜单，避免重复叠加
        self.menu.setVisible(bool(self.cfg['show_menu'] and SHOW_MENU_BAR))

        m_file = self.menu.addMenu(L("文件(&F)"))
        act_new = QAction(L("新建工程"), self); act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self.new_project); m_file.addAction(act_new)
        act_open = QAction(L("打开工程…"), self); act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self.load_preset); m_file.addAction(act_open)
        act_save = QAction(L("保存工程…"), self); act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_preset); m_file.addAction(act_save)
        self.recent_menu = m_file.addMenu(L("最近工程"))
        self._refresh_recent_menu()
        m_file.addSeparator()
        act_quit = QAction(L("退出"), self); act_quit.setShortcut(QKeySequence("Alt+F4"))
        act_quit.triggered.connect(self.close); m_file.addAction(act_quit)

        m_edit = self.menu.addMenu(L("编辑(&E)"))
        act_settings = QAction(L("设置…"), self); act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(self.open_settings); m_edit.addAction(act_settings)
        act_rescan = QAction(L("重新扫描 JP-1 端口"), self)
        act_rescan.triggered.connect(self.rescan_midi); m_edit.addAction(act_rescan)

        m_view = self.menu.addMenu(L("视图(&V)"))
        act_log = QAction(L("运行日志…"), self); act_log.setShortcut(QKeySequence("Ctrl+L"))
        act_log.triggered.connect(self.open_log); m_view.addAction(act_log)
        act_map = QAction(L("JP-1 键值表…"), self)
        act_map.triggered.connect(self.open_mapping); m_view.addAction(act_map)

        m_help = self.menu.addMenu(L("帮助(&H)"))
        act_about = QAction(L("关于…"), self); act_about.setShortcut(QKeySequence("F1"))
        act_about.triggered.connect(self.open_about); m_help.addAction(act_about)

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        items = self.presets.recent()
        if not items:
            a = self.recent_menu.addAction(L("（暂无）")); a.setEnabled(False)
            return
        for p in items:
            a = self.recent_menu.addAction(Path(p).name)
            a.setToolTip(p)
            a.triggered.connect(lambda checked=False, path=p: self._load_project_path(path))

    def _build_status_bar(self):
        self.status = self.statusBar()
        self.status.setVisible(bool(self.cfg['show_status'] and SHOW_STATUS_BAR))
        self.status.showMessage(L("就绪"))
        self.update_status_bar()

    def update_status_bar(self):
        if not self.status.isVisible():
            return
        proj = Path(self.current_project).name if self.current_project else L("未保存工程")
        self.status.showMessage(L(
            f"JP-1 端口 {len(self.midi.port_names)}  |  "
            f"{'独占' if self.engine.exclusive else '共享'} {self.engine.sample_rate}Hz/"
            f"{self.engine.channels}ch bs={self.engine.blocksize}  |  "
            f"xrun {self.engine.xrun_count}  |  {proj}{' *' if self._dirty else ''}"))

    def open_settings(self):
        dlg = SettingsDialog(self, self.cfg, list_output_devices())
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.values()
        old = dict(self.cfg)
        self.cfg.update(new)
        self._save_config()
        lang_changed = old.get('language') != new.get('language')
        self._apply_autosave_interval()
        self.menu.setVisible(bool(new['show_menu'] and SHOW_MENU_BAR))
        self.status.setVisible(bool(new['show_status'] and SHOW_STATUS_BAR))
        audio_keys = ('sample_rate', 'channels', 'blocksize', 'device', 'exclusive')
        if any(old[k] != new[k] for k in audio_keys):
            try:
                self.engine.rebuild_stream(new['sample_rate'], new['channels'],
                                           new['blocksize'], new['device'], new['exclusive'])
                show_message(self, 'info', L("设置"), L("音频流已按新参数重建。"))
            except Exception as e:
                show_message(self, 'error', L("错误"), L(f"音频流重建失败：{e}\n\n已保留原设置，请重启后再试。"))
                self.cfg.update(old)
                self._save_config()
        if lang_changed:
            self.retranslate()
        self.update_status_bar()

    def _set_quantize_text(self, enabled=None):
        """ON / OFF 也走双语表；不传参时读引擎当前真值。"""
        if enabled is None:
            enabled = self.engine.quantize_enabled
        self.btn_quantize.setText(T('ON') if enabled else T('OFF'))

    def _apply_top_text(self):
        """仅顶部四组功能栏及其下属控件随语言重刷。
        BANK / Pad / 8 个旋钮名 / 产品名 / BPM 数字一律不动。"""
        self.quant_lbl.setText(T('QUANTIZE'))
        self.mode_label.setText(T('PLAY_MODE'))
        self.bpm_label.setText(T('MASTER_BPM'))
        self.preset_label.setText(T('PROJECT'))
        self.btn_loop.setText(T('LOOP'))
        self.btn_oneshot.setText(T('ONE_SHOT'))
        self.btn_save.setText(T('SAVE'))
        self.btn_load.setText(T('LOAD'))
        self._set_quantize_text()

    def retranslate(self):
        """语言切换后即时刷新主窗所有用户可见文本，布局/配色/辉光一律不动。"""
        self._apply_top_text()
        self._build_menu_bar()
        self.btn_quantize.setToolTip(L("起播量化：ON 时敲击排到下一小节，OFF 时立即播放（验证力度用 OFF）"))
        self.btn_loop.setToolTip(L("循环模式：再按一次同一 Pad 停止"))
        self.btn_oneshot.setToolTip(L("单次模式：播完一遍自动停止，不绕回、不跨小节复活"))
        self.btn_play.setToolTip(L("播放 / 从暂停恢复 (JP-1 CC 22)"))
        self.btn_pause.setToolTip(L("暂停 (JP-1 CC 23)"))
        self.btn_stop.setToolTip(L("终止：清空播放与排队 (JP-1 CC 24 / 空格)"))
        for knob, cc in self.knobs:
            knob.setToolTip(L(f"{knob.name}  (CC {cc}) — 拖动 / 滚轮调节"))
        for i, btn in enumerate(self.bank_btns):
            btn.setToolTip(L(f"切换到 BANK {i+1}（硬件敲击对应 Bank 会自动跳转）"))
        for bank in self.all_buttons:
            for b in bank:
                b.setToolTip(L("单击触发 · 双击 / 右键加载素材"))
        self._refresh_recent_menu()
        self.update_status_bar()

    def open_log(self):
        LogDialog(self).exec()

    def open_about(self):
        AboutDialog(self).exec()

    def open_mapping(self):
        MappingDialog(self).exec()

    def rescan_midi(self):
        self.midi.rescan()
        self.update_status_bar()

    # ------------------------------------------
    # ✨ 唯一辉光入口：委托给可测试的 GlowManager，观感不变
    # ------------------------------------------
    def _apply_glow(self, widget, level, color_key=None):
        return self.glow.apply(widget, level, color_key)

    # ------------------------------------------
    # 工程：收集 / 应用 / 自动保存 / 崩溃恢复
    # ------------------------------------------
    def collect_state(self):
        return {
            'bpm': int(self.bpm_display.text()),
            'quantize': bool(self.engine.quantize_enabled),
            'play_mode': self.engine.play_mode,
            'dials': [k.value() for k, cc in self.knobs],
            'pads': {str(i): m['file_path'] for i, m in self.engine.pad_meta().items()},
        }

    def do_autosave(self):
        if not self._dirty:
            return
        try:
            self.presets.write_autosave(self.collect_state())
        except Exception as e:
            print(L(f"⚠️ 自动保存失败: {e}"))

    def _offer_crash_recovery(self):
        if self._crash_checked:
            return
        self._crash_checked = True
        if not (self.cfg['autosave'] and self.presets.crashed_last_time()
                and self.presets.read_autosave() is not None):
            return
        r = show_message(
            self, 'ask', L("恢复工程"),
            L("检测到上次异常退出，且存在自动保存的工程。\n是否恢复？"),
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self._apply_state(self.presets.read_autosave(), from_autosave=True)
            show_message(self, 'info', L("已恢复"), L("自动保存的工程已恢复，请用「保存工程」另存为正式文件。"))

    def new_project(self):
        if self._dirty and show_message(
                self, 'ask', L("新建工程"), L("当前改动尚未保存，确定清空？"),
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._apply_state(self.presets.empty_data())
        self.current_project = None
        self._dirty = False

    def save_preset(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, L("Save Project"), str(self.current_project or ""), "JP-1 Project (*.jp1.json);;JSON Files (*.json)")
        if not file_path:
            return
        try:
            res = self.presets.save(file_path, self.collect_state())
            self.current_project = file_path
            self.presets.add_recent(file_path)
            self._refresh_recent_menu()
            self._dirty = False
            self.update_status_bar()
            show_message(
                self, 'info', L("Success"),
                L(f"Project Saved!\n\n素材已收进：{res['sample_dir']}\n"
                f"共 {len(res['samples'])} 个文件，工程内使用相对路径，可整体搬走。"))
        except Exception as e:
            show_message(self, 'error', L("Error"), L(f"保存失败：{e}"))

    def load_preset(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, L("Load Project"), "", "JP-1 Project (*.jp1.json);;JSON Files (*.json)")
        if file_path:
            self._load_project_path(file_path)

    def _load_project_path(self, file_path):
        try:
            data, missing = self.presets.load(file_path)
            self.current_project = file_path       # 必须先定工程目录，相对素材路径才有基准
            self._apply_state(data, base_dir=Path(file_path).parent)
            self.presets.add_recent(file_path)
            self._refresh_recent_menu()
            self._dirty = False
            self.update_status_bar()
            if missing:
                lines = '\n'.join(f"  Pad {k}: {v}" for k, v in missing[:6])
                more = L(f"\n  …另有 {len(missing)-6} 个") if len(missing) > 6 else ""
                show_message(self, 'warn', L("部分素材缺失"),
                             L(f"以下素材未找到，对应 Pad 保持空白：\n\n{lines}{more}\n\n"
                             "请把素材放回工程目录的 samples 文件夹后重新打开。"))
            else:
                show_message(self, 'info', L("Success"), L("Project Loaded!"))
        except Exception as e:
            show_message(self, 'error', L("Error"), L(f"Load failed: {str(e)}"))
            print(traceback.format_exc())

    def _apply_state(self, data, base_dir=None, from_autosave=False):
        """统一应用工程数据：修掉旧版 toggle_quantize() 连调两次的脆写法。"""
        # 模式必须走 set_mode：它会把命令投给 RT 线程，直接赋值只改了 GUI 镜像
        self.engine.set_mode(data['play_mode'])
        self.update_mode_ui()
        self._set_quantize_ui(data['quantize'], emit=True)

        # 旋钮 setValue 在值未变化时不 emit，故显式再 set_cc 一次，保证 fx 快照同步
        dials = list(data['dials'][:len(self.knobs)])
        for i, val in enumerate(dials):
            knob, cc_num = self.knobs[i]
            knob.setValue(val)
            self.engine.set_cc(cc_num, val)
        # TEMPO 旋钮会回写 bpm，工程里的 bpm 才是最终真值
        self.engine.update_bpm(data['bpm'])
        self.bpm_display.setText(str(data['bpm']))
        self._set_quantize_ui(data['quantize'], emit=False)

        self.engine.stop_all()
        self.engine.clear_pads()
        for bank in self.all_buttons:
            for idx, b in enumerate(bank):
                b.setText(f"Pad {idx+1}")
                b.setStyleSheet(PAD_IDLE)
                self._apply_glow(b, None)

        resolved, _missing = resolve_pad_paths(data, base_dir, fallback_dir=APP_DATA_DIR)
        for pad_index, abs_p in sorted(resolved.items()):
            try:
                if self.engine.load_audio(pad_index, abs_p):
                    bank_idx = pad_index // 16
                    pad_idx_in_bank = pad_index % 16
                    self.all_buttons[bank_idx][pad_idx_in_bank].setText(
                        os.path.basename(abs_p)[:10])
            except Exception as e:
                print(L(f"⚠️ 素材加载失败 Pad {pad_index}: {e}"))
        if from_autosave:
            self._dirty = True

    def _on_dial_changed(self, cc, val):
        self.engine.set_cc(cc, val)
        self._dirty = True

    # ------------------------------------------
    # 原有交互（布局 / 样式 / 辉光逻辑逐字保留）
    # ------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)

    def set_mode(self, mode):
        self.engine.set_mode(mode)
        self.update_mode_ui()
        self._dirty = True

    def update_mode_ui(self):
        active_style = f"""
            QPushButton {{ border: 1px solid {THEME_COLOR}; background-color: #001A22; color: {THEME_COLOR}; border-radius: 4px; }}
            QPushButton:hover {{ background-color: #002A33; border: 1px solid {THEME_COLOR}; }}
        """
        inactive_style = f"""
            QPushButton {{ border: 1px solid {BORDER_COLOR}; background-color: transparent; color: {TEXT_GRAY}; border-radius: 4px; }}
            QPushButton:hover {{ border: 1px solid {THEME_COLOR}; color: {THEME_COLOR}; }}
        """

        if self.engine.play_mode == 'loop':
            self.btn_loop.setProperty("active", True)
            self.btn_oneshot.setProperty("active", False)
            self.btn_loop.setStyleSheet(active_style)
            self.btn_oneshot.setStyleSheet(inactive_style)

            self._apply_glow(self.btn_loop, 'active', THEME_COLOR)
            self._apply_glow(self.btn_oneshot, None)
        else:
            self.btn_loop.setProperty("active", False)
            self.btn_oneshot.setProperty("active", True)
            self.btn_loop.setStyleSheet(inactive_style)
            self.btn_oneshot.setStyleSheet(active_style)

            self._apply_glow(self.btn_oneshot, 'active', THEME_COLOR)
            self._apply_glow(self.btn_loop, None)

    def _set_quantize_ui(self, enabled, emit=True):
        """单一真值来源：同时更新按钮外观与引擎，不再靠 toggle 两次对齐。"""
        enabled = bool(enabled)
        if emit:
            self.engine.set_quantize(enabled)
            self._dirty = True
        self._set_quantize_text(enabled)
        self.btn_quantize.setProperty("active", enabled)
        if enabled:
            self._apply_glow(self.btn_quantize, 'active', THEME_COLOR)
        else:
            self._apply_glow(self.btn_quantize, None)
        self.btn_quantize.style().unpolish(self.btn_quantize)
        self.btn_quantize.style().polish(self.btn_quantize)

    def toggle_quantize(self):
        self._set_quantize_ui(not self.engine.quantize_enabled, emit=True)

    def update_ui_bpm(self, bpm):
        self.bpm_display.setText(str(bpm))
        self._dirty = True

    def play_all(self):
        self.engine.resume_all()

    def pause_all(self):
        self.engine.pause_all()

    def stop_all(self):
        self.engine.stop_all()

    def on_transport_in(self, action):
        if action == 'play':
            self.btn_play.animateClick()
        elif action == 'pause':
            self.btn_pause.animateClick()
        elif action == 'stop':
            self.btn_stop.animateClick()

    def on_expression_in(self, kind, note, value):
        if not PRESSURE_TO_GAIN or kind == 'velocity':
            return
        g = vel_gain(value)
        if kind == 'poly':
            hit = note_to_pad(note)
            if hit:
                self.engine.set_pad_gain(hit[1], g, only_if_playing=True)
        elif kind == 'channel':
            if self._last_triggered_pad is not None:
                self.engine.set_pad_gain(self._last_triggered_pad, g, only_if_playing=True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.btn_stop.animateClick()
        else:
            super().keyPressEvent(event)

    def refresh_ui(self):
        if self.hardware_target_bank != -1:
            self.switch_bank(self.hardware_target_bank)
            self.hardware_target_bank = -1

        ui_page_idx = self.current_bank
        buttons = self.all_buttons[ui_page_idx]
        styles = [PAD_PLAY_1, PAD_PLAY_2, PAD_PLAY_3]
        bank_main = self._bank_main_colors[ui_page_idx]
        states = self.engine.pad_states()          # 原子发布的快照，无锁

        for i in range(16):
            global_pad_index = ui_page_idx * 16 + i
            btn = buttons[i]
            st = states.get(global_pad_index)
            if st is not None:
                queued, playing = st
                if queued:
                    if btn.styleSheet() != PAD_QUEUED:
                        btn.setStyleSheet(PAD_QUEUED)
                    self._apply_glow(btn, 'soft', '#FFD700')
                elif playing:
                    if btn.styleSheet() != styles[ui_page_idx]:
                        btn.setStyleSheet(styles[ui_page_idx])
                    self._apply_glow(btn, 'playing', bank_main)
                else:
                    if btn.styleSheet() != PAD_IDLE:
                        btn.setStyleSheet(PAD_IDLE)
                    self._apply_glow(btn, None)
            else:
                if btn.styleSheet() != PAD_IDLE:
                    btn.setStyleSheet(PAD_IDLE)
                self._apply_glow(btn, None)

    def on_cc_in(self, cc_num, value):
        if cc_num in TRANSPORT_CCS or cc_num in FUNCTION_CCS or cc_num not in CC_KNOB_RANGE:
            return
        for knob, cc in self.knobs:
            if cc == cc_num:
                knob.setValue(value)
                self.engine.set_cc(cc_num, value)
                break

    def switch_bank(self, ui_page_idx):
        self.current_bank = ui_page_idx
        self.stacked_widget.setCurrentIndex(ui_page_idx)

        bank_colors = [
            (BANK1_COLOR, "#001A33", "#002A4D", QColor(30, 136, 255, 120)),
            (BANK2_COLOR, "#221100", "#332200", QColor(255, 107, 0, 120)),
            (BANK3_COLOR, "#001A0D", "#002A11", QColor(0, 255, 102, 120))
        ]

        for i, btn in enumerate(self.bank_btns):
            c_text, c_bg, c_hover, _ = bank_colors[i]
            if i == ui_page_idx:
                btn.setStyleSheet(f"""
                    QPushButton {{ border: 1px solid {c_text}; background-color: {c_bg}; color: {c_text}; font-weight: bold; border-radius: 4px; }}
                    QPushButton:hover {{ background-color: {c_hover}; border: 1px solid {c_text}; }}
                """)
                self._apply_glow(btn, 'active', c_text)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ border: 1px solid {BORDER_COLOR}; background-color: transparent; color: {TEXT_GRAY}; border-radius: 4px; }}
                    QPushButton:hover {{ border: 1px solid {c_text}; color: {c_text}; }}
                """)
                self._apply_glow(btn, None)

    def load_file_to_pad(self, global_pad_index, btn):
        file_path, _ = QFileDialog.getOpenFileName(self, f"Load Sample", "", "Audio Files (*.wav *.mp3)")
        if file_path:
            try:
                self.engine.load_audio(global_pad_index, file_path)
                filename = os.path.basename(file_path)[:10]
                btn.setText(f"{filename}")
                self._dirty = True
            except Exception as e:
                show_message(self, 'error', L("Error"), L(f"素材加载失败：{e}"))

    def trigger_from_ui(self, global_pad_index):
        self.engine.trigger_pad(global_pad_index)

    def on_midi_in(self, note, velocity):
        if note in TRANSPORT_NOTES:
            return
        hit = note_to_pad(note)
        if hit is None or velocity <= 0:
            return
        ui_page_idx, global_pad_index = hit
        self._last_triggered_pad = global_pad_index

        if ui_page_idx != self.current_bank:
            self.hardware_target_bank = ui_page_idx

        self.engine.trigger_pad(global_pad_index, velocity)

    # ------------------------------------------
    # 有序退出
    # ------------------------------------------
    def closeEvent(self, event):
        try:
            if self._dirty and not self.cfg['autosave']:
                r = show_message(self, 'ask', L("未保存的改动"),
                                 L("当前工程有未保存的改动，且自动保存未开启。仍要退出？"),
                                 QMessageBox.Yes | QMessageBox.No)
                if r != QMessageBox.Yes:
                    event.ignore()
                    return
            self.ui_timer.stop()
            self.status_timer.stop()
            self.autosave_timer.stop()
            if self._dirty and self.cfg['autosave']:
                self.do_autosave()
            self.midi.stop()
            self.engine.shutdown()
            self._save_config()
            self.presets.mark_clean_exit()
            print(L("👋 已有序退出"))
            event.accept()
        except Exception as e:
            print(L(f"⚠️ 退出清理异常: {e}"))
            event.accept()


def main():
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    setup_appdata()
    print(f"▶ {APP_NAME}  v{APP_VERSION} ({BUILD_TAG})")
    print(L(f"📁 数据目录: {APP_DATA_DIR}"))
    print(L(f"📄 日志: {LOG_PATH}"))
    app = QApplication(sys.argv)
    from PySide6.QtCore import QSharedMemory
    _singleton = QSharedMemory("JP1_LIVE_HOST_SINGLE")
    if not _singleton.create(1):
        sys.exit(0)
    import os as _os, sys as _sys
    from PySide6.QtGui import QIcon as _QIcon
    for _base in (getattr(_sys, '_MEIPASS', ''),
                  _os.path.dirname(_os.path.abspath(_sys.executable)),
                  _os.path.dirname(_os.path.abspath(__file__))):
        _ico = _os.path.join(_base, 'jamjum.ico')
        if _os.path.exists(_ico):
            app.setWindowIcon(_QIcon(_ico))
            break
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setStyleSheet(CHROME_QSS)   # 仅作用于新增外围壳层；中央舞台仍只吃 GLOBAL_QSS
    try:
        app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    import os as _os, sys as _sys
    from PySide6.QtCore import QTimer, Qt as _Qt
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
    from PySide6.QtWidgets import QWidget as _QWidget
    _base = getattr(_sys, '_MEIPASS', _os.path.dirname(_os.path.abspath(__file__)))
    _ico = _os.path.join(_base, 'jamjum.ico')
    _pm  = _os.path.join(_base, 'splash.png')
    try:
        app.setWindowIcon(QIcon(_ico))
    except Exception:
        pass
    class _Boot(QWidget):
        def __init__(self):
            super().__init__()
            from PySide6.QtCore import Qt as _Q, QTimer as _T
            from PySide6.QtGui import QIcon as _I
            import sys as _s, os as _o
            _base = getattr(_s, "_MEIPASS", _o.path.dirname(_o.path.abspath(__file__)))
            self.setWindowFlags(_Q.FramelessWindowHint | _Q.WindowStaysOnTopHint)
            try: self.setWindowIcon(_I(_o.path.join(_base, "jamjum.ico")))
            except Exception: pass
            self.resize(960, 540)
            self._v = 0; self._done = False
            self._t = _T(self)
            self._t.timeout.connect(self._tick)
            self._t.start(16)
        def _tick(self):
            if self._done: return
            self._v = min(90, self._v + 3)
            self.update()
            if self._v >= 90: self._t.stop()
        def stage(self, v):
            self._v = max(self._v, min(90, v)); self.update()
        def finish(self):
            self._done = True; self._t.stop()
            self._v = 100; self.update()
            from PySide6.QtWidgets import QApplication as _A
            _A.processEvents()
        def paintEvent(self, e):
            from PySide6.QtGui import QPainter as _P, QPixmap as _PX, QColor as _C
            from PySide6.QtCore import Qt as _Q
            import sys as _s, os as _o
            _base = getattr(_s, "_MEIPASS", _o.path.dirname(_o.path.abspath(__file__)))
            _sp = _o.path.join(_base, "splash.png")
            p = _P(self)
            if _o.path.isfile(_sp):
                p.drawPixmap(0, 0, _PX(_sp).scaled(self.size(), _Q.IgnoreAspectRatio, _Q.SmoothTransformation))
            else:
                p.fillRect(self.rect(), _C(20, 22, 28))
            y = self.height() - 6
            p.fillRect(0, y, self.width(), 6, _C(48, 54, 62))
            p.fillRect(0, y, int(self.width() * self._v / 100.0), 6, _C(255, 255, 255))
            p.end()
    class _Boot(_QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(_Qt.FramelessWindowHint | _Qt.WindowStaysOnTopHint)
            self.setWindowIcon(QIcon(_ico))
            self.resize(960, 540)
            self._v = 0
            self._hidden = []
            self._t = QTimer(self)
            self._t.timeout.connect(self._tick)
            self._t.start(12)
        def _tick(self):
            self._v = min(100, self._v + 4)
            self.update()
            if self._v >= 100:
                self._t.stop()
                for _w in self._hidden:
                    try: _w.show()
                    except Exception: pass
                self.close()
        def paintEvent(self, e):
            p = QPainter(self)
            if _os.path.isfile(_pm):
                pm = QPixmap(_pm).scaled(self.size(), _Qt.IgnoreAspectRatio, _Qt.SmoothTransformation)
                p.drawPixmap(0, 0, pm)
            else:
                p.fillRect(self.rect(), QColor(20, 22, 28))
            y = self.height() - 6
            p.fillRect(0, y, self.width(), 6, QColor(48, 54, 62))
            p.fillRect(0, y, int(self.width() * self._v / 100.0), 6, QColor(255, 255, 255))
            p.end()
    window = MainWindow()
    window.show()
    try:
        app.processEvents()
    except Exception:
        pass
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass

    pass  # autoboot



    rc = app.exec()
    sys.exit(rc)


if __name__ == "__main__":
    main()
