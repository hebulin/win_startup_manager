# -*- coding: utf-8 -*-
"""界面主题：tkinter 版配色常量与全局样式应用。

保留原项目颜色体系，通过 ttk.Style 应用到全部 ttk 控件。
业务逻辑与视图层均可从这里导入颜色常量。
"""

import tkinter as tk
from tkinter import ttk


# ===== 配色常量 =====
COLOR_BG = "#f5f6f8"             # 窗口背景
COLOR_FG = "#1f2329"             # 默认前景文字
COLOR_ACCENT = "#2b6cb0"         # 主色调
COLOR_ACCENT_FG = "#ffffff"      # 主色调上的文字
COLOR_BORDER = "#d0d7de"         # 边框
COLOR_ROW_ALT = "#f0f2f5"        # 表格隔行底色
COLOR_ROW_SEL = "#cfe2f3"        # 表格选中行底色
COLOR_LINK = "#0645ad"           # 超链接
COLOR_STATUS_INFO = "#1f2329"    # 状态栏-普通
COLOR_STATUS_WARN = "#b8860b"    # 状态栏-警告
COLOR_STATUS_ERR = "#c0392b"     # 状态栏-错误
COLOR_STATUS_BAR_BG = "#eef1f4"  # 状态栏背景
COLOR_TREEVIEW_BG = "#ffffff"    # 列表/表格背景

# ===== 字体/边距常量 =====
FONT_FAMILY = "Microsoft YaHei"
FONT_SIZE = 10
MONO_FAMILY = "Consolas"
PAD_OUTER = 10
PAD_INNER = 6


def apply_theme(root):
    """在根窗口上应用全局 ttk 样式与默认字体。"""
    style = ttk.Style(root)
    # clam 主题可定制性最强，失败则回退默认主题
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=COLOR_BG)

    font_main = (FONT_FAMILY, FONT_SIZE)
    font_bold = (FONT_FAMILY, FONT_SIZE, "bold")

    # 全局默认
    style.configure(".", background=COLOR_BG, foreground=COLOR_FG, font=font_main)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_FG)

    # 按钮：主色填充
    style.configure("TButton",
                    background=COLOR_ACCENT, foreground=COLOR_ACCENT_FG,
                    font=font_main, borderwidth=0, focusthickness=2,
                    padding=(10, 5))
    style.map("TButton",
              background=[("active", "#225a9a"), ("pressed", "#1b4a7d"),
                          ("disabled", "#a0aec0")],
              foreground=[("disabled", "#edf2f7")])

    # 输入控件
    style.configure("TEntry",
                    fieldbackground=COLOR_TREEVIEW_BG, foreground=COLOR_FG,
                    bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER,
                    darkcolor=COLOR_BORDER, insertcolor=COLOR_FG,
                    padding=3)
    style.configure("TCombobox",
                    fieldbackground=COLOR_TREEVIEW_BG, foreground=COLOR_FG,
                    background=COLOR_ACCENT, arrowcolor=COLOR_ACCENT_FG,
                    bordercolor=COLOR_BORDER, padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", COLOR_TREEVIEW_BG)],
              foreground=[("readonly", COLOR_FG)])

    # Treeview
    style.configure("Treeview",
                    background=COLOR_TREEVIEW_BG, foreground=COLOR_FG,
                    fieldbackground=COLOR_TREEVIEW_BG, rowheight=24,
                    bordercolor=COLOR_BORDER)
    style.configure("Treeview.Heading",
                    background="#edf2f7", foreground=COLOR_FG,
                    font=font_bold, borderwidth=1, relief="solid")
    style.map("Treeview",
              background=[("selected", COLOR_ROW_SEL)],
              foreground=[("selected", COLOR_FG)])
    style.map("Treeview.Heading", background=[("active", "#e2e8f0")])

    # Notebook（顶部页签）
    style.configure("TNotebook", background=COLOR_BG, borderwidth=0, tabmargins=(8, 6, 8, 0))
    style.configure("TNotebook.Tab",
                    background=COLOR_BG, foreground="#6b7280",
                    padding=(20, 9), font=font_main, borderwidth=0, focuscolor=COLOR_BG)
    style.map("TNotebook.Tab",
              background=[("selected", COLOR_TREEVIEW_BG), ("active", "#eef1f4")],
              foreground=[("selected", COLOR_ACCENT), ("active", COLOR_FG)])

    # 侧边导航（Radiobutton 风格：无圆点，选中高亮）
    style.configure("Nav.TRadiobutton",
                    background=COLOR_BG, foreground=COLOR_FG,
                    indicator=0, focuscolor=COLOR_BG,
                    padding=(14, 11), font=font_main, borderwidth=0)
    style.map("Nav.TRadiobutton",
              background=[("selected", COLOR_ROW_SEL), ("active", "#eef1f4")],
              foreground=[("selected", COLOR_ACCENT)])
    style.configure("Nav.TFrame", background=COLOR_BG)
    style.configure("Nav.TLabel", background=COLOR_BG, foreground="#9aa0a6",
                    font=(FONT_FAMILY, FONT_SIZE - 1), padding=(14, 2))

    # Progressbar
    style.configure("Horizontal.TProgressbar",
                    background=COLOR_ACCENT, troughcolor=COLOR_BORDER,
                    bordercolor=COLOR_BORDER)

    # 状态栏 Label
    style.configure("Status.TLabel",
                    background=COLOR_STATUS_BAR_BG, foreground=COLOR_STATUS_INFO,
                    padding=(8, 5))
