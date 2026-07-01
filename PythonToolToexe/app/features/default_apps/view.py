# -*- coding: utf-8 -*-
"""默认应用清理功能视图（tkinter 版）。

读取并展示系统中各文件扩展名 / URL 协议的默认打开程序信息，
支持一键识别 WPS 篡改、全选后一键还原、手动设置默认软件。
扫描在后台线程执行，避免读取版本信息时卡界面。
"""

import os
import tkinter as tk
from tkinter import ttk

from app.features.default_apps import core
from app.view.theme import COLOR_FG, FONT_FAMILY, FONT_SIZE


# Treeview 列定义
COLUMNS = ("type", "id", "progid", "app", "company", "product", "exe", "wps")


def register(add_page, ctx):
    """向主窗口注册"默认应用清理"页签。

    :param add_page: 主窗口提供的添加页签回调，签名 add_page(label) -> ttk.Frame。
    :param ctx: FeatureContext 上下文。
    """
    DefaultAppsView(add_page, ctx)


class DefaultAppsView:
    """默认应用清理页签视图：表格展示 + 还原 / 设置 / WPS 识别操作。"""

    def __init__(self, add_page, ctx):
        """构建页面内容并注册，启动时后台扫描一次。"""
        self.ctx = ctx
        self.items = []                # AssocItem 列表
        self.filter_wps_only = False   # 是否仅显示 WPS 项
        self._iid_map = {}             # iid -> AssocItem

        self._build(add_page("默认应用清理"))
        self.refresh()

    def _build(self, page):
        """构建工具栏 + 表格。"""
        # 顶部工具栏
        bar = ttk.Frame(page)
        bar.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(bar, text="刷新列表", command=self.refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="识别WPS篡改", command=self.filter_wps).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="显示全部", command=self.show_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="全选WPS", command=self.select_all_wps).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="一键还原(选中)", command=self.restore_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="手动设置默认", command=self.manual_set).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="在Windows设置中打开", command=self.open_windows_settings).pack(side=tk.LEFT, padx=2)

        # 表格
        table_frame = ttk.Frame(page)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        self.tree = ttk.Treeview(
            table_frame, columns=COLUMNS, show="headings", selectmode="extended",
        )
        titles = {
            "type": "类型", "id": "默认应用", "progid": "ProgId",
            "app": "当前打开软件", "company": "厂商/公司", "product": "产品名",
            "exe": "可执行路径", "wps": "WPS占用",
        }
        widths = {"type": 50, "id": 80, "progid": 170, "app": 150,
                  "company": 130, "product": 130, "exe": 340, "wps": 70}
        for col in COLUMNS:
            self.tree.heading(col, text=titles[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=False)
        # 标签: WPS 行红色
        self.tree.tag_configure("wps", foreground="#c0392b")
        self.tree.tag_configure("normal", foreground=COLOR_FG)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

    # ===== 扫描与渲染 =====

    def refresh(self):
        """后台扫描系统默认应用并刷新表格。"""
        self.ctx.set_status("正在扫描默认应用...", "info")
        self.ctx.run_thread(
            core.scan_all_associations,
            on_result=self._on_scan_done,
            on_error=self._on_scan_error,
        )

    def _on_scan_done(self, items):
        """扫描完成：保存数据并渲染表格。"""
        self.items = items
        self._render_table()

    def _on_scan_error(self, error):
        """扫描出错上报。"""
        self.ctx.set_status("扫描失败：{0}".format(error), "error")

    def _render_table(self):
        """根据当前数据与筛选条件渲染表格行。"""
        for iid in list(self._iid_map.keys()):
            self.tree.delete(iid)
        self._iid_map.clear()

        shown = [it for it in self.items if it.is_wps] if self.filter_wps_only else self.items
        for it in shown:
            tag = "wps" if it.is_wps else "normal"
            iid = self.tree.insert("", tk.END, values=(
                it.kind,
                it.identifier,
                it.prog_id or "(无)",
                it.description or "(未知)",
                it.company or "-",
                it.product or "-",
                it.exe_path or "(未解析)",
                "是" if it.is_wps else "否",
            ), tags=(tag,))
            self._iid_map[iid] = it

        total = len(self.items)
        wps = sum(1 for it in self.items if it.is_wps)
        self.ctx.set_status(
            "共 %d 项默认应用设置, 其中 WPS 占用 %d 项 (当前显示 %d 项)" % (total, wps, len(shown)),
            "info",
        )

    # ===== 筛选 / 选择 =====

    def filter_wps(self):
        """仅显示被 WPS 占用的关联项。"""
        self.filter_wps_only = True
        self._render_table()

    def show_all(self):
        """显示全部关联项(取消 WPS 筛选)。"""
        self.filter_wps_only = False
        self._render_table()

    def select_all_wps(self):
        """选中表格中所有 WPS 占用行(用于批量还原)。"""
        for iid in self.tree.get_children():
            it = self._iid_map.get(iid)
            if it is not None and it.is_wps:
                self.tree.selection_add(iid)
            else:
                self.tree.selection_remove(iid)

    def _get_selected_items(self):
        """获取当前选中行对应的 AssocItem 列表。"""
        result = []
        for iid in self.tree.selection():
            it = self._iid_map.get(iid)
            if it is not None:
                result.append(it)
        return result

    # ===== 还原 =====

    def restore_selected(self):
        """一键还原所有选中项(删除对应 UserChoice / 协议关联)。"""
        selected = self._get_selected_items()
        if not selected:
            self.ctx.show_alert("提示", "请先在列表中选择要还原的项")
            return
        msg = "确认还原以下 %d 项默认应用为系统原生设置?\n\n" % len(selected)
        msg += "\n".join("%s %s" % (it.kind, it.identifier) for it in selected)
        self.ctx.confirm("确认还原", msg, on_ok=lambda: self._do_restore(selected))

    def _do_restore(self, selected):
        """实际执行还原(同步), 完成后刷新。"""
        ok, fail = 0, []
        for it in selected:
            success, info = core.restore_item(it)
            if success:
                ok += 1
            else:
                fail.append(info)
        core.notify_shell_change()
        if fail:
            self.ctx.show_alert("还原完成",
                                "成功还原 %d 项\n失败:\n%s" % (ok, "\n".join(fail)))
        else:
            self.ctx.show_alert("还原完成", "成功还原 %d 项" % ok)
        self.refresh()

    # ===== 手动设置 =====

    def manual_set(self):
        """对选中项弹出对话框, 选择目标 ProgId 后写回默认设置。"""
        selected = self._get_selected_items()
        if len(selected) != 1:
            self.ctx.show_alert("提示", "请只选择 1 项进行手动设置(当前选择 %d 项)" % len(selected))
            return
        it = selected[0]
        is_uri = (it.kind == "协议")
        candidates = core.list_candidate_progids(it.identifier, is_uri=is_uri)
        if it.prog_id and it.prog_id not in candidates:
            candidates.insert(0, it.prog_id)
        self._open_set_dialog(it, is_uri, candidates)

    def _open_set_dialog(self, item, is_uri, candidates):
        """弹出手动设置对话框，列出候选 ProgId 供选择。"""
        dlg = tk.Toplevel(self.ctx.root)
        dlg.title("手动设置默认程序 - %s %s" % (item.kind, item.identifier))
        dlg.geometry("620x380")
        dlg.transient(self.ctx.root)
        dlg.grab_set()

        ttk.Label(dlg, text="默认应用: %s %s" % (item.kind, item.identifier)).pack(anchor=tk.W, padx=10, pady=(10, 4))
        ttk.Label(dlg, text="当前 ProgId: %s" % (item.prog_id or "(无)")).pack(anchor=tk.W, padx=10, pady=(0, 6))
        ttk.Label(dlg, text="选择要替代的目标程序 (ProgId):").pack(anchor=tk.W, padx=10, pady=(0, 4))

        list_frame = ttk.Frame(dlg)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        listbox = tk.Listbox(list_frame, activestyle="none",
                             font=(FONT_FAMILY, FONT_SIZE))
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=vsb.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 显示 "ProgId | exe 路径" 便于识别
        display_map = {}
        for pid in candidates:
            cmd = core.resolve_prog_command(pid) or ""
            exe = core.extract_exe_path(cmd) or "-"
            disp = "%s    |    %s" % (pid, exe)
            display_map[disp] = pid
            listbox.insert(tk.END, disp)
        if item.prog_id:
            # 默认选中当前项
            for idx, disp in enumerate(display_map.keys()):
                if display_map[disp] == item.prog_id:
                    listbox.selection_set(idx)
                    break

        def on_apply():
            """确认应用所选 ProgId。"""
            sel = listbox.curselection()
            if not sel:
                self.ctx.show_alert("提示", "请先在列表中选择一个目标程序")
                return
            disp = listbox.get(sel[0])
            target_pid = display_map.get(disp)
            if not target_pid:
                return
            success, info = core.set_item_default(item, target_pid)
            if success:
                self.ctx.show_alert("成功", info)
                dlg.destroy()
                self.refresh()
            else:
                self.ctx.show_alert("失败", info)

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="应用", command=on_apply).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

    def open_windows_settings(self):
        """打开 Windows 系统默认应用设置页面(后备手动设置入口)。"""
        try:
            os.system("start ms-settings:defaultapps")
            self.ctx.set_status("已打开 Windows 默认应用设置", "info")
        except Exception as e:
            self.ctx.set_status("无法打开设置: %s" % e, "error")
