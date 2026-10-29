import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import base64
import os
import re
import sys
from openai import OpenAI

DEFAULT_HISTORY_ROUNDS = 8
INPUT_MIN_H = 44   # 输入框区域最小高度（像素）
CHAT_MIN_H = 80    # 聊天区最小高度（像素）
DEFAULT_SYSTEM_PROMPT = ("你是一位专业的语言学习助手。"
                         "请优先遵循用户在消息中给出的格式要求；"
                         "若用户没有特别要求，则用简洁的中文回答，排版清晰。")

# ---------- 路径处理（兼容 PyInstaller 打包） ----------
def base_dir():
    """配置读写基准目录：打包后为 exe 所在目录，否则为脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative):
    """获取打包后资源的绝对路径（图标等）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


CONFIG_FILE = os.path.join(base_dir(), "config.json")
PROMPTS_FILE = os.path.join(base_dir(), "prompts.json")
SESSIONS_DIR = os.path.join(base_dir(), "sessions")

DEFAULT_CFG = {
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",
    "topmost": False,
    "no_thinking": False,
    "history_rounds": 0,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.3,
    "input_h": None,  # 输入框区域高度（像素），None 表示用默认高度
    "win_x": None,
    "win_y": None,
    "win_w": 760,
    "win_h": 650,
}


# ---------- 配置读写 ----------
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = dict(DEFAULT_CFG)
                cfg.update(data)
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_prompts():
    """加载提示词，兼容旧格式（字符串列表）和新格式（对象列表）。"""
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    result = []
                    for item in data:
                        if isinstance(item, str):
                            text = item.strip()
                            if text:
                                result.append({"text": text, "checked": False})
                        elif isinstance(item, dict):
                            text = str(item.get("text", "")).strip()
                            if text:
                                result.append({
                                    "text": text,
                                    "checked": bool(item.get("checked", False)),
                                })
                    return result
        except Exception:
            pass
    return []


def save_prompts(prompts):
    try:
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- Markdown 解析（只产出 (文本, 标签) 片段，不依赖 Tk） ----------
# 分组顺序：1 行内代码 2 粗斜体 3/4 粗体 5 删除线 6 链接 7/8 斜体
_INLINE_RE = re.compile(
    r'(`[^`\n]+`)'
    r'|(\*\*\*[^*\n]+?\*\*\*)'
    r'|(\*\*(?:[^*\n]|\*(?!\*))+?\*\*)'
    r'|(__[^_\n]+?__)'
    r'|(~~[^~\n]+?~~)'
    r'|(\[[^\]\n]+\]\([^)\s]+\))'
    r'|(\*[^*\s][^*\n]*?\*)'
    r'|((?<!\w)_[^_\s][^_\n]*?_(?!\w))'
)
_HR_RE = re.compile(r'^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$')
_HEAD_RE = re.compile(r'^\s{0,3}(#{1,6})\s+(.+?)\s*$')
_QUOTE_RE = re.compile(r'^\s{0,3}>\s?(.*)$')
_UL_RE = re.compile(r'^(\s*)[-*+]\s+(.*)$')
_OL_RE = re.compile(r'^(\s*)(\d+)[.)]\s+(.*)$')
_TABLE_SEP_RE = re.compile(r'^:?-+:?$')


def _md_add(tags, new):
    """给标签元组追加样式；粗体与斜体叠加时换成粗斜体。"""
    if new in tags:
        return tags
    if new == "md_italic" and "md_bold" in tags:
        return tuple(t for t in tags if t != "md_bold") + ("md_bi",)
    if new == "md_bold" and "md_italic" in tags:
        return tuple(t for t in tags if t != "md_italic") + ("md_bi",)
    return tags + (new,)


def _md_inline(text, tags=()):
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], tags))
        g = m.lastindex
        s = m.group(g)
        if g == 1:
            out.append((s[1:-1], tags + ("md_code",)))
        elif g == 2:
            out.extend(_md_inline(s[3:-3], _md_add(_md_add(tags, "md_bold"), "md_italic")))
        elif g in (3, 4):
            out.extend(_md_inline(s[2:-2], _md_add(tags, "md_bold")))
        elif g == 5:
            out.extend(_md_inline(s[2:-2], tags + ("md_strike",)))
        elif g == 6:
            label, url = s[1:].split("](", 1)
            out.append((label, tags + ("md_link",)))
            out.append((" (" + url[:-1] + ")", tags + ("md_url",)))
        else:
            out.extend(_md_inline(s[1:-1], _md_add(tags, "md_italic")))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], tags))
    return out


_TABLE_PAD = 28  # 表格列间距（像素）


def _default_measure(text, bold=False):
    """没有 Tk 字体可测量时的估算：中日韩字符约两倍宽。"""
    return sum(14 if ord(ch) > 0x2E7F else 7 for ch in text)


