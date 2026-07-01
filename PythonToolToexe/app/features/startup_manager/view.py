# -*- coding: utf-8 -*-
"""开机启动管理功能视图（tkinter 版）：单页签 + 左侧导航切换三个子功能。

主窗口注册一个页签【开机启动项管理】，页签内部为左右两栏：
- 左栏：导航菜单（设置开机启动 / 取消开机启动 / 应用取消历史）
- 右栏：内容区，根据左栏选中项切换显示对应面板

视图层调用 core 业务逻辑，捕获 StartupError 后通过 FeatureContext 弹窗/上报状态。
后台扫描使用 threading（经 ctx.run_thread），文件选择使用原生 filedialog。
"""

import os
import tkinter as tk
from tkinter import ttk

from app.features.startup_manager import core
from app.view.theme import (
    COLOR_ROW_SEL, COLOR_BORDER, COLOR_TREEVIEW_BG, COLOR_FG,
    FONT_FAMILY, FONT_SIZE,
)


def register(add_page, ctx):
    """向主窗口注册开机启动管理页签（单页签，内部左侧导航切换子功能）。

    :param add_page: 主窗口提供的添加页签回调，签名 add_page(label) -> ttk.Frame。
    :param ctx: FeatureContext 上下文。
    """
    StartupView(add_page, ctx)


