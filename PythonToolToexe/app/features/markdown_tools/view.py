# -*- coding: utf-8 -*-
"""Markdown 转文档功能视图（tkinter 版）：编辑 + 多格式导出。

视图层调用 renderers.export_markdown，捕获异常弹窗，并通过 ctx.set_status 上报状态。
文件选择使用原生 filedialog；导出 PDF 等耗时操作使用后台线程。
"""

import tkinter as tk
from tkinter import ttk

from app.config import EXPORT_FORMATS
from app.view.theme import (
    COLOR_TREEVIEW_BG, COLOR_FG, COLOR_BORDER,
    MONO_FAMILY, FONT_FAMILY, FONT_SIZE,
)
from app.features.markdown_tools.renderers import export_markdown


def register(add_page, ctx):
    """向主窗口注册"Markdown 转文档"页签。

    :param add_page: 主窗口提供的添加页签回调，签名 add_page(label) -> ttk.Frame。
    :param ctx: FeatureContext 上下文。
    """
    MarkdownView(add_page, ctx)


class MarkdownView:
    """Markdown 转文档页签视图：编辑 Markdown + 选择格式 + 导出。"""

    def __init__(self, add_page, ctx):
        """构建页签内容并注册。"""
        self.ctx = ctx
        self.add_page = add_page
        self._build_ui(add_page("Markdown 转文档"))

    def _build_ui(self, page):
        """构建 Markdown 转文档 Tab 的内容：工具栏 + 多行输入 + 格式选择 + 导出。"""
        # 工具栏
        toolbar = ttk.Frame(page)
        toolbar.pack(fill=tk.X, padx=10, pady=(10, 6))

        self.btn_load = ttk.Button(toolbar, text="加载 .md 文件", command=self._on_load)
        self.btn_load.pack(side=tk.LEFT)

        self.btn_sample = ttk.Button(toolbar, text="填入示例", command=self._on_fill_sample)
        self.btn_sample.pack(side=tk.LEFT, padx=6)

        self.btn_clear = ttk.Button(toolbar, text="清空", command=self._on_clear)
        self.btn_clear.pack(side=tk.LEFT)

        # Markdown 编辑器（tk.Text + 滚动条）
        editor_frame = ttk.Frame(page)
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        self.md_editor = tk.Text(
            editor_frame,
            wrap=tk.WORD,
            bg=COLOR_TREEVIEW_BG, fg=COLOR_FG,
            insertbackground=COLOR_FG,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            borderwidth=0, padx=6, pady=6,
            font=(MONO_FAMILY, FONT_SIZE + 1),
            undo=True,
        )
        # 占位提示
        self.md_editor.insert("1.0", "在此输入 Markdown")
        self.md_editor.configure(foreground="#9aa0a6")
        self.md_editor.bind("<FocusIn>", self._on_editor_focus_in)
        self._editor_placeholder = True

        vsb = ttk.Scrollbar(editor_frame, orient="vertical",
                            command=self.md_editor.yview)
        self.md_editor.configure(yscrollcommand=vsb.set)
        self.md_editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 导出格式 + 导出按钮
        export_bar = ttk.Frame(page)
        export_bar.pack(fill=tk.X, padx=10, pady=(6, 10))
        ttk.Label(export_bar, text="导出格式：").pack(side=tk.LEFT)

        # Combobox 用索引映射到格式 key
        self._fmt_keys = [x[0] for x in EXPORT_FORMATS]
        self.fmt_dropdown = ttk.Combobox(
            export_bar, state="readonly",
            values=[x[1] for x in EXPORT_FORMATS], width=22,
        )
        self.fmt_dropdown.current(0)
        self.fmt_dropdown.pack(side=tk.LEFT, padx=6)

        self.btn_export = ttk.Button(export_bar, text="导出", command=self._on_export)
        self.btn_export.pack(side=tk.LEFT)

    def _on_editor_focus_in(self, _event):
        """编辑器首次获得焦点时清掉占位提示文本。"""
        if self._editor_placeholder:
            self.md_editor.delete("1.0", tk.END)
            self.md_editor.configure(foreground=COLOR_FG)
            self._editor_placeholder = False

    def _get_md_text(self):
        """取出编辑器文本（若是占位状态返回空串）。"""
        if self._editor_placeholder:
            return ""
        return self.md_editor.get("1.0", tk.END).rstrip("\n")

    def _set_md_text(self, text):
        """设置编辑器文本并清除占位状态。"""
        self.md_editor.delete("1.0", tk.END)
        self.md_editor.insert("1.0", text)
        self.md_editor.configure(foreground=COLOR_FG)
        self._editor_placeholder = False

    def _on_load(self):
        """点击加载：弹出原生文件选择器选 .md/.txt，返回后读取内容。"""
        path = self.ctx.choose_open_file(
            "选择 Markdown 文件",
            filetypes=[("Markdown/文本", "*.md *.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._set_md_text(f.read())
            self.ctx.set_status("已加载：{0}".format(path), "info")
        except Exception as ex:
            self.ctx.show_alert("读取失败", "读取文件失败：\n{0}".format(ex))
            self.ctx.set_status("读取文件失败", "error")

    def _on_fill_sample(self):
        """向编辑器填入示例 Markdown，便于快速体验。"""
        sample = (
            "# Markdown 转文档示例\n\n"
            "这是一个把 **Markdown** 转换为 _多种文档格式_ 的示例。\n\n"
            "## 支持的格式\n\n"
            "1. Word 文档（.doc / .docx）\n"
            "2. PDF 文档（.pdf）\n"
            "3. Excel 表格（.xlsx）\n\n"
            "## 行内样式\n\n"
            "支持 **粗体**、_斜体_、`行内代码`、~~删除线~~ 以及 [超链接](https://github.com)。\n\n"
            "## 代码块\n\n"
            "```python\n"
            "def hello():\n"
            "    print('Hello, Markdown!')\n"
            "```\n\n"
            "## 引用\n\n"
            "> 这是一段引用文字。\n"
            "> 可以有多行。\n\n"
            "## 表格\n\n"
            "| 格式 | 说明 |\n"
            "| --- | --- |\n"
            "| doc | Word 旧版格式 |\n"
            "| docx | Word 新版格式 |\n"
            "| pdf | 便携文档格式 |\n"
            "| xlsx | Excel 表格 |\n\n"
            "---\n\n"
            "更多内容请自行编辑后导出。"
        )
        self._set_md_text(sample)
        self.ctx.set_status("已填入示例", "info")

    def _on_clear(self):
        """清空编辑器。"""
        self.md_editor.delete("1.0", tk.END)
        self._editor_placeholder = False
        self.ctx.set_status("已清空", "info")

    def _on_export(self):
        """选保存路径，然后后台线程导出（PDF 嵌字体耗时长）。"""
        md = self._get_md_text().strip()
        if not md:
            self.ctx.show_alert("提示", "请先输入 Markdown 内容。")
            return

        idx = self.fmt_dropdown.current()
        if idx < 0 or idx >= len(self._fmt_keys):
            self.ctx.show_alert("提示", "请选择导出格式。")
            return
        fmt = self._fmt_keys[idx]

        # 由 key 反查默认扩展名与过滤器（config 中 filters 已是 tkinter filetypes 格式）
        fmt_info = next((x for x in EXPORT_FORMATS if x[0] == fmt), None)
        if not fmt_info:
            self.ctx.show_alert("提示", "不支持的导出格式。")
            return
        _key, _label, ext, filters = fmt_info

        path = self.ctx.choose_save_file(
            "选择导出位置",
            filetypes=filters,
            default_filename="export" + ext,
        )
        if not path:
            return

        # 自动补齐扩展名
        if not path.lower().endswith(ext.lower()):
            path += ext

        self.ctx.set_status("正在导出...", "info")
        self.btn_export.configure(state=tk.DISABLED)
        self.ctx.run_thread(
            export_markdown,
            md, fmt, path,
            on_result=lambda _r: self._on_export_done(path),
            on_error=self._on_export_error,
        )

    def _on_export_done(self, path):
        """导出成功回调（主线程）。"""
        self.btn_export.configure(state=tk.NORMAL)
        self.ctx.set_status("导出成功：{0}".format(path), "info")

    def _on_export_error(self, error):
        """导出失败回调（主线程）。"""
        self.btn_export.configure(state=tk.NORMAL)
        self.ctx.set_status("导出失败：{0}".format(error), "error")
        self.ctx.show_alert("导出失败", str(error))