def _is_table_line(line):
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _md_table(block, measure, tables):
    """把一整块表格行转成带制表位的行。

    每列宽度 = 该列最宽单元格（像素）+ 间距；单元格之间用 \\t 分隔，
    制表位位置写入 tables[表格编号]，对应标签名为 "tbl<编号>"。
    """
    measure = measure or _default_measure
    parsed = [[c.strip() for c in ln.strip("|").split("|")] for ln in block]

    def is_sep(cells):
        return all(_TABLE_SEP_RE.match(c) for c in cells)

    header = len(parsed) > 1 and is_sep(parsed[1])
    ncols = max(len(cells) for cells in parsed if not is_sep(cells)) \
        if any(not is_sep(c) for c in parsed) else 1
    widths = [0] * ncols
    for r, cells in enumerate(parsed):
        if is_sep(cells):
            continue
        for j, c in enumerate(cells):
            plain = "".join(t for t, _ in _md_inline(c))
            widths[j] = max(widths[j], measure(plain, bold=(header and r == 0)))

    tabs, acc = [], 0
    for j in range(ncols - 1):
        acc += widths[j] + _TABLE_PAD
        tabs.append(acc)
    total = acc + widths[-1]
    tid = len(tables)
    tables[tid] = tabs
    tag = "tbl%d" % tid
    base = ("md_table", tag)

    out = []
    for r, cells in enumerate(parsed):
        if is_sep(cells):
            n = max(int(total // max(measure("─"), 1)), 3)
            out.append(([("─" * n, ("md_table", "md_hr"))], "table"))
            continue
        tags = _md_add(base, "md_bold") if header and r == 0 else base
        segs = []
        for j, c in enumerate(cells):
            if j:
                segs.append(("\t", base))
            segs.extend(_md_inline(c, tags))
        out.append((segs, "table"))
    return out


def md_parse(raw, measure=None, tables=None, blocks=None):
    """把 Markdown 文本解析成 [(文本, 标签元组), ...]。

    支持：标题、粗体/斜体/删除线/行内代码、代码块、有序/无序列表、
    引用、分隔线、链接、表格（按列宽用制表位对齐）。

    measure(text, bold=False) 返回文本像素宽度，用于计算表格列宽；
    tables 是调用方传入的字典，表格的制表位位置会写进去：{编号: [x1, x2, ...]}。
    """
    if tables is None:
        tables = {}
    if blocks is None:
        blocks = []  # 代码块列表：[{"lang": 语言, "lines": [原始代码行]}, ...]
    lines = raw.replace("\r\n", "\n").strip("\n").split("\n")
    rows = []  # [(片段列表, 类型)]
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code = not in_code
            if in_code:
                # 代码块上方留一个空位，渲染时放"复制"按钮；标签 md_cb:N 对应 blocks[N]
                parts = stripped[3:].strip().split()
                blocks.append({"lang": parts[0] if parts else "", "lines": []})
                rows.append(([("", ("md_codehead", "md_cb:%d" % (len(blocks) - 1)))],
                             "codehead"))
            i += 1
            continue
        if in_code:
            blocks[-1]["lines"].append(line)
            rows.append(([(line or " ", ("md_codeblock",))], "code"))
            i += 1
            continue

        if _HR_RE.match(line):
            rows.append(([("─" * 30, ("md_hr",))], "hr"))
        elif _HEAD_RE.match(line):
            m = _HEAD_RE.match(line)
            tag = "md_h%d" % min(len(m.group(1)), 3)
            rows.append((_md_inline(m.group(2), (tag,)), "h"))
        elif stripped.startswith("|") and stripped.count("|") >= 2:
            block = []
            while i < len(lines) and _is_table_line(lines[i]):
                block.append(lines[i].strip())
                i += 1
            rows.extend(_md_table(block, measure, tables))
            continue
        elif _QUOTE_RE.match(line):
            rows.append((_md_inline(_QUOTE_RE.match(line).group(1), ("md_quote",)), "quote"))
        elif _UL_RE.match(line) or _OL_RE.match(line):
            m = _UL_RE.match(line)
            if m:
                indent, content, mark = m.group(1), m.group(2), None
            else:
                m = _OL_RE.match(line)
                indent, content, mark = m.group(1), m.group(3), m.group(2) + ". "
            nested = len(indent.expandtabs(4)) >= 2
            tag = "md_li2" if nested else "md_li"
            if mark is None:
                mark = "◦ " if nested else "• "
            rows.append(([(mark, (tag,))] + _md_inline(content, (tag,)), "li"))
        else:
            rows.append((_md_inline(line), "p"))
        i += 1

    segs = []
    for idx, (row, kind) in enumerate(rows):
        if idx:
            # 相邻代码块行的换行也带底色，背景才连续
            same = kind == "code" and rows[idx - 1][1] == "code"
            segs.append(("\n", ("md_codeblock",) if same else ()))
        segs.extend(row)
    return segs


# ---------- 文本文件读取（输入里写 "D:\路径\文件.txt" 即读取） ----------
MAX_FILE_BYTES = 1024 * 1024        # 单个文件上限
WARN_TOTAL_CHARS = 100000           # 一次发送的文件总字符数超过此值时先确认
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".srt", ".vtt", ".ass",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java", ".kt", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".lua",
    ".sh", ".bat", ".cmd", ".ps1", ".sql", ".html", ".htm", ".css", ".scss",
}
SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519", "id_ecdsa"}
SENSITIVE_EXTS = {".pem", ".key", ".pfx", ".p12"}
_FILE_REF_RE = re.compile(r'"([A-Za-z]:[\\/][^"\r\n]*)"')


def find_file_refs(text):
    """找出文字里带英文引号的 Windows 路径，按出现顺序去重。"""
    seen, result = set(), []
    for m in _FILE_REF_RE.finditer(text):
        p = m.group(1).strip()
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def is_sensitive_file(path):
    name = os.path.basename(path).lower()
    ext = os.path.splitext(name)[1]
    if name in SENSITIVE_NAMES or name.startswith(".env.") or ext in SENSITIVE_EXTS:
        return True
    try:
        return os.path.normcase(os.path.abspath(path)) == \
            os.path.normcase(os.path.abspath(CONFIG_FILE))
    except Exception:
        return False


def read_text_file(path):
    """读取文本文件，返回 (内容, 错误信息)；成功时错误信息为 None。"""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if ext not in TEXT_EXTS and not is_sensitive_file(path):
        return None, f"不支持的文件类型 {ext or '(无扩展名)'}，只支持文本和代码文件"
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            return None, f"文件过大（{-(-size // 1024)} KB），上限 {MAX_FILE_BYTES // 1024} KB"
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        return None, f"读取失败：{e}"
    if b"\x00" in data[:8192]:
        return None, "看起来是二进制文件，不是文本"
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc), None
        except UnicodeDecodeError:
            continue
    return None, "无法识别编码（已尝试 UTF-8、GBK）"


# ---------- 图片读取（输入里写 "D:\路径\截图.png" 即作为图片发送） ----------
# 限制依据 DeepSeek 图像理解文档：单张 32 MiB、请求体 48 MiB（base64 会膨胀约 1/3），
# 这里按原始字节留出余量
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024        # 单张图片原始大小上限
MAX_IMAGES_TOTAL_BYTES = 30 * 1024 * 1024  # 一次发送的图片原始大小总上限