class StartupView:
    """开机启动管理页签视图：左侧导航 + 右侧三面板（设置/取消/历史）。"""

    def __init__(self, add_page, ctx):
        """构建页签外壳与三个子面板，启动时刷新数据。"""
        self.ctx = ctx
        self.selected_path = None

        # 主页签容器
        page = add_page("开机启动项管理")

        # 左右两栏：左导航 + 右内容
        body = ttk.Frame(page)
        body.pack(fill=tk.BOTH, expand=True)

        self._build_nav(body)
        content = ttk.Frame(body)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=10)

        # 三个子面板（都挂在 content 下，通过 pack/forget 切换可见性）
        self.setup_panel = ttk.Frame(content)
        self.remove_panel = ttk.Frame(content)
        self.history_panel = ttk.Frame(content)
        self._build_setup(self.setup_panel)
        self._build_remove(self.remove_panel)
        self._build_history(self.history_panel)

        # 默认显示"设置开机启动"
        self._show_panel("setup")

        # 程序启动时刷新一次启动项列表与历史
        self.refresh_startup()
        self.refresh_history()

    def _build_nav(self, parent):
        """构建左侧导航菜单。"""
        nav = ttk.Frame(parent, width=180, style="Nav.TFrame")
        nav.pack(side=tk.LEFT, fill=tk.Y, pady=10)
        nav.pack_propagate(False)  # 固定导航栏宽度

        # 导航标题
        ttk.Label(nav, text="功能导航", style="Nav.TLabel").pack(anchor=tk.W, pady=(8, 6))

        # 三个导航项（Radiobutton 风格，无圆点，选中高亮）
        self.nav_var = tk.StringVar(value="setup")
        nav_items = [
            ("设置开机启动", "setup"),
            ("取消开机启动", "remove"),
            ("应用取消历史", "history"),
        ]
        for text, value in nav_items:
            ttk.Radiobutton(
                nav, text=text, value=value, variable=self.nav_var,
                command=self._on_nav_change, style="Nav.TRadiobutton",
            ).pack(fill=tk.X, pady=1)

    def _on_nav_change(self):
        """左侧导航切换：根据选中项显示对应面板。"""
        self._show_panel(self.nav_var.get())

    def _show_panel(self, which):
        """切换右侧内容区显示的面板。"""
        for panel in (self.setup_panel, self.remove_panel, self.history_panel):
            panel.pack_forget()
        if which == "setup":
            self.setup_panel.pack(fill=tk.BOTH, expand=True)
        elif which == "remove":
            self.remove_panel.pack(fill=tk.BOTH, expand=True)
        elif which == "history":
            self.history_panel.pack(fill=tk.BOTH, expand=True)

    # ===== 面板1：设置开机启动应用 =====

    def _build_setup(self, page):
        """构建设置开机启动应用面板：目录输入 + 扫描 + 候选列表 + 别名 + 添加。"""
        # 第一行：目录输入 + 浏览 + 进度条
        row1 = ttk.Frame(page)
        row1.pack(fill=tk.X, padx=10, pady=(10, 6))

        self.entry_dir = ttk.Entry(row1)
        self.entry_dir.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_browse = ttk.Button(row1, text="浏览", command=self._on_browse)
        self.btn_browse.pack(side=tk.LEFT, padx=(6, 0))

        self.progress = ttk.Progressbar(row1, mode="indeterminate", length=90)
        # 默认隐藏，扫描时再 pack

        # 第二行：扫描 + 添加
        row2 = ttk.Frame(page)
        row2.pack(fill=tk.X, padx=10, pady=6)
        self.btn_scan = ttk.Button(row2, text="扫描", command=self._on_scan)
        self.btn_scan.pack(side=tk.LEFT)
        self.btn_add = ttk.Button(row2, text="添加到开机启动", command=self._on_add)
        self.btn_add.pack(side=tk.LEFT, padx=6)

        # 候选列表
        list_frame = ttk.Frame(page)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        self.candidate_list = tk.Listbox(
            list_frame,
            bg=COLOR_TREEVIEW_BG, fg=COLOR_FG,
            selectbackground=COLOR_ROW_SEL, selectforeground=COLOR_FG,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            borderwidth=0, activestyle="none",
            font=(FONT_FAMILY, FONT_SIZE),
        )
        vsb = ttk.Scrollbar(list_frame, orient="vertical",
                            command=self.candidate_list.yview)
        self.candidate_list.configure(yscrollcommand=vsb.set)
        self.candidate_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.candidate_list.bind("<<ListboxSelect>>", self._on_candidate_click)

        # 别名输入
        self.entry_alias = ttk.Entry(page)
        self.entry_alias.pack(fill=tk.X, padx=10, pady=(6, 10))

    def _on_browse(self):
        """点击浏览：弹出原生目录选择器，返回后填入输入框。"""
        path = self.ctx.choose_directory("选择要扫描的目录", self.entry_dir.get())
        if path:
            self.entry_dir.delete(0, tk.END)
            self.entry_dir.insert(0, path)
            self.ctx.set_status("已选择目录：{0}".format(path), "info")

    def _on_scan(self):
        """启动后台扫描，期间显示进度条、禁用按钮。"""
        directory = self.entry_dir.get().strip()
        self.candidate_list.delete(0, tk.END)
        self.selected_path = None
        self.progress.pack(side=tk.LEFT, padx=(6, 0))
        self.progress.start(12)
        self.btn_scan.configure(state=tk.DISABLED)

        self.ctx.run_thread(
            core.scan_directory,
            directory,
            on_result=self._on_scan_done,
            on_error=self._on_scan_error,
        )

    def _on_scan_done(self, found_files):
        """扫描完成：填充候选列表。"""
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_scan.configure(state=tk.NORMAL)
        if not found_files:
            self.ctx.set_status("该目录下未找到可执行文件", "warn")
            return
        for fp in found_files:
            self.candidate_list.insert(tk.END, fp)
        self.ctx.set_status("找到 {0} 个可执行文件".format(len(found_files)), "info")

    def _on_scan_error(self, error):
        """扫描出错：恢复 UI 并上报。"""
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_scan.configure(state=tk.NORMAL)
        self.ctx.set_status("扫描失败：{0}".format(error), "error")

    def _on_candidate_click(self, _event):
        """点击候选项：记录选中路径，并填别名输入框。"""
        sel = self.candidate_list.curselection()
        if not sel:
            return
        self.selected_path = self.candidate_list.get(sel[0])
        name_no_ext = os.path.splitext(os.path.basename(self.selected_path))[0]
        self.entry_alias.delete(0, tk.END)
        self.entry_alias.insert(0, name_no_ext)

    def _on_add(self):
        """添加开机启动项：校验选区 -> 二次确认 -> 调 core -> 弹窗/刷新。"""
        if not self.selected_path:
            self.ctx.show_alert("提示", "请先在候选列表中选择一个文件。")
            return
        full_path = self.selected_path
        name_no_ext = os.path.splitext(os.path.basename(full_path))[0]
        alias = self.entry_alias.get().strip()
        run_name = alias if alias else name_no_ext
        msg = "确认添加以下开机启动项？\n\n启动项名称：{0}\n程序路径：{1}".format(run_name, full_path)
        self.ctx.confirm("二次确认", msg, on_ok=lambda: self._do_add(full_path, run_name, alias))

    def _do_add(self, full_path, run_name, alias):
        """实际执行添加逻辑，捕获 StartupError 弹窗。"""
        try:
            core.add_to_startup(full_path, run_name, alias)
        except core.StartupError as ex:
            self.ctx.show_alert("添加失败", str(ex))
            self.ctx.set_status("添加失败", "error")
            return
        self.ctx.set_status("已添加开机启动项：{0}".format(run_name), "info")
        self.ctx.show_alert("添加成功", "已添加开机启动项：\n{0}".format(run_name))
        self.refresh_startup()

    # ===== 面板2：取消开机启动应用 =====

    def _build_remove(self, page):
        """构建取消开机启动应用面板：可多选表格 + 取消按钮。"""
        self.btn_remove = ttk.Button(page, text="取消选中启动项", command=self._on_remove)
        self.btn_remove.pack(anchor=tk.W, padx=10, pady=(10, 6))

        table_frame = ttk.Frame(page)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.table_startup = ttk.Treeview(
            table_frame,
            columns=("name", "path", "alias"),
            show="headings",
            selectmode="extended",
        )
        self.table_startup.heading("name", text="名称")
        self.table_startup.heading("path", text="路径")
        self.table_startup.heading("alias", text="别名")
        self.table_startup.column("name", width=200, anchor=tk.W)
        self.table_startup.column("path", width=420, anchor=tk.W)
        self.table_startup.column("alias", width=160, anchor=tk.W)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self.table_startup.yview)
        self.table_startup.configure(yscrollcommand=vsb.set)
        self.table_startup.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # iid -> 行数据，便于删除时读取
        self._startup_rows = {}

    def refresh_startup(self):
        """重新读取注册表 Run 键与 aliases.json，刷新当前启动项表格。"""
        try:
            rows = core.list_startup()
        except core.StartupError as ex:
            self.ctx.show_alert("读取失败", str(ex))
            self.ctx.set_status("读取启动项失败", "error")
            return

        # 清空旧数据
        for iid in self.table_startup.get_children():
            self.table_startup.delete(iid)
        self._startup_rows.clear()

        for r in rows:
            iid = self.table_startup.insert("", tk.END, values=(r["name"], r["path"], r["alias"]))
            self._startup_rows[iid] = r
        self.ctx.set_status("当前启动项 {0} 个".format(len(rows)), "info")

    def _on_remove(self):
        """删除选中的启动项：二次确认后调 core.remove_startup。"""
        selected = self.table_startup.selection()
        if not selected:
            self.ctx.show_alert("提示", "请先选中要取消的启动项（按住 Ctrl 多选）。")
            return

        pending = [self._startup_rows[iid] for iid in selected if iid in self._startup_rows]
        detail = "\n".join("• 名称：{0}　路径：{1}".format(p["name"], p["path"]) for p in pending)
        self.ctx.confirm(
            "二次确认",
            "确认取消以下开机启动项？此操作不可撤销：\n\n{0}".format(detail),
            on_ok=lambda: self._do_remove(pending),
        )

    def _do_remove(self, pending):
        """实际执行删除并刷新两个面板。"""
        try:
            core.remove_startup(pending)
        except core.StartupError as ex:
            self.ctx.show_alert("删除失败", str(ex))
            self.ctx.set_status("删除失败", "error")
            return
        self.ctx.set_status("已取消 {0} 个启动项".format(len(pending)), "info")
        self.ctx.show_alert("成功", "已取消选中的启动项。")
        self.refresh_startup()
        self.refresh_history()

    # ===== 面板3：应用取消历史 =====

    def _build_history(self, page):
        """构建应用取消历史面板：只读表格 + 清空按钮。"""
        self.btn_clear_history = ttk.Button(page, text="清空历史", command=self._on_clear_history)
        self.btn_clear_history.pack(anchor=tk.W, padx=10, pady=(10, 6))

        table_frame = ttk.Frame(page)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.table_history = ttk.Treeview(
            table_frame,
            columns=("name", "path", "alias", "deleted_at"),
            show="headings",
            selectmode="browse",
        )
        self.table_history.heading("name", text="名称")
        self.table_history.heading("path", text="路径")
        self.table_history.heading("alias", text="别名")
        self.table_history.heading("deleted_at", text="删除时间")
        self.table_history.column("name", width=180, anchor=tk.W)
        self.table_history.column("path", width=380, anchor=tk.W)
        self.table_history.column("alias", width=140, anchor=tk.W)
        self.table_history.column("deleted_at", width=160, anchor=tk.W)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self.table_history.yview)
        self.table_history.configure(yscrollcommand=vsb.set)
        self.table_history.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_history(self):
        """重新读取 deleted_startup.json，刷新删除历史表格。"""
        rows = core.list_deleted()
        for iid in self.table_history.get_children():
            self.table_history.delete(iid)
        for r in rows:
            self.table_history.insert("", tk.END,
                                      values=(r["name"], r["path"], r["alias"], r["deleted_at"]))

    def _on_clear_history(self):
        """清空全部删除历史（二次确认后清空 deleted_startup.json）。"""
        if not core.list_deleted():
            self.ctx.show_alert("提示", "删除历史为空，无需清空。")
            return
        self.ctx.confirm(
            "二次确认",
            "确认清空全部删除历史？此操作不可撤销。",
            on_ok=self._do_clear_history,
        )

    def _do_clear_history(self):
        """实际执行清空并刷新历史。"""
        try:
            core.clear_deleted()
        except core.StartupError as ex:
            self.ctx.show_alert("清空失败", str(ex))
            self.ctx.set_status("清空历史失败", "error")
            return
        self.refresh_history()
        self.ctx.set_status("已清空删除历史", "info")
        self.ctx.show_alert("成功", "已清空删除历史。")
