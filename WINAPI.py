import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import os
import sys
from openai import OpenAI

DEFAULT_HISTORY_ROUNDS = 8

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

DEFAULT_CFG = {
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",
    "topmost": False,
    "no_thinking": False,
    "history_rounds": 0,
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


class LangLearnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 语言学习助手 V0.1.2")
        self.root.minsize(320, 200)

        self.cfg = load_config()
        self.client = None
        self.history = []
        self.prompts = load_prompts()

        self.root.attributes("-topmost", bool(self.cfg.get("topmost", False)))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._init_client()

        self._set_icon(self.root)
        self.root.after(10, self._restore_geometry)

    # ================= 图标 =================
    def _set_icon(self, win):
        try:
            icon_path = resource_path("WINAPI.ico")
            if os.path.exists(icon_path):
                win.iconbitmap(icon_path)
        except Exception:
            pass

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
        ttk.Button(top, text="发送", width=8,
                   command=self.send).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="纯发送", width=8,
                   command=lambda: self.send(use_rules=False)).pack(side="left", padx=(6, 0))

        self.rounds_label = ttk.Label(top, text="0 / 8 轮", foreground="#666666")
        self.rounds_label.pack(side="right")

        input_frame = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        input_frame.pack(fill="x", side="top")

        self.input_box = tk.Text(input_frame, height=2, wrap="word",
                                 font=("微软雅黑", 11), undo=True)
        input_scroll = ttk.Scrollbar(input_frame, orient="vertical",
                                     command=self.input_box.yview)
        self.input_box.configure(yscrollcommand=input_scroll.set)

        self.input_box.pack(side="left", fill="x", expand=True)
        input_scroll.pack(side="right", fill="y")
        self.input_box.bind("<Control-Return>", self._on_send_key)

        chat_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        chat_frame.pack(fill="both", expand=True, side="top")

        self.chat_area = scrolledtext.ScrolledText(
            chat_frame, wrap="word", font=("微软雅黑", 11), state="disabled")
        self.chat_area.pack(fill="both", expand=True)
        self.chat_area.tag_config("user", foreground="#0066cc",
                                  font=("微软雅黑", 11, "bold"))
        self.chat_area.tag_config("ai", foreground="#222222")
        self.chat_area.tag_config("sys", foreground="#999999",
                                  font=("微软雅黑", 9, "italic"))

        self.status = ttk.Label(self.root, text="就绪", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

        self._update_rounds_label()

    # ================= 事件 =================
    def _on_send_key(self, event):
        self.send()
        return "break"

    def _clear_chat(self):
        self.history.clear()
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

        status_lbl = ttk.Label(frm, text="", foreground="#666666")
        status_lbl.grid(row=6, column=0, columnspan=2, pady=(8, 0))

        def collect():
            rounds_str = rounds_var.get().strip()
            if not rounds_str.isdigit() or int(rounds_str) < 0:
                messagebox.showinfo("提示", "上下文轮数必须为大于或等于 0 的整数", parent=win)
                return None
            rounds = int(rounds_str)

            cfg = dict(self.cfg)
            cfg.update({
                "api_key": api_var.get().strip(),
                "base_url": url_var.get().strip(),
                "model": model_var.get().strip(),
                "topmost": bool(topmost_var.get()),
                "no_thinking": bool(no_thinking_var.get()),
                "history_rounds": rounds,
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
        btns.grid(row=7, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="测试连接", command=do_test).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="保存", command=do_save).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="left")

    # ================= 提示词（Treeview 版） =================
    def _open_prompts(self):
        win = tk.Toplevel(self.root)
        win.title("提示词")
        win.transient(self.root)
        win.geometry("420x360")
        win.minsize(320, 220)

        self._set_icon(win)
        win.attributes("-topmost", bool(self.root.attributes("-topmost")))

        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="both", expand=True)

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
            if row:
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
        if not self.client:
            messagebox.showwarning("提示", "请先在【设置】里填写 API Key 并保存")
            return
        text = self.input_box.get("1.0", "end").strip()
        if not text:
            return
        self.input_box.delete("1.0", "end")

        # 收集勾选的规则（纯发送时忽略）
        if use_rules:
            selected = [p["text"] for p in self.prompts if p.get("checked")]
        else:
            selected = []

        if selected:
            rules = "\n\n".join(selected)
            full_text = f"{rules}\n\n【要处理的内容】\n{text}"
        else:
            full_text = text

        try:
            log_path = os.path.join(base_dir(), "send_log.txt")
            if os.path.exists(log_path) and os.path.getsize(log_path) > 1024 * 1024:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
                f.write(f"附加规则数：{len(selected)}\n")
                f.write("-" * 60 + "\n")
                f.write(full_text + "\n")
        except Exception as e:
            print("写日志失败:", e)

        # 聊天区显示原始输入
        self._append("user", text)
        if selected:
            self._append_sys(f"[已附加 {len(selected)} 条规则]")

        system = ("你是一位专业的语言学习助手。"
                  "请优先遵循用户在消息中给出的格式要求；"
                  "若用户没有特别要求，则用简洁的中文回答，排版清晰。")
        messages = [{"role": "system", "content": system}]

        rounds = self.cfg.get("history_rounds", DEFAULT_HISTORY_ROUNDS)
        try:
            rounds = int(rounds)
        except Exception:
            rounds = DEFAULT_HISTORY_ROUNDS
        if rounds > 0:
            messages.extend(self.history[-rounds * 2:])
        messages.append({"role": "user", "content": full_text})

        self.status.config(text="请求中...")
        threading.Thread(target=self._call_api,
                         args=(messages, text), daemon=True).start()

    def _call_api(self, messages, user_text):
        try:
            kwargs = dict(
                model=self.cfg.get("model", "deepseek-flash"),
                messages=messages,
                temperature=0.3,
                stream=True,
            )
            eb = self._build_extra_body(self.cfg)
            if eb:
                kwargs["extra_body"] = eb

            stream = self.client.chat.completions.create(**kwargs)

            self.chat_area.config(state="normal")
            self.chat_area.insert("end", "\n【AI】\n", "ai")
            self.chat_area.config(state="disabled")

            full = ""
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full += delta
                    self.chat_area.config(state="normal")
                    self.chat_area.insert("end", delta, "ai")
                    self.chat_area.see("end")
                    self.chat_area.config(state="disabled")

            self.chat_area.config(state="normal")
            self.chat_area.insert("end", "\n")
            self.chat_area.config(state="disabled")

            # history 存原始输入
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": full})
            self.status.config(text="完成")

            self.root.after(0, self._update_rounds_label)
        except Exception as e:
            self._append("sys", f"[错误] {e}")
            self.status.config(text="出错")


if __name__ == "__main__":
    root = tk.Tk()
    app = LangLearnerApp(root)
    root.mainloop()