# -*- coding: utf-8 -*-
"""功能上下文：功能包与主窗口之间的轻量契约（tkinter 版）。

把主窗口的通用能力（状态栏、后台线程、文件对话框、消息框、剪贴板）
打包成稳定接口，功能包不反向依赖 main_window，保证依赖方向单向。
"""

from tkinter import messagebox, filedialog

from app.view.worker import Worker


class FeatureContext:
    """功能包与主窗口之间的轻量上下文：只暴露共享服务。"""

    def __init__(self, root, status_var, status_label):
        """初始化上下文。

        :param root: tk.Tk 根窗口。
        :param status_var: 底部状态栏对应的 tk.StringVar。
        :param status_label: 状态栏 ttk.Label，用于切换前景色。
        """
        self.root = root
        self.window = root          # 兼容旧字段名
        self.status_var = status_var
        self.status_label = status_label

    # ===== 状态栏 =====

    def set_status(self, text, kind="info"):
        """更新底部状态栏文本与颜色。kind: info/warn/error。"""
        color_map = {
            "info": "#1f2329",
            "warn": "#b8860b",
            "error": "#c0392b",
        }
        self.status_var.set(text)
        if self.status_label is not None:
            self.status_label.configure(foreground=color_map.get(kind, color_map["info"]))

    # ===== 后台线程 =====

    def run_thread(self, fn, *args, on_result=None, on_error=None, on_finished=None):
        """把 fn 提交到后台线程执行，并通过 root.after 把回调投递回主线程。

        :param fn: 后台执行的函数。
        :param args: fn 的参数。
        :param on_result: 成功回调，签名为 on_result(result)。
        :param on_error: 异常回调，签名为 on_error(exception)。
        :param on_finished: 完成回调，无参数。
        """
        # after(0, cb) 把回调调度到 Tk 主事件循环，保证线程安全
        schedule = lambda cb: self.root.after(0, cb)
        Worker(fn, args, schedule, on_result, on_error, on_finished).start()

    # ===== 对话框 =====

    def show_alert(self, title, message):
        """弹出一个单按钮信息提示框。"""
        messagebox.showinfo(title, message, parent=self.root)

    def confirm(self, title, message, on_ok):
        """弹出确认/取消对话框，确认时回调 on_ok（在主线程同步执行）。"""
        ok = messagebox.askyesno(title, message, parent=self.root)
        if ok:
            on_ok()

    # ===== 文件对话框 =====

    def choose_directory(self, caption="选择目录", directory=""):
        """弹出原生目录选择对话框，返回目录路径或 None。"""
        path = filedialog.askdirectory(
            title=caption, initialdir=directory or None, parent=self.root,
        )
        return path if path else None

    def choose_open_file(self, caption, filetypes=None, directory=""):
        """弹出原生打开文件对话框，返回文件路径或 None。

        :param filetypes: tkinter filetypes 列表，如 [("Markdown", "*.md *.txt")]。
        """
        path = filedialog.askopenfilename(
            title=caption, initialdir=directory or None,
            filetypes=filetypes or [("所有文件", "*.*")], parent=self.root,
        )
        return path if path else None

    def choose_save_file(self, caption, filetypes=None, default_filename="", directory=""):
        """弹出原生保存文件对话框，返回文件路径或 None。"""
        path = filedialog.asksaveasfilename(
            title=caption, initialdir=directory or None,
            initialfile=default_filename or None,
            filetypes=filetypes or [("所有文件", "*.*")], parent=self.root,
        )
        return path if path else None

    # ===== 剪贴板 =====

    def clipboard_set_text(self, text):
        """把文本写入系统剪贴板。"""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ===== 兼容旧 page.update() 语义 =====

    def update(self):
        """触发主窗口刷新待处理事件（tkinter 一般自动刷新，此方法保留供旧代码兼容）。"""
        self.root.update_idletasks()