def sniff_image_mime(data):
    """按文件头判断图片格式（服务商也是按实际内容判断，不看扩展名）。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_image_file(path):
    """读取图片，返回 ({"mime", "b64", "bytes"}, 错误信息)；成功时错误信息为 None。"""
    try:
        size = os.path.getsize(path)
        if size > MAX_IMAGE_BYTES:
            return None, f"图片过大（{-(-size // 1048576)} MB），单张上限 {MAX_IMAGE_BYTES // 1048576} MB"
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        return None, f"读取失败：{e}"
    mime = sniff_image_mime(data)
    if not mime:
        return None, "文件内容不是支持的图片（只支持 JPEG、PNG、GIF、WebP），可能已损坏或扩展名不对"
    return {"mime": mime, "b64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data)}, None


def describe_file(fi):
    """聊天区灰字里的一行说明；兼容旧会话（只有 chars 字段）。"""
    if fi.get("kind") == "image":
        kb = max(1, round(fi.get("bytes", 0) / 1024))
        return f"[已读取图片：{fi['path']}，{kb} KB]"
    return f"[已读取文件：{fi['path']}，{fi.get('chars', 0)} 字符]"


# ---------- 历史会话读写 ----------
def save_session(session):
    """先写临时文件再替换，避免写到一半崩溃留下半截 JSON。"""
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        path = os.path.join(SESSIONS_DIR, session["id"] + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print("保存会话失败:", e)


def load_session(sid):
    try:
        with open(os.path.join(SESSIONS_DIR, sid + ".json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data
    except Exception:
        pass
    return None


def list_sessions():
    """返回按时间倒序的会话摘要列表。"""
    result = []
    if not os.path.isdir(SESSIONS_DIR):
        return result
    for name in sorted(os.listdir(SESSIONS_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        data = load_session(name[:-5])
        if data:
            result.append({
                "id": name[:-5],
                "title": data.get("title", ""),
                "updated": data.get("updated", ""),
                "rounds": len(data["messages"]) // 2,
            })
    return result


def delete_session(sid):
    try:
        os.remove(os.path.join(SESSIONS_DIR, sid + ".json"))
    except Exception:
        pass


class LangLearnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 语言学习助手 V0.1.3")
        self.root.minsize(320, 200)

        self.cfg = load_config()
        self.client = None
        self.history = []
        self.prompts = load_prompts()
        self.session = None  # 当前会话，首次回答完成时创建
        self.busy = False
        self.stop_event = threading.Event()
        self._stream = None
        self._ans_n = 0  # 回答片段计数，用于"复制整条回答"
        self._ans_raw = {}  # 回答标签 -> 原始 Markdown 文本（复制时用）
        self._tbl_n = 0  # 表格标签计数，保证每张表的制表位标签唯一

        # 启动时先设为全透明，等位置和布局都摆好再恢复不透明，避免窗口先出现在
        # 系统默认位置再跳走。不用 withdraw：隐藏状态下 Tk 不做布局，分隔条放不准
        self.root.attributes("-alpha", 0.0)
        self.root.attributes("-topmost", bool(self.cfg.get("topmost", False)))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._init_client()

        self._set_icon(self.root)
        self.root.after(10, self._startup_layout)

    # ================= 图标 =================
    def _set_icon(self, win):
        try:
            icon_path = resource_path("WINAPI.ico")
            if os.path.exists(icon_path):
                win.iconbitmap(icon_path)
        except Exception:
            pass

    # ================= 输入框 / 聊天区高度分配 =================
    def _startup_layout(self):
        try:
            self._restore_geometry()
            self.root.update_idletasks()  # 先让窗口尺寸生效，再摆分隔条
            self._input_default_h = self.input_frame.winfo_reqheight()
            self._restore_sash()
        finally:
            # 无论上面是否出错都要恢复不透明，否则窗口会一直看不见
            self.root.attributes("-alpha", 1.0)

    def _sash_y(self):
        try:
            return self.paned.sash_coord(0)[1]
        except tk.TclError:
            return None

    def _place_sash(self, input_h):
        """把输入框区域高度设为 input_h 像素，夹在合法范围内。"""
        total = self.paned.winfo_height()
        if total <= 1:
            return
        sash_w = int(self.paned.cget("sashwidth"))
        input_h = max(INPUT_MIN_H, min(int(input_h), total - CHAT_MIN_H - sash_w))
        self.paned.sash_place(0, 0, input_h)

    def _restore_sash(self):
        saved = self.cfg.get("input_h")
        if isinstance(saved, (int, float)) and saved > 0:
            self._place_sash(saved)

    def _store_input_h(self):
        """把当前输入框高度写入配置；与默认高度一致时存 None（表示跟随默认）。"""
        y = self._sash_y()
        if y is None or self._input_default_h is None:
            return
        self.cfg["input_h"] = None if abs(y - self._input_default_h) <= 2 else int(y)

    def _on_sash_release(self, event):
        # 只有在分隔条上松开鼠标才需要记录
        if self.paned.identify(event.x, event.y):
            self._store_input_h()

    def _on_sash_double(self, event):
        if not self.paned.identify(event.x, event.y):
            return
        if self._input_default_h is not None:
            self._place_sash(self._input_default_h)
            self._store_input_h()
            self.status.config(text="已恢复默认输入框高度")

    # ================= 窗口几何 =================
    def _restore_geometry(self):
        w = self.cfg.get("win_w") or 760
        h = self.cfg.get("win_h") or 600
        x = self.cfg.get("win_x")
        y = self.cfg.get("win_y")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        if x is None or y is None:
            self.root.geometry(f"{w}x{h}")
            self._center(w, h)
            return

        visible = (x + w > 0 and x < sw and y + h > 0 and y < sh)
        if not visible:
            self.root.geometry(f"{w}x{h}")
            self._center(w, h)
            return

        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _center(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _save_geometry(self):
        try:
            state = self.root.state()
            if state == "normal":
                self.cfg["win_x"] = self.root.winfo_x()
                self.cfg["win_y"] = self.root.winfo_y()
                self.cfg["win_w"] = self.root.winfo_width()
                self.cfg["win_h"] = self.root.winfo_height()
        except Exception:
            pass

    def _on_close(self):
        self._save_geometry()
        save_config(self.cfg)
        self.root.destroy()

    # ================= 轮数标签 =================
    def _update_rounds_label(self):
        try:
            cur = len(self.history) // 2
            limit = self.cfg.get("history_rounds", DEFAULT_HISTORY_ROUNDS)
            try:
                limit = int(limit)
            except Exception:
                limit = DEFAULT_HISTORY_ROUNDS
            self.rounds_label.config(text=f"{cur} / {limit} 轮")
        except Exception:
            pass

    # ================= UI =================
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x", side="top")

        ttk.Button(top, text="提示词", width=8,
                   command=self._open_prompts).pack(side="left")
        ttk.Button(top, text="设置", width=8,
                   command=self._open_settings).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="清空", width=8,
                   command=self._clear_chat).pack(side="left", padx=(6, 0))
        # 请求进行中，【发送】变成【停止】，【纯发送】置灰
        self.send_btn = ttk.Button(top, text="发送", width=8,
                                   command=self._on_send_click)
        self.send_btn.pack(side="left", padx=(6, 0))
        self.pure_btn = ttk.Button(top, text="纯发送", width=8,
                                   command=lambda: self.send(use_rules=False))
        self.pure_btn.pack(side="left", padx=(6, 0))
        self.root.bind("<Escape>", lambda e: self.stop_generation())

        self.rounds_label = ttk.Label(top, text="0 / 8 轮", foreground="#666666")
        self.rounds_label.pack(side="right")

        # 状态栏在下面、分隔窗口之后才 pack：窗口缩得很矮时，状态栏最先被裁掉，
        # 把空间让给对话区
        self.status = ttk.Label(self.root, text="就绪", anchor="w", relief="sunken")

        # 输入框与聊天区之间是可拖动的分隔条：输入框保持自己的高度，
        # 窗口缩放时多出来或减少的空间全部给聊天区
        self.paned = tk.PanedWindow(self.root, orient="vertical", sashwidth=6,
                                    sashrelief="flat", bd=0, bg="#d5d9df",
                                    opaqueresize=True)
        self.paned.pack(fill="both", expand=True, side="top")
        self.status.pack(fill="x", side="bottom")  # 必须在 paned 之后，见上

        input_frame = ttk.Frame(self.paned, padding=(8, 0, 8, 6))
        self.input_frame = input_frame

        self.input_box = tk.Text(input_frame, height=2, wrap="word",
                                 font=("微软雅黑", 11), undo=True)
        input_scroll = ttk.Scrollbar(input_frame, orient="vertical",
                                     command=self.input_box.yview)
        self.input_box.configure(yscrollcommand=input_scroll.set)

        self.input_box.pack(side="left", fill="both", expand=True)
        input_scroll.pack(side="right", fill="y")
        self.input_box.bind("<Control-Return>", self._on_send_key)

        chat_frame = ttk.Frame(self.paned, padding=(8, 0, 8, 8))

        self.paned.add(input_frame, minsize=INPUT_MIN_H, stretch="never")
        self.paned.add(chat_frame, minsize=CHAT_MIN_H, stretch="always")
        self.paned.bind("<ButtonRelease-1>", self._on_sash_release)
        self.paned.bind("<Double-Button-1>", self._on_sash_double)
        self._input_default_h = None  # 启动布局完成后记录，用于双击还原

        self.chat_area = scrolledtext.ScrolledText(
            chat_frame, wrap="word", font=("微软雅黑", 11), state="disabled")
        self.chat_area.pack(fill="both", expand=True)
        self.chat_area.tag_config("user", foreground="#0066cc",
                                  font=("微软雅黑", 11, "bold"))
        self.chat_area.tag_config("ai", foreground="#222222")
        self.chat_area.tag_config("sys", foreground="#999999",
                                  font=("微软雅黑", 9, "italic"))
        self._config_markdown_tags()

        self._build_chat_menu()
        self._update_rounds_label()

    # ================= Markdown 渲染 =================
    def _config_markdown_tags(self):
        c = self.chat_area
        f = "微软雅黑"
        mono = ("Consolas", 10)
        c.tag_config("md_bold", font=(f, 11, "bold"))
        c.tag_config("md_italic", font=(f, 11, "italic"))
        c.tag_config("md_bi", font=(f, 11, "bold italic"))
        c.tag_config("md_strike", overstrike=True)
        c.tag_config("md_code", font=mono, background="#eef0f3", foreground="#c0392b")
        c.tag_config("md_codeblock", font=mono, background="#f4f5f7",
                     foreground="#222222", lmargin1=8, lmargin2=8)
        c.tag_config("md_h1", font=(f, 15, "bold"), foreground="#1e3c72", spacing1=6)
        c.tag_config("md_h2", font=(f, 13, "bold"), foreground="#1e3c72", spacing1=4)
        c.tag_config("md_h3", font=(f, 12, "bold"), foreground="#2a5298", spacing1=2)
        c.tag_config("md_quote", foreground="#666666", lmargin1=14, lmargin2=14)
        c.tag_config("md_li", lmargin1=12, lmargin2=26)
        c.tag_config("md_li2", lmargin1=32, lmargin2=46)
        c.tag_config("md_hr", foreground="#bbbbbb")
        c.tag_config("md_table", font=(f, 11))
        # 用于测量表格列宽，字体要和显示一致
        self._md_font = tkfont.Font(root=self.root, family=f, size=11)
        self._md_font_b = tkfont.Font(root=self.root, family=f, size=11, weight="bold")
        c.tag_config("md_link", foreground="#0066cc", underline=True)
        c.tag_config("md_url", foreground="#999999", font=(f, 9))
        c.tag_raise("sel")  # 保证选中高亮盖过代码底色

    def _render_answer(self, tag):
        """把 tag 对应的纯文本回答替换成 Markdown 渲染结果。调用时 chat_area 须为 normal 状态。"""
        raw = self._ans_raw.get(tag)
        if not raw:
            return
        ranges = self.chat_area.tag_ranges(tag)
        if not ranges:
            return
        def measure(text, bold=False):
            return (self._md_font_b if bold else self._md_font).measure(text)

        tables, blocks = {}, []
        try:
            segs = md_parse(raw, measure, tables, blocks)
        except Exception:
            return  # 解析失败就保留纯文本
        # 解析里的表格编号从 0 开始，这里换成全局唯一的标签名
        remap = {}
        for local_id, tabs in tables.items():
            self._tbl_n += 1
            remap["tbl%d" % local_id] = "gtbl%d" % self._tbl_n
            self.chat_area.tag_config("gtbl%d" % self._tbl_n,
                                      tabs=tuple(tabs), tabstyle="tabular")
        if remap:
            segs = [(t, tuple(remap.get(g, g) for g in gs)) for t, gs in segs]
        start, end = str(ranges[0]), str(ranges[-1])
        self.chat_area.delete(start, end)
        self.chat_area.mark_set("md_ins", start)
        for text, tags in segs:
            cb = next((g for g in tags if g.startswith("md_cb:")), None)
            if cb is not None:
                # 代码块头部：放一个右对齐的"复制"按钮，不写入任何文字，
                # 所以选中复制、复制全部对话都不会带上按钮文字
                blk = blocks[int(cb.split(":")[1])]
                self.chat_area.window_create(
                    "md_ins", window=self._make_copy_btn(blk),
                    padx=2, pady=1, align="center")
                self.chat_area.insert("md_ins", "", ("ai", tag) + tuple(
                    g for g in tags if g != cb))
                continue
            self.chat_area.insert("md_ins", text, ("ai", tag) + tuple(tags))
        self.chat_area.mark_unset("md_ins")

    def _make_copy_btn(self, blk):
        """生成一个代码块的"复制"按钮；点击后复制该块原文，按钮短暂显示"已复制"。"""
        # 按钮文字统一为"复制"：语言标记来自模型回答，可能标错，不放在按钮上
        idle = "复制"
        btn = tk.Button(self.chat_area, text=idle, font=("微软雅黑", 8), relief="flat",
                        bg="#e4e7ec", activebackground="#cfd5de", fg="#333333",
                        bd=0, padx=8, pady=0, cursor="hand2")

        def do_copy():
            code = "\n".join(blk["lines"])
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.status.config(text="已复制代码块")
            btn.config(text="已复制 ✓")
            btn.after(1500, lambda: btn.winfo_exists() and btn.config(text=idle))

        btn.config(command=do_copy)
        return btn

    def _finish_render(self, tag):
        """流式结束后在主线程渲染。"""
        self.chat_area.config(state="normal")
        try:
            self._render_answer(tag)
            self.chat_area.see("end")
        finally:
            self.chat_area.config(state="disabled")

    # ================= 聊天区右键：复制 =================
    def _build_chat_menu(self):
        self._chat_menu = tk.Menu(self.root, tearoff=0)
        self._chat_menu.add_command(label="复制选中", command=self._copy_selection)
        self._chat_menu.add_command(label="复制整条回答", command=self._copy_answer)
        self._chat_menu.add_command(label="复制全部对话", command=self._copy_all)
        self._menu_index = "1.0"
        self.chat_area.bind("<Button-3>", self._on_chat_right_click)

    def _on_chat_right_click(self, event):
        self._menu_index = self.chat_area.index(f"@{event.x},{event.y}")
        has_sel = bool(self.chat_area.tag_ranges("sel"))
        has_ans = any(t.startswith("ans") for t in self.chat_area.tag_names(self._menu_index))
        self._chat_menu.entryconfig(0, state="normal" if has_sel else "disabled")
        self._chat_menu.entryconfig(1, state="normal" if has_ans else "disabled")
        try:
            self._chat_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._chat_menu.grab_release()

    def _to_clipboard(self, text, done):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.config(text=done)

    def _copy_selection(self):
        try:
            self._to_clipboard(self.chat_area.get("sel.first", "sel.last"), "已复制选中内容")
        except tk.TclError:
            pass

    def _copy_answer(self):
        tags = [t for t in self.chat_area.tag_names(self._menu_index) if t.startswith("ans")]
        if not tags:
            return
        raw = self._ans_raw.get(tags[0])
        if raw:  # 复制原始 Markdown，而不是渲染后的显示文本
            self._to_clipboard(raw.strip(), "已复制整条回答")
            return
        ranges = self.chat_area.tag_ranges(tags[0])
        if ranges:
            self._to_clipboard(self.chat_area.get(ranges[0], ranges[-1]).strip(),
                               "已复制整条回答")

    def _copy_all(self):
        self._to_clipboard(self.chat_area.get("1.0", "end").strip(), "已复制全部对话")

    # ================= 事件 =================
    def _on_send_key(self, event):
        self.send()
        return "break"

    def _on_send_click(self):
        if self.busy:
            self.stop_generation()
        else:
            self.send()

    def stop_generation(self):
        """停止当前流式生成（【发送】和【纯发送】发起的请求都适用）。"""
        if not self.busy:
            return
        self.stop_event.set()
        self.status.config(text="正在停止...")
        stream = self._stream
        if stream is not None:
            try:
                stream.close()  # 打断正在阻塞的读取
            except Exception:
                pass

    def _set_busy_ui(self, busy):
        self.send_btn.config(text="停止" if busy else "发送")
        self.pure_btn.config(state="disabled" if busy else "normal")

    def _clear_chat(self):
        if self.busy:
            messagebox.showinfo("提示", "请求进行中，请稍后再清空")
            return
        self.history.clear()
        self._ans_raw.clear()
        self.session = None  # 旧会话已保存在历史里，之后开始新会话
        self.chat_area.config(state="normal")
        self.chat_area.delete("1.0", "end")
        self.chat_area.config(state="disabled")
        self.status.config(text="已清空")
        self._update_rounds_label()

    # ================= 设置弹窗 =================
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        self._set_icon(win)
        win.attributes("-topmost", bool(self.root.attributes("-topmost")))

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="API Key:").grid(row=0, column=0, sticky="e", pady=4)
        api_var = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(frm, textvariable=api_var, width=46, show="*").grid(row=0, column=1, pady=4)

        ttk.Label(frm, text="Base URL:").grid(row=1, column=0, sticky="e", pady=4)
        url_var = tk.StringVar(value=self.cfg.get("base_url", ""))
        ttk.Entry(frm, textvariable=url_var, width=46).grid(row=1, column=1, pady=4)

        ttk.Label(frm, text="模型:").grid(row=2, column=0, sticky="e", pady=4)
        model_var = tk.StringVar(value=self.cfg.get("model", ""))
        ttk.Entry(frm, textvariable=model_var, width=46).grid(row=2, column=1, pady=4)

        topmost_var = tk.BooleanVar(value=bool(self.cfg.get("topmost", False)))
        no_thinking_var = tk.BooleanVar(value=bool(self.cfg.get("no_thinking", False)))
        rounds_var = tk.StringVar(value=str(self.cfg.get("history_rounds", DEFAULT_HISTORY_ROUNDS)))

        ttk.Checkbutton(frm, text="置顶窗口", variable=topmost_var).grid(
            row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(frm, text="关闭思考（快速模式）", variable=no_thinking_var).grid(
            row=4, column=1, sticky="w", pady=(2, 0))

        ttk.Label(frm, text="上下文轮数:").grid(row=5, column=0, sticky="e", pady=(6, 0))
        ttk.Entry(frm, textvariable=rounds_var, width=6).grid(
            row=5, column=1, sticky="w", pady=(6, 0))
        ttk.Label(frm, text="（0=不携带历史聊天记录）", foreground="#888888").grid(
            row=5, column=1, sticky="w", padx=(60, 0), pady=(6, 0))

        ttk.Label(frm, text="系统提示词:").grid(row=6, column=0, sticky="ne", pady=(8, 0))
        sys_box = tk.Text(frm, width=46, height=4, wrap="word", font=("微软雅黑", 10))
        sys_box.grid(row=6, column=1, pady=(8, 0), sticky="w")
        sys_box.insert("1.0", self.cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
        ttk.Label(frm, text="（发送与纯发送共用，留空则不发送系统提示词）",
                  foreground="#888888").grid(row=7, column=1, sticky="w")

        def reset_sys():
            sys_box.delete("1.0", "end")
            sys_box.insert("1.0", DEFAULT_SYSTEM_PROMPT)

        cur_temp = self.cfg.get("temperature", 0.3)
        temp_var = tk.StringVar(value="" if cur_temp is None else str(cur_temp))
        ttk.Label(frm, text="温度:").grid(row=8, column=0, sticky="e", pady=(6, 0))
        ttk.Entry(frm, textvariable=temp_var, width=6).grid(
            row=8, column=1, sticky="w", pady=(6, 0))
        ttk.Label(frm, text="（0~2，留空=使用服务商默认值）", foreground="#888888").grid(
            row=8, column=1, sticky="w", padx=(60, 0), pady=(6, 0))

        status_lbl = ttk.Label(frm, text="", foreground="#666666")
        status_lbl.grid(row=9, column=0, columnspan=2, pady=(8, 0))

        def collect():
            rounds_str = rounds_var.get().strip()
            if not rounds_str.isdigit() or int(rounds_str) < 0:
                messagebox.showinfo("提示", "上下文轮数必须为大于或等于 0 的整数", parent=win)
                return None
            rounds = int(rounds_str)

            temp_str = temp_var.get().strip()
            if temp_str == "":
                temperature = None
            else:
                try:
                    temperature = float(temp_str)
                    if not 0 <= temperature <= 2:
                        raise ValueError
                except ValueError:
                    messagebox.showinfo("提示", "温度必须是 0 到 2 之间的数字，或留空", parent=win)
                    return None

            cfg = dict(self.cfg)
            cfg.update({
                "api_key": api_var.get().strip(),
                "base_url": url_var.get().strip(),
                "model": model_var.get().strip(),
                "topmost": bool(topmost_var.get()),
                "no_thinking": bool(no_thinking_var.get()),
                "history_rounds": rounds,
                "system_prompt": sys_box.get("1.0", "end").strip(),
                "temperature": temperature,
            })
            return cfg

        def apply_topmost():
            flag = bool(topmost_var.get())
            self.root.attributes("-topmost", flag)
            try:
                win.attributes("-topmost", flag)
            except Exception:
                pass

        topmost_var.trace_add("write", lambda *_: apply_topmost())

        def do_save():
            cfg = collect()
            if cfg is None:
                return
            save_config(cfg)
            self.cfg = cfg
            self._init_client()
            apply_topmost()
            self._update_rounds_label()
            status_lbl.config(text="已保存 ✅", foreground="#2a9d2a")

        def do_test():
            cfg = collect()
            if cfg is None:
                return
            status_lbl.config(text="测试中...", foreground="#666666")
            win.update_idletasks()
            ok, msg = self._test_connection(cfg)
            if ok:
                status_lbl.config(text="连接成功 ✅", foreground="#2a9d2a")
            else:
                status_lbl.config(text=f"失败：{msg}", foreground="#cc0000")

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="恢复默认提示词", command=reset_sys).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="测试连接", command=do_test).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="保存", command=do_save).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="left")

    # ================= 提示词（Treeview 版） =================
    def _open_prompts(self):
        win = tk.Toplevel(self.root)
        win.title("提示词")
        win.transient(self.root)
        win.geometry("460x400")
        win.minsize(340, 260)

        self._set_icon(win)
        win.attributes("-topmost", bool(self.root.attributes("-topmost")))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True)

        frm = ttk.Frame(nb, padding=8)
        nb.add(frm, text="提示词")
        hist_frm = ttk.Frame(nb, padding=8)
        nb.add(hist_frm, text="历史会话")

        btns = ttk.Frame(frm)
        btns.pack(side="bottom", fill="x", pady=(8, 0))

        tree_frame = ttk.Frame(frm)
        tree_frame.pack(side="top", fill="both", expand=True)

        columns = ("check", "text")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                            selectmode="extended")
        tree.heading("check", text="")
        tree.heading("text", text="提示词")
        tree.column("check", width=40, anchor="center", stretch=False)
        tree.column("text", width=320, anchor="w", stretch=True)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                                    command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        def refresh_tree():
            # 记录当前选中行，尽量保持
            selected_indices = set()
            for item in tree.selection():
                try:
                    selected_indices.add(tree.index(item))
                except Exception:
                    pass

            for item in tree.get_children():
                tree.delete(item)

            for p in self.prompts:
                mark = "☑" if p.get("checked") else "☐"
                one_line = p["text"].replace("\n", " ")
                display = one_line if len(one_line) <= 40 else one_line[:40] + "…"
                tree.insert("", "end", values=(mark, display))

            # 恢复选中
            children = tree.get_children()
            for idx in selected_indices:
                if 0 <= idx < len(children):
                    tree.selection_add(children[idx])

        def get_selected_index():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选中一条", parent=win)
                return None
            return tree.index(sel[0])

        def get_selected_indices():
            sel = tree.selection()
            return [tree.index(item) for item in sel]

        def do_use():
            idx = get_selected_index()
            if idx is None:
                return
            text = self.prompts[idx]["text"]
            self.input_box.delete("1.0", "end")
            self.input_box.insert("1.0", text)
            self.input_box.focus_set()
            self.status.config(text="已填入提示词")

        def do_new():
            self._edit_prompt(win, None, on_saved=refresh_tree)

        def do_edit_idx(idx):
            self._edit_prompt(win, idx, on_saved=refresh_tree)

        def do_edit():
            idx = get_selected_index()
            if idx is None:
                return
            do_edit_idx(idx)

        def do_delete():
            indices = get_selected_indices()
            if not indices:
                messagebox.showinfo("提示", "请先选中要删除的条目", parent=win)
                return
            if not messagebox.askyesno("确认", f"确定删除选中的 {len(indices)} 条提示词吗？",
                                       parent=win):
                return
            for idx in sorted(indices, reverse=True):
                del self.prompts[idx]
            save_prompts(self.prompts)
            refresh_tree()
            self.status.config(text="已删除")

        def toggle_max_prompts():
            try:
                if win.state() == "zoomed":
                    win.state("normal")
                else:
                    win.state("zoomed")
            except Exception:
                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                if getattr(win, "_is_max", False):
                    win.geometry("420x360")
                    win._is_max = False
                else:
                    win.geometry(f"{sw}x{sh}+0+0")
                    win._is_max = True

        def on_tree_click(event):
            region = tree.identify("region", event.x, event.y)
            if region != "cell":
                return
            col = tree.identify_column(event.x)
            row = tree.identify_row(event.y)
            if not row:
                return
            if col == "#1":  # check 列
                idx = tree.index(row)
                self.prompts[idx]["checked"] = not self.prompts[idx].get("checked", False)
                save_prompts(self.prompts)
                # 只更新该行，避免整体刷新导致闪烁
                mark = "☑" if self.prompts[idx]["checked"] else "☐"
                one_line = self.prompts[idx]["text"].replace("\n", " ")
                display = one_line if len(one_line) <= 40 else one_line[:40] + "…"
                tree.item(row, values=(mark, display))
                # 同时选中该行
                tree.selection_set(row)
                tree.focus(row)
                return "break"

        def on_space(event):
            sel = tree.selection()
            if not sel:
                return "break"
            for row in sel:
                idx = tree.index(row)
                self.prompts[idx]["checked"] = not self.prompts[idx].get("checked", False)
            save_prompts(self.prompts)
            for row in sel:
                idx = tree.index(row)
                mark = "☑" if self.prompts[idx]["checked"] else "☐"
                one_line = self.prompts[idx]["text"].replace("\n", " ")
                display = one_line if len(one_line) <= 40 else one_line[:40] + "…"
                tree.item(row, values=(mark, display))
            return "break"

        def on_ctrl_a(event):
            tree.selection_set(tree.get_children())
            return "break"

        def on_double_click(event):
            col = tree.identify_column(event.x)
            if col == "#1":
                return
            row = tree.identify_row(event.y)
            if not row:
                return
            idx = tree.index(row)
            do_edit_idx(idx)

        def on_delete_key(event):
            do_delete()
            return "break"

        def on_right_click(event):
            row = tree.identify_row(event.y)
            if not row:
                return  # 空白处不弹菜单
            # 点在已选中的行上时保留多选，否则才切换选中
            if row not in tree.selection():
                tree.selection_set(row)
            tree.focus(row)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-1>", on_tree_click)
        tree.bind("<space>", on_space)
        tree.bind("<Control-a>", on_ctrl_a)
        tree.bind("<Double-Button-1>", on_double_click)
        tree.bind("<Delete>", on_delete_key)
        tree.bind("<Button-3>", on_right_click)

        menu = tk.Menu(win, tearoff=0)
        menu.add_command(label="使用", command=do_use)
        menu.add_command(label="编辑", command=do_edit)
        menu.add_command(label="删除", command=do_delete)

        ttk.Button(btns, text="全屏", command=toggle_max_prompts).pack(side="left")
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="删除", command=do_delete).pack(side="right", padx=(0, 6))
        ttk.Button(btns, text="新增", command=do_new).pack(side="right", padx=(0, 6))

        refresh_tree()
        self._build_history_tab(win, hist_frm, nb)

    def _build_history_tab(self, win, frm, nb):
        btns = ttk.Frame(frm)
        btns.pack(side="bottom", fill="x", pady=(8, 0))

        tree_frame = ttk.Frame(frm)
        tree_frame.pack(side="top", fill="both", expand=True)

        tree = ttk.Treeview(tree_frame, columns=("time", "title", "rounds"),
                            show="headings", selectmode="extended")
        tree.heading("time", text="时间")
        tree.heading("title", text="标题")
        tree.heading("rounds", text="轮数")
        tree.column("time", width=130, anchor="w", stretch=False)
        tree.column("title", width=200, anchor="w", stretch=True)
        tree.column("rounds", width=50, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def refresh():
            for item in tree.get_children():
                tree.delete(item)
            # iid 用会话 id，方便直接取回
            for s in list_sessions():
                tree.insert("", "end", iid=s["id"],
                            values=(s["updated"], s["title"], s["rounds"]))

        def do_load(event=None):
            sel = tree.selection()
            if not sel:
                if event is None:
                    messagebox.showinfo("提示", "请先选中一条", parent=win)
                return
            self._load_into_chat(sel[0])

        def do_export():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选中一条", parent=win)
                return
            self._export_session_md(sel[0], win)

        def do_delete(event=None):
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选中要删除的会话", parent=win)
                return "break"
            if not messagebox.askyesno("确认", f"确定删除选中的 {len(sel)} 个会话吗？",
                                       parent=win):
                return "break"
            for sid in sel:
                delete_session(sid)
                # 删除的是当前会话时，下一轮另起新会话，避免重新写回旧文件
                if self.session and self.session["id"] == sid:
                    self.session = None
            refresh()
            self.status.config(text="已删除会话")
            return "break"

        menu = tk.Menu(win, tearoff=0)
        menu.add_command(label="载入", command=do_load)
        menu.add_command(label="导出", command=do_export)
        menu.add_command(label="删除", command=do_delete)

        def on_right_click(event):
            row = tree.identify_row(event.y)
            if not row:
                return  # 空白处不弹菜单
            # 点在已选中的行上时保留多选，否则才切换选中
            if row not in tree.selection():
                tree.selection_set(row)
            tree.focus(row)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Double-Button-1>", do_load)
        tree.bind("<Delete>", do_delete)
        tree.bind("<Button-3>", on_right_click)

        ttk.Button(btns, text="刷新", command=refresh).pack(side="left")
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="删除", command=do_delete).pack(side="right", padx=(0, 6))
        ttk.Button(btns, text="导出", command=do_export).pack(side="right", padx=(0, 6))
        ttk.Button(btns, text="载入", command=do_load).pack(side="right", padx=(0, 6))

        # 切到该标签页时刷新列表
        nb.bind("<<NotebookTabChanged>>",
                lambda e: refresh() if nb.index("current") == 1 else None)
        refresh()

    def _edit_prompt(self, parent, index, on_saved):
        edit_win = tk.Toplevel(parent)
        edit_win.title("新增提示词" if index is None else "编辑提示词")
        edit_win.transient(parent)
        edit_win.grab_set()
        edit_win.geometry("420x240")
        edit_win.minsize(300, 180)

        self._set_icon(edit_win)

        frm = ttk.Frame(edit_win, padding=10)
        frm.pack(fill="both", expand=True)

        btns = ttk.Frame(frm)
        btns.pack(side="bottom", fill="x", pady=(8, 0))

        text_frame = ttk.Frame(frm)
        text_frame.pack(side="top", fill="both", expand=True)

        text = tk.Text(text_frame, wrap="word", font=("微软雅黑", 11), undo=True)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)

        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if index is not None:
            text.insert("1.0", self.prompts[index]["text"])
        text.focus_set()

        def toggle_max():
            try:
                if edit_win.state() == "zoomed":
                    edit_win.state("normal")
                else:
                    edit_win.state("zoomed")
            except Exception:
                sw = edit_win.winfo_screenwidth()
                sh = edit_win.winfo_screenheight()
                if getattr(edit_win, "_is_max", False):
                    edit_win.geometry("420x240")
                    edit_win._is_max = False
                else:
                    edit_win.geometry(f"{sw}x{sh}+0+0")
                    edit_win._is_max = True

        ttk.Button(btns, text="全屏", command=toggle_max).pack(side="left")

        def do_save():
            content = text.get("1.0", "end").strip()
            if not content:
                messagebox.showinfo("提示", "内容不能为空", parent=edit_win)
                return
            if index is None:
                self.prompts.append({"text": content, "checked": False})
            else:
                self.prompts[index]["text"] = content
            save_prompts(self.prompts)
            on_saved()
            self.status.config(text="已保存提示词")
            edit_win.destroy()

        ttk.Button(btns, text="保存", command=do_save).pack(side="right")
        ttk.Button(btns, text="取消",
                   command=edit_win.destroy).pack(side="right", padx=(0, 6))

    # ================= 客户端 / 测试 =================
    def _init_client(self):
        key = self.cfg.get("api_key", "").strip()
        if not key:
            self.client = None
            return
        try:
            self.client = OpenAI(api_key=key,
                                 base_url=self.cfg.get("base_url") or None)
        except Exception as e:
            self.client = None
            self.status.config(text=f"客户端初始化失败: {e}")

    def _build_extra_body(self, cfg):
        if cfg.get("no_thinking", False):
            return {"thinking": {"type": "disabled"}}
        return None

    def _test_connection(self, cfg):
        key = cfg.get("api_key", "").strip()
        if not key:
            return False, "API Key 为空"
        try:
            client = OpenAI(api_key=key, base_url=cfg.get("base_url") or None)
            kwargs = dict(
                model=cfg.get("model") or "deepseek-flash",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            eb = self._build_extra_body(cfg)
            if eb:
                kwargs["extra_body"] = eb
            resp = client.chat.completions.create(**kwargs)
            _ = resp.choices[0].message.content
            return True, "ok"
        except Exception as e:
            return False, str(e)[:120]

    # ================= 对话 =================
    def _append(self, who, text):
        self.chat_area.config(state="normal")
        if who == "user":
            self.chat_area.insert("end", "\n【你】\n", "user")
        elif who == "ai":
            self.chat_area.insert("end", "\n【AI】\n", "ai")
            self._ans_n += 1
            tag = f"ans{self._ans_n}"
            self._ans_raw[tag] = text
            self.chat_area.insert("end", text, ("ai", tag))
            self._render_answer(tag)
            self.chat_area.insert("end", "\n")
            self.chat_area.see("end")
            self.chat_area.config(state="disabled")
            return
        else:
            self.chat_area.insert("end", f"\n{text}\n", "sys")
        self.chat_area.insert("end", text + "\n")
        self.chat_area.see("end")
        self.chat_area.config(state="disabled")

    def _append_sys(self, text):
        self.chat_area.config(state="normal")
        self.chat_area.insert("end", f"\n{text}\n", "sys")
        self.chat_area.see("end")
        self.chat_area.config(state="disabled")

    def send(self, use_rules=True):
        if self.busy:
            self.status.config(text="请求进行中，请稍候")
            return
        if not self.client:
            messagebox.showwarning("提示", "请先在【设置】里填写 API Key 并保存")
            return
        text = self.input_box.get("1.0", "end").strip()
        if not text:
            return

        # 读取输入里带引号的文件路径；任何一个读不了就整个取消，输入框内容保留
        files, notes = self._collect_files(text)
        if files is None:
            return
        body = text
        for f in files:
            if f["kind"] == "text":
                body += f"\n\n【文件：{f['path']}】\n```\n{f['content']}\n```"
        images = [f for f in files if f["kind"] == "image"]

        self.input_box.delete("1.0", "end")

        # 收集勾选的规则（纯发送时忽略）
        if use_rules:
            selected = [p["text"] for p in self.prompts if p.get("checked")]
        else:
            selected = []

        if selected:
            rules = "\n\n".join(selected)
            full_text = f"{rules}\n\n【要处理的内容】\n{body}"
        else:
            full_text = body
        # 会话里只记路径和大小：文本记字符数，图片记字节数，不存图片内容本身
        file_info = [
            {"path": f["path"], "kind": "image", "bytes": f["bytes"]} if f["kind"] == "image"
            else {"path": f["path"], "kind": "text", "chars": len(f["content"])}
            for f in files]

        try:
            log_path = os.path.join(base_dir(), "send_log.txt")
            if os.path.exists(log_path) and os.path.getsize(log_path) > 1024 * 1024:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
                f.write(f"附加规则数：{len(selected)}\n")
                for im in images:  # 只记路径和大小，不写 base64
                    f.write(f"附带图片：{im['path']}（{im['bytes']} 字节）\n")
                f.write("-" * 60 + "\n")
                f.write(full_text + "\n")
        except Exception as e:
            print("写日志失败:", e)

        # 聊天区显示原始输入
        self._append("user", text)
        if selected:
            self._append_sys(f"[已附加 {len(selected)} 条规则]")
        for fi in file_info:
            self._append_sys(describe_file(fi))
        for n in notes:
            self._append_sys(n)

        system = str(self.cfg.get("system_prompt", DEFAULT_SYSTEM_PROMPT)).strip()
        messages = [{"role": "system", "content": system}] if system else []

        rounds = self.cfg.get("history_rounds", DEFAULT_HISTORY_ROUNDS)
        try:
            rounds = int(rounds)
        except Exception:
            rounds = DEFAULT_HISTORY_ROUNDS
        if rounds > 0:
            messages.extend(self.history[-rounds * 2:])
        if images:
            # 图片只出现在当前这条 user 消息里（历史里不带图片）；不传 detail，用服务商默认
            parts = [{"type": "text", "text": full_text}]
            parts += [{"type": "image_url",
                       "image_url": {"url": f"data:{im['mime']};base64,{im['b64']}"}}
                      for im in images]
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": "user", "content": full_text})

        self.busy = True
        self.stop_event.clear()
        self._stream = None
        self._set_busy_ui(True)
        self.status.config(text="请求中...（Esc 或【停止】可中断）")
        threading.Thread(target=self._call_api,
                         args=(messages, text, selected, full_text, file_info),
                         daemon=True).start()

    def _collect_files(self, text):
        """解析输入里的文件路径，返回 (文件列表, 提示列表)；需要取消发送时返回 (None, [])。"""
        files, notes = [], []
        for path in find_file_refs(text):
            if not os.path.isfile(path):
                if os.path.isdir(path):
                    messagebox.showwarning("提示", f"这是文件夹，暂不支持：\n{path}")
                    return None, []
                notes.append(f"[路径不存在，按普通文字发送：{path}]")
                continue
            if is_sensitive_file(path) and not messagebox.askyesno(
                    "敏感文件", f"这个文件可能含密钥或账号信息，内容会发送给 API 服务商：\n\n{path}\n\n仍要读取并发送吗？"):
                return None, []
            if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
                img, err = read_image_file(path)
                if err:
                    messagebox.showwarning("无法读取图片", f"{path}\n\n{err}")
                    return None, []
                files.append({"path": path, "kind": "image", **img})
                continue
            content, err = read_text_file(path)
            if err:
                messagebox.showwarning("无法读取文件", f"{path}\n\n{err}")
                return None, []
            files.append({"path": path, "kind": "text", "content": content})
        img_total = sum(f["bytes"] for f in files if f["kind"] == "image")
        if img_total > MAX_IMAGES_TOTAL_BYTES:
            messagebox.showwarning(
                "图片太多", f"这次的图片共 {-(-img_total // 1048576)} MB，"
                f"超过总上限 {MAX_IMAGES_TOTAL_BYTES // 1048576} MB，请减少图片。")
            return None, []
        total = sum(len(f["content"]) for f in files if f["kind"] == "text")
        if total > WARN_TOTAL_CHARS and not messagebox.askyesno(
                "内容较多", f"文件共 {total} 字符，可能超出模型上限或产生较高费用。\n仍要发送吗？"):
            return None, []
        return files, notes

    def _call_api(self, messages, user_text, rule_texts=(), full_text="", files=()):
        try:
            kwargs = dict(
                model=self.cfg.get("model", "deepseek-flash"),
                messages=messages,
                stream=True,
            )
            temp = self.cfg.get("temperature", 0.3)
            if temp is not None:  # 留空表示不传，使用服务商默认值
                kwargs["temperature"] = temp
            eb = self._build_extra_body(self.cfg)
            if eb:
                kwargs["extra_body"] = eb

            stream = self.client.chat.completions.create(**kwargs)
            self._stream = stream

            self._ans_n += 1
            ans_tag = f"ans{self._ans_n}"
            self.chat_area.config(state="normal")
            self.chat_area.insert("end", "\n【AI】\n", "ai")
            self.chat_area.config(state="disabled")

            full = ""
            stopped = False
            try:
                for chunk in stream:
                    if self.stop_event.is_set():
                        stopped = True
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full += delta
                        self.chat_area.config(state="normal")
                        self.chat_area.insert("end", delta, ("ai", ans_tag))
                        self.chat_area.see("end")
                        self.chat_area.config(state="disabled")
            except Exception:
                # 停止时关闭流可能抛异常，属于预期；其他异常照常上报
                if not self.stop_event.is_set():
                    raise
                stopped = True
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
            stopped = stopped or self.stop_event.is_set()

            self.chat_area.config(state="normal")
            self.chat_area.insert("end", "\n")
            if stopped:
                self.chat_area.insert("end", "[已停止]\n", "sys")
            self.chat_area.config(state="disabled")

            if full:
                self._ans_raw[ans_tag] = full
                # 流式阶段是纯文本，结束后在主线程整段替换成渲染结果
                self.root.after(0, lambda t=ans_tag: self._finish_render(t))

            if full or not stopped:
                # history 存原始输入；停止时保留已输出的半截回答
                self.history.append({"role": "user", "content": user_text})
                self.history.append({"role": "assistant", "content": full})
                self.root.after(0, lambda: self._record_round(
                    user_text, full, list(rule_texts), full_text, stopped, list(files)))
            self.status.config(text="已停止" if stopped else "完成")
            self.root.after(0, self._update_rounds_label)
        except Exception as e:
            self._append("sys", f"[错误] {e}")
            self.status.config(text="出错")
        finally:
            self.root.after(0, self._finish_request)

    def _finish_request(self):
        self.busy = False
        self._stream = None
        self._set_busy_ui(False)

    # ================= 历史会话 =================
    def _record_round(self, user_text, answer, rule_texts, full_text, stopped=False,
                      files=None):
        """一轮完成后写入当前会话文件（主线程调用）。

        完整保留：原始输入、规则正文、实际发送内容、AI 回答、所用模型。
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        model = self.cfg.get("model", "")
        if self.session is None:
            sid = time.strftime("%Y-%m-%d_%H-%M-%S")
            title = user_text.replace("\n", " ")[:30]
            self.session = {"id": sid, "title": title, "model": model,
                            "updated": now, "messages": []}
        self.session["messages"].append({
            "role": "user", "content": user_text,
            "rules": len(rule_texts), "rule_texts": rule_texts,
            "sent": full_text, "files": files or [], "time": now})
        reply = {"role": "assistant", "content": answer, "model": model, "time": now}
        if stopped:
            reply["stopped"] = True  # content 保持原样，显示时再补 [已停止]
        self.session["messages"].append(reply)
        self.session["updated"] = now
        save_session(self.session)

    def _load_into_chat(self, sid):
        """载入历史会话：恢复聊天区显示和 history，之后继续追加到该会话。"""
        if self.busy:
            messagebox.showinfo("提示", "请求进行中，请稍后再载入")
            return False
        data = load_session(sid)
        if not data:
            messagebox.showwarning("提示", "会话文件读取失败")
            return False
        self.session = data
        self.history = [{"role": m["role"], "content": m["content"]}
                        for m in data["messages"]
                        if m.get("role") in ("user", "assistant")]
        self.chat_area.config(state="normal")
        self.chat_area.delete("1.0", "end")
        self.chat_area.config(state="disabled")
        self._ans_raw.clear()
        for m in data["messages"]:
            if m["role"] == "user":
                self._append("user", m["content"])
                if m.get("rules"):
                    self._append_sys(f"[已附加 {m['rules']} 条规则]")
                    # 旧会话没有规则正文，只显示条数
                    for i, rt in enumerate(m.get("rule_texts", []), 1):
                        self._append_sys(f"规则 {i}：\n{rt}")
                for fi in m.get("files", []):
                    self._append_sys(describe_file(fi))
            else:
                self._append("ai", m["content"])
                if m.get("stopped"):
                    self._append_sys("[已停止]")
        self._update_rounds_label()
        self.status.config(text=f"已载入会话：{data.get('title', '')}")
        return True

    def _export_session_md(self, sid, parent):
        data = load_session(sid)
        if not data:
            return
        path = filedialog.asksaveasfilename(
            parent=parent, defaultextension=".md", initialfile=sid + ".md",
            filetypes=[("Markdown", "*.md"), ("文本", "*.txt")])
        if not path:
            return
        lines = [f"# {data.get('title', sid)}", ""]
        for m in data["messages"]:
            lines.append("## 你" if m["role"] == "user" else "## AI")
            lines.append("")
            lines.append(m["content"])
            if m.get("stopped"):
                lines.append("")
                lines.append("*[已停止]*")
            lines.append("")
            for i, rt in enumerate(m.get("rule_texts", []), 1):
                lines.append(f"> 规则 {i}：")
                lines.extend("> " + ln for ln in rt.splitlines())
                lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.status.config(text="已导出")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}", parent=parent)


if __name__ == "__main__":
    root = tk.Tk()
    app = LangLearnerApp(root)
    root.mainloop()