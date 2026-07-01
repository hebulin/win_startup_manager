# -*- coding: utf-8 -*-
"""目录数据同步器功能视图（tkinter 版）。

页签【目录数据同步器】: 顶部本机连接信息 + 中部同步配置 + 底部日志进度。
程序启动即自动监听(持久化配对码, 端口自动选择), 无需手动启动监听。
支持两种角色: 目标端(被动接收) / 源端(连接目标发送)。
同步完成后记录历史日志(时间/内容/大小/耗时/成功/备份)。
"""

import os
import json
import time
import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app.features.dir_sync import core
from app.view.theme import (
    COLOR_BG, COLOR_TREEVIEW_BG, COLOR_FG, COLOR_BORDER, COLOR_LINK,
    FONT_FAMILY, FONT_SIZE,
)


def register(add_page, ctx):
    """向主窗口注册"目录数据同步器"页签。"""
    DirSyncView(add_page, ctx)


class DirSyncView:
    """目录数据同步器页签视图：自动监听 + 源/目标目录 + 同步 + 日志进度。"""

    def __init__(self, add_page, ctx):
        """构建页签内容, 启动自动监听。"""
        self.ctx = ctx
        # 服务端监听状态
        self.server_stop = None
        self.server_thread = None
        self.is_listening = False
        self.pair_code = core.load_pair_code()
        # 本机实际监听端口(握手时告知对方, 供对方保存本机为已配对设备)
        self.local_port = None
        # 同步进行中标记(避免重复同步)
        self.syncing = False
        # 多设备顺序同步队列
        self._sync_queue = []

        self._build(add_page("目录数据同步器"))
        self._refresh_device_list()
        # 自动启动监听
        self._auto_listen()
        # 首次在线探测 + 启动 60 秒周期监控
        self._refresh_online_status()
        self._start_online_monitor()

    def _build(self, page):
        """构建页签: 连接信息区 + 配置区 + 日志进度区。"""
        # ===== 顶部: 本机连接信息 + 设备选择 =====
        conn_frame = ttk.LabelFrame(page, text="设备连接")
        conn_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        # 本机连接信息(自动监听后填充)
        info_row = ttk.Frame(conn_frame)
        info_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(info_row, text="本机连接信息:").pack(side=tk.LEFT)
        self.conn_info_var = tk.StringVar(value="正在启动监听...")
        self.entry_conn_info = ttk.Entry(info_row, textvariable=self.conn_info_var, width=42)
        self.entry_conn_info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(info_row, text="一键复制", command=self._copy_conn_info).pack(side=tk.LEFT, padx=2)
        self.listen_status = ttk.Label(info_row, text="启动中...", foreground="#888")
        self.listen_status.pack(side=tk.LEFT, padx=6)

        # 设备管理入口(连接新设备); 同步历史已移至同步数据区按钮行
        dev_row = ttk.Frame(conn_frame)
        dev_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(dev_row, text="连接设备信息管理", command=self._open_device_dialog).pack(side=tk.LEFT, padx=2)

        # ===== 目标设备(可多选, 带在线状态) =====
        self._build_device_list_module(page)

        # ===== 中部: 同步数据区 =====
        cfg_frame = ttk.LabelFrame(page, text="同步数据")
        cfg_frame.pack(fill=tk.X, padx=8, pady=4)

        src_row = ttk.Frame(cfg_frame)
        src_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(src_row, text="源路径(本机):").pack(side=tk.LEFT)
        self.entry_src = ttk.Entry(src_row)
        self.entry_src.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(src_row, text="选目录...", command=self._browse_src).pack(side=tk.LEFT, padx=2)
        ttk.Button(src_row, text="选文件...", command=self._browse_src_file).pack(side=tk.LEFT, padx=2)

        dst_row = ttk.Frame(cfg_frame)
        dst_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(dst_row, text="目标目录:").pack(side=tk.LEFT)
        self.entry_dst = ttk.Entry(dst_row)
        self.entry_dst.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Label(dst_row, text="(对方机器上的路径, 手动输入)", foreground="#888").pack(side=tk.LEFT, padx=4)

        btn_row = ttk.Frame(cfg_frame)
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.btn_sync = ttk.Button(btn_row, text="开始同步", command=self._on_sync)
        self.btn_sync.pack(side=tk.LEFT)
        self._make_link(btn_row, "同步历史", self._show_history).pack(side=tk.LEFT, padx=(10, 0), pady=2)

        # ===== 底部: 进度 + 日志 =====
        log_frame = ttk.LabelFrame(page, text="进度与日志")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 文件级进度条
        self.progress = ttk.Progressbar(log_frame, mode="determinate")
        self.progress.pack(fill=tk.X, padx=8, pady=(6, 2))
        # 当前文件标签 + 清空日志按钮
        cur_row = ttk.Frame(log_frame)
        cur_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.lbl_cur = ttk.Label(cur_row, text="当前: -", foreground="#555")
        self.lbl_cur.pack(side=tk.LEFT)
        ttk.Button(cur_row, text="清空日志", command=self._clear_log).pack(side=tk.RIGHT)

        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.log_text = tk.Text(log_inner, height=16, state=tk.NORMAL,
                                bg=COLOR_TREEVIEW_BG, fg=COLOR_FG,
                                highlightthickness=1, highlightbackground=COLOR_BORDER,
                                borderwidth=0, padx=6, pady=6,
                                font=(FONT_FAMILY, FONT_SIZE - 1))
        vsb = ttk.Scrollbar(log_inner, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(state=tk.DISABLED)

    # ===== 日志/进度 =====

    def _make_link(self, parent, text, command):
        """创建一个超链接样式 Label(蓝色, 鼠标悬停变手型+下划线, 点击触发 command)。"""
        link = tk.Label(parent, text=text, fg=COLOR_LINK, bg=COLOR_BG,
                        cursor="hand2", font=(FONT_FAMILY, FONT_SIZE))
        link.bind("<Button-1>", lambda e: command())
        link.bind("<Enter>", lambda e: link.configure(font=(FONT_FAMILY, FONT_SIZE, "underline")))
        link.bind("<Leave>", lambda e: link.configure(font=(FONT_FAMILY, FONT_SIZE)))
        return link

    def _log(self, text):
        """向日志区追加一行(主线程), 带时间戳。"""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, "[%s] %s\n" % (ts, text))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.ctx.set_status(text, "info")

    def _log_async(self, text):
        """后台线程调用: 投递到主线程追加日志。"""
        self.ctx.root.after(0, lambda: self._log(text))

    def _clear_log(self):
        """清空日志区内容。"""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.ctx.set_status("日志已清空", "info")

    def _set_progress(self, current, total):
        """更新文件级进度条(主线程)。"""
        if total <= 0:
            self.progress["value"] = 0
            return
        self.progress["maximum"] = total
        self.progress["value"] = current

    def _set_progress_async(self, current, total):
        """后台线程调用: 投递到主线程更新进度。"""
        self.ctx.root.after(0, lambda: self._set_progress(current, total))

    def _set_cur_file(self, rel, sent, total):
        """更新当前文件传输标签(主线程)。"""
        if total > 0:
            self.lbl_cur.configure(text="当前: %s  (%s / %s)" % (
                rel, _fmt_size(sent), _fmt_size(total)))
        else:
            self.lbl_cur.configure(text="当前: %s" % rel)

    def _set_cur_file_async(self, rel, sent, total):
        """后台线程调用: 投递到主线程更新当前文件标签。"""
        self.ctx.root.after(0, lambda: self._set_cur_file(rel, sent, total))

    # ===== 自动监听 =====

    def _auto_listen(self):
        """自动启动服务端监听(持久化配对码, 端口 52000..52009 自动选择)。"""
        if self.is_listening:
            return
        self.server_stop = threading.Event()
        self.is_listening = True
        ports = list(range(core.DEFAULT_PORT, core.DEFAULT_PORT + 10))
        self.server_thread = threading.Thread(
            target=core.start_server,
            args=(ports, self.pair_code, "",
                  self._log_async, self._set_progress_async,
                  lambda ok, msg, stats: self.ctx.root.after(
                      0, lambda: self._on_server_done(ok, msg, stats)),
                  lambda port, code: self.ctx.root.after(
                      0, lambda: self._on_listening(port, code)),
                  self.server_stop,
                  lambda ok, msg, stats: self.ctx.root.after(
                      0, lambda: self._on_conn_done(ok, msg, stats))),
            daemon=True,
        )
        self.server_thread.start()

    def _on_listening(self, port, code):
        """监听已启动: 更新本机连接信息显示。"""
        self.local_port = port
        ips, hostname = core.get_local_info()
        # 优先用非回环 IP
        ip = next((x for x in ips if not x.startswith("127.")), ips[0] if ips else "127.0.0.1")
        info = core.format_connection_info(ip, port, code, hostname)
        self.conn_info_var.set(info)
        self.listen_status.configure(text="监听中(端口%d)" % port, foreground="#2b6cb0")
        self._log("服务端: 已自动启动监听 (端口 %d, 配对码 %s)" % (port, code))
        self._log("服务端: 等待对方连接... (把上方连接信息发给对方)")

    def _on_conn_done(self, ok, msg, stats):
        """单个连接处理完成: 刷新设备列表(可能新增对方设备), 记录历史。

        srv 持续监听不重启, 故此处不触发 _auto_listen, 避免与正在监听的 srv 端口冲突。
        """
        # 握手时双方互存了对方为已配对设备, 刷新列表让本机看到新加入的设备
        self._refresh_device_list()
        # 探测连接不记录历史, 也不输出日志(避免刷屏)
        if stats and stats.get("probe"):
            return
        if stats:
            self._record_session(stats, success=ok)
        if ok:
            self._log("服务端: 接收完成 - %s" % msg)
        else:
            self._log("服务端: %s" % msg)

    def _on_server_done(self, ok, msg, stats):
        """服务端监听结束(停止或异常): 重启监听以保持本机可被连接。"""
        self.is_listening = False
        if not ok:
            self._log("服务端: %s" % msg)
        # 自动恢复监听(程序仍在运行)
        self.ctx.root.after(300, self._auto_listen)

    def _copy_conn_info(self):
        """一键复制本机连接信息到剪贴板。"""
        info = self.conn_info_var.get().strip()
        if not info or info == "正在启动监听...":
            self.ctx.show_alert("提示", "连接信息尚未就绪, 请稍候")
            return
        self.ctx.clipboard_set_text(info)
        self.ctx.set_status("连接信息已复制", "info")
        messagebox.showinfo("已复制", "连接信息已复制到剪贴板:\n\n%s\n\n发给对方即可。" % info,
                            parent=self.ctx.root)

    # ===== 目录选择 =====

    def _browse_src(self):
        """选择本机源目录。"""
        path = self.ctx.choose_directory("选择源目录", self.entry_src.get())
        if path:
            self.entry_src.delete(0, tk.END)
            self.entry_src.insert(0, path)

    def _browse_src_file(self):
        """选择本机单个源文件(单文件模式: 直接发送该文件)。"""
        path = self.ctx.choose_open_file("选择源文件", directory=self.entry_src.get())
        if path:
            self.entry_src.delete(0, tk.END)
            self.entry_src.insert(0, path)

    # ===== 目标设备模块(多选 + 在线状态) =====

    def _build_device_list_module(self, page):
        """构建目标设备模块: 复选框多选 + 全选/取消全选 + 在线状态展示。"""
        frame = ttk.LabelFrame(page, text="目标设备")
        frame.pack(fill=tk.X, padx=8, pady=4)

        top = ttk.Frame(frame)
        top.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(top, text="勾选要发送的目标设备(支持多选):").pack(side=tk.LEFT)
        ttk.Button(top, text="刷新状态", command=self._refresh_online_status).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="取消全选", command=self._deselect_all).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="全选", command=self._select_all).pack(side=tk.RIGHT, padx=2)

        # 可滚动的设备复选框列表
        list_wrap = ttk.Frame(frame)
        list_wrap.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.dev_canvas = tk.Canvas(list_wrap, height=120, highlightthickness=1,
                                    highlightbackground=COLOR_BORDER,
                                    bg=COLOR_TREEVIEW_BG, borderwidth=0)
        vsb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.dev_canvas.yview)
        self.dev_inner = ttk.Frame(self.dev_canvas)
        self.dev_inner.bind(
            "<Configure>",
            lambda e: self.dev_canvas.configure(scrollregion=self.dev_canvas.bbox("all")))
        self.dev_canvas.create_window((0, 0), window=self.dev_inner, anchor="nw")
        self.dev_canvas.configure(yscrollcommand=vsb.set)
        self.dev_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        # 鼠标滚轮支持(仅当光标在列表内时接管)
        self.dev_canvas.bind("<Enter>",
            lambda e: self.dev_canvas.bind_all("<MouseWheel>", self._on_dev_wheel))
        self.dev_canvas.bind("<Leave>",
            lambda e: self.dev_canvas.unbind_all("<MouseWheel>"))

        self._device_rows = []
        self._online_refreshing = False

    def _on_dev_wheel(self, event):
        """目标设备列表鼠标滚轮滚动。"""
        self.dev_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _refresh_device_list(self):
        """从 devices.json 重建目标设备复选框列表, 保留已有勾选与在线状态(不触发探测)。"""
        # 保留重建前的勾选状态与在线状态, 便于增量加入新设备时无缝衔接
        prev_selected = set()
        prev_status = {}
        for r in getattr(self, "_device_rows", []):
            d = r["device"]
            key = (d.get("ip"), d.get("port"))
            if r["var"].get():
                prev_selected.add(key)
            prev_status[key] = r["status_lbl"].cget("text")

        for w in self.dev_inner.winfo_children():
            w.destroy()
        self._device_rows = []
        devices = core.load_devices()
        self._devices = devices
        for i, d in enumerate(devices):
            key = (d.get("ip"), d.get("port"))
            row = ttk.Frame(self.dev_inner)
            row.pack(fill=tk.X, padx=4, pady=1)
            # 勾选状态: 沿用之前的; 若之前无任何勾选则默认选第一个
            default_sel = (i == 0 and not prev_selected)
            var = tk.BooleanVar(value=(key in prev_selected or default_sel))
            # 用经典 tk.Checkbutton: Windows 下选中显示对勾(✓), 而非 clam 主题的叉号
            tk.Checkbutton(row, variable=var, bg=COLOR_BG, fg=COLOR_FG,
                           selectcolor=COLOR_BG, activebackground=COLOR_BG,
                           activeforeground=COLOR_FG, highlightthickness=0,
                           bd=0).pack(side=tk.LEFT)
            ttk.Label(row, text="%s  (%s:%s)" % (
                d.get("name", "?"), d.get("ip"), d.get("port"))).pack(side=tk.LEFT, padx=4)
            status_text = prev_status.get(key, "● 检测中")
            if status_text.startswith("● 在线"):
                fg = "#080"
            elif status_text.startswith("● 离线"):
                fg = "#c0392b"
            else:
                fg = "#888"
            status_lbl = ttk.Label(row, text=status_text, foreground=fg)
            status_lbl.pack(side=tk.RIGHT, padx=4)
            self._device_rows.append({"device": d, "var": var, "status_lbl": status_lbl})
        if not devices:
            ttk.Label(self.dev_inner, text="(暂无目标设备, 请点击“连接设备”添加)",
                      foreground="#888").pack(anchor=tk.W, padx=4, pady=6)

    def _get_selected_devices(self):
        """返回勾选的目标设备对象列表。"""
        return [r["device"] for r in self._device_rows if r["var"].get()]

    def _select_all(self):
        """勾选全部目标设备。"""
        for r in self._device_rows:
            r["var"].set(True)

    def _deselect_all(self):
        """取消勾选全部目标设备。"""
        for r in self._device_rows:
            r["var"].set(False)

    def _refresh_online_status(self):
        """触发一次在线探测周期(非阻塞): 并发探测所有设备并统计成功/失败。

        由手动"刷新状态"按钮、新设备连接成功、以及 60 秒后台监控调用。
        不会在被动收到连接时触发, 避免双方互相探测形成乒乓死循环。
        """
        if self._online_refreshing:
            return
        if not self._device_rows:
            return
        self._online_refreshing = True
        for r in self._device_rows:
            r["status_lbl"].configure(text="● 检测中", foreground="#888")
        threading.Thread(target=self._probe_cycle_worker,
                         args=(list(self._device_rows),), daemon=True).start()

    def _probe_cycle_worker(self, rows):
        """后台执行一次探测周期: 并发探测各设备, 统计后投递主线程更新UI与汇总日志。"""
        total = len(rows)
        results = {}
        lock = threading.Lock()

        def probe(r):
            """探测单个设备在线状态。"""
            d = r["device"]
            online, name = core.check_device_online(
                d.get("ip"), d.get("port"), d.get("code"))
            with lock:
                results[id(r)] = (online, name)

        threads = []
        for r in rows:
            t = threading.Thread(target=probe, args=(r,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=6)
        success = sum(1 for r in rows if results.get(id(r), (False,))[0])
        fail = total - success
        self.ctx.root.after(0, lambda: self._on_probe_cycle_done(results, total, success, fail))

    def _on_probe_cycle_done(self, results, total, success, fail):
        """探测周期完成: 更新各设备在线标签, 输出汇总日志。"""
        self._online_refreshing = False
        for r in self._device_rows:
            online, _ = results.get(id(r), (False, None))
            if online:
                r["status_lbl"].configure(text="● 在线", foreground="#080")
            else:
                r["status_lbl"].configure(text="● 离线", foreground="#c0392b")
        # 仅在有设备时输出汇总, 避免空列表刷屏
        if total > 0:
            self._log("在线状态探测: 共探测 %d 次, 成功 %d 次, 失败 %d 次" % (total, success, fail))

    def _start_online_monitor(self):
        """启动后台在线状态监控: 每 60 秒触发一次探测周期。"""
        def loop():
            """监控循环: 60 秒一次, 程序退出时随守护线程结束。"""
            while True:
                time.sleep(60)
                self.ctx.root.after(0, self._refresh_online_status)
        threading.Thread(target=loop, daemon=True).start()

    def _open_device_dialog(self):
        """打开设备管理对话框(连接新设备并保存)。"""
        DeviceDialog(self.ctx, on_changed=self._refresh_device_list,
                     on_connected=self._on_device_connected,
                     my_port=self.local_port, my_code=self.pair_code)

    def _on_device_connected(self, name):
        """新设备连接保存成功: 日志反馈并刷新在线状态。"""
        self._log("连接成功, 已保存 %s 到设备列表" % name)
        self.ctx.set_status("已保存设备 %s" % name, "info")
        self._refresh_device_list()
        self._refresh_online_status()

    # ===== 同步 =====

    def _on_sync(self):
        """开始同步: 校验 -> 逐个目标设备连接传输。"""
        if self.syncing:
            self.ctx.show_alert("提示", "已有同步正在进行")
            return
        src = self.entry_src.get().strip()
        dst = self.entry_dst.get().strip()
        if not src or not os.path.exists(src):
            self.ctx.show_alert("提示", "请选择有效的源文件或目录")
            return
        if not dst:
            self.ctx.show_alert("提示", "请输入目标目录路径")
            return
        devs = self._get_selected_devices()
        if not devs:
            self.ctx.show_alert("提示", "请在“目标设备”区勾选至少一个设备")
            return

        kind = "文件" if os.path.isfile(src) else "目录"
        names = ", ".join("%s(%s:%s)" % (d.get("name"), d.get("ip"), d.get("port")) for d in devs)
        msg = ("确认开始同步?\n\n源%s(本机): %s\n目标目录(对方): %s\n目标设备(%d): %s\n\n"
               "如目标目录非空, 将先备份再同步。" % (kind, src, dst, len(devs), names))
        self.ctx.confirm("确认同步", msg, on_ok=lambda: self._start_sync_queue(devs, src, dst))

    def _start_sync_queue(self, devs, src, dst):
        """初始化多设备同步队列并启动第一个设备。"""
        self.syncing = True
        self.btn_sync.configure(state=tk.DISABLED)
        self._sync_queue = list(devs)
        self._sync_total = len(devs)
        self._log("客户端: 开始同步, 共 %d 个目标设备" % len(self._sync_queue))
        self._sync_next(src, dst)

    def _sync_next(self, src, dst):
        """同步队列中下一个设备(顺序执行, 避免并发 TCP 冲突)。"""
        if not self._sync_queue:
            self.syncing = False
            self.btn_sync.configure(state=tk.NORMAL)
            self._log("客户端: 全部目标设备同步完成")
            self.ctx.set_status("同步完成", "info")
            return
        dev = self._sync_queue.pop(0)
        self._do_sync(dev, src, dst, on_done=lambda: self._sync_next(src, dst))

    def _do_sync(self, dev, src, dst, on_done=None):
        """实际执行单设备同步(后台线程)。"""
        ip, port, code = dev.get("ip"), dev.get("port"), dev.get("code")
        self.progress["value"] = 0
        self.lbl_cur.configure(text="当前: -")
        self._log("客户端: 开始同步 %s -> %s:%s" % (src, ip, dst))
        start_ts = time.time()

        def need_backup_callback(target_dir):
            """目标非空时由主线程弹窗确认是否备份。"""
            decision = {"ok": False}
            evt = threading.Event()

            def ask():
                """主线程弹窗。"""
                ok = messagebox.askyesno(
                    "目标目录非空",
                    "目标目录非空:\n  %s\n\n将先备份为 zip 再同步, 是否继续?" % target_dir,
                    parent=self.ctx.root)
                decision["ok"] = ok
                evt.set()

            self.ctx.root.after(0, ask)
            evt.wait()
            return decision["ok"]

        def on_file_progress(rel, sent, total):
            """单文件字节进度。"""
            self._set_cur_file_async(rel, sent, total)

        self.ctx.run_thread(
            core.connect_and_sync, ip, port, code, src, dst,
            self._log_async, self._set_progress_async, need_backup_callback,
            on_file_progress,
            self.local_port, self.pair_code,
            on_result=lambda stats: self._on_sync_done(stats, dev, src, dst, start_ts, on_done),
            on_error=lambda err: self._on_sync_error(err, dev, src, dst, start_ts, on_done),
        )

    def _on_sync_done(self, stats, dev, src, dst, start_ts, on_done=None):
        """单设备同步完成: 记录历史, 输出汇总, 触发下一个设备。"""
        self.lbl_cur.configure(text="当前: -")
        if stats:
            stats["src_dir"] = src
            self._record_session(stats, success=True)
            # 多设备同步时不弹窗, 仅记日志, 避免连续弹窗打断; 单设备仍弹窗提示
            multi = getattr(self, "_sync_total", 1) and self._sync_total > 1
            self._log_summary(stats, suppress_alert=multi)
        else:
            self._log("同步完成(无统计)")
        if on_done:
            on_done()

    def _on_sync_error(self, error, dev, src, dst, start_ts, on_done=None):
        """单设备同步失败: 记录失败会话, 询问是否继续剩余设备。"""
        elapsed = time.time() - start_ts
        session = {
            "direction": "发送",
            "peer": dev.get("name", "?"),
            "src_dir": src,
            "target_dir": dst,
            "files_total": 0, "files_sent": 0, "files_skipped": 0,
            "bytes": 0, "elapsed": elapsed, "backup_zip": None,
        }
        self._record_session(session, success=False, error=str(error))
        self._log("同步失败 [%s]: %s" % (dev.get("name", "?"), error))
        # 仍有剩余设备时询问是否继续
        if self._sync_queue:
            remain = len(self._sync_queue)
            if not messagebox.askyesno(
                    "同步失败",
                    "设备 %s 同步失败:\n%s\n\n是否继续剩余 %d 个设备?" % (dev.get("name", "?"), error, remain),
                    parent=self.ctx.root):
                self._sync_queue = []
        else:
            self.ctx.show_alert("同步失败", str(error))
        if on_done:
            on_done()

    # ===== 历史记录 =====

    def _record_session(self, stats, success, error=None):
        """把一次同步会话写入 sync_log.json。"""
        ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session = {
            "time": ts_str,
            "direction": stats.get("direction", "?"),
            "peer": stats.get("peer", "?"),
            "src_dir": stats.get("src_dir", ""),
            "target_dir": stats.get("target_dir", ""),
            "files_total": stats.get("files_total", 0),
            "files_sent": stats.get("files_sent", 0),
            "files_skipped": stats.get("files_skipped", 0),
            "bytes": stats.get("bytes", 0),
            "elapsed": round(stats.get("elapsed", 0), 2),
            "backup_zip": stats.get("backup_zip"),
            "success": success,
            "error": error,
        }
        core.append_sync_log(session)

    def _log_summary(self, stats, suppress_alert=False):
        """输出同步汇总日志。suppress_alert=True 时只记日志不弹窗。"""
        ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "========== 同步完成 ==========",
            "时间: %s" % ts_str,
            "方向: %s  对方: %s" % (stats.get("direction", "?"), stats.get("peer", "?")),
            "文件: 共 %d 个, 传输 %d 个, 跳过 %d 个" % (
                stats.get("files_total", 0), stats.get("files_sent", 0),
                stats.get("files_skipped", 0)),
            "数据量: %s" % _fmt_size(stats.get("bytes", 0)),
            "耗时: %.2f 秒" % stats.get("elapsed", 0),
        ]
        if stats.get("backup_zip"):
            lines.append("备份: %s" % stats["backup_zip"])
        else:
            lines.append("备份: 无(目标为空或未备份)")
        lines.append("状态: 成功")
        for ln in lines:
            self._log(ln)
        if not suppress_alert:
            self.ctx.show_alert("同步完成",
                                "同步完成!\n\n%s" % "\n".join(lines[1:]))

    def _show_history(self):
        """弹出同步历史记录对话框。"""
        HistoryDialog(self.ctx)


# ==================================================================
# 辅助: 字节数格式化
# ==================================================================
def _fmt_size(n):
    """把字节数格式化为人类可读字符串。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f PB" % n


# ==================================================================
# 设备管理对话框(连接目标 / 已配对设备)
# ==================================================================
class DeviceDialog:
    """设备管理对话框: 连接到目标设备 / 已配对设备。"""

    def __init__(self, ctx, on_changed=None, on_connected=None, my_port=None, my_code=None):
        """构建设备管理 Toplevel。"""
        self.ctx = ctx
        self.on_changed = on_changed
        # 连接保存成功后的反馈回调(由主界面日志展示, 避免连续弹窗)
        self.on_connected = on_connected
        # 本机连接信息, 探测握手时告知对方以便双向保存为已配对设备
        self.my_port = my_port
        self.my_code = my_code

        self.dlg = tk.Toplevel(ctx.root)
        self.dlg.title("设备管理")
        self.dlg.geometry("540x420")
        self.dlg.transient(ctx.root)
        self.dlg.grab_set()

        nb = ttk.Notebook(self.dlg)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._build_connect(nb)
        self._build_paired(nb)

    def _build_connect(self, nb):
        """分区1: 连接到目标设备。"""
        page = ttk.Frame(nb)
        nb.add(page, text="连接到目标设备")

        ttk.Label(page, text="对方连接信息:").pack(anchor=tk.W, padx=10, pady=(10, 4))
        ttk.Label(page, text="格式: IP:端口:配对码  (例 192.168.1.10:52000:ABC123)",
                  foreground="#888").pack(anchor=tk.W, padx=10, pady=(0, 6))

        self.conn_info = tk.StringVar()
        info_row = ttk.Frame(page)
        info_row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Entry(info_row, textvariable=self.conn_info, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(info_row, text="一键粘贴识别", command=self._paste_conn_info).pack(side=tk.LEFT, padx=6)

        ttk.Label(page, text="对方设备名(可选, 留空用对方主机名):").pack(anchor=tk.W, padx=10, pady=(8, 2))
        self.conn_name = tk.StringVar()
        ttk.Entry(page, textvariable=self.conn_name, width=30).pack(anchor=tk.W, padx=10, pady=(0, 6))

        self.status_lbl = ttk.Label(page, text="", foreground="#2b6cb0")
        self.status_lbl.pack(anchor=tk.W, padx=10, pady=4)

        ttk.Button(page, text="连接并保存", command=self._do_connect).pack(anchor=tk.W, padx=10, pady=8)

    def _paste_conn_info(self):
        """一键粘贴剪贴板内容并自动识别连接信息。"""
        try:
            text = self.ctx.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("提示", "剪贴板为空或无法读取", parent=self.dlg)
            return
        if not text or not text.strip():
            messagebox.showwarning("提示", "剪贴板内容为空", parent=self.dlg)
            return
        parsed = core.parse_connection_info(text)
        if not parsed:
            self.conn_info.set(text.strip())
            messagebox.showwarning("识别失败",
                                   "剪贴板内容未能识别为连接信息(格式应为 IP:端口:配对码)。\n"
                                   "已把原文填入, 请手动修正后连接。", parent=self.dlg)
            return
        ip, port, code, name = parsed
        self.conn_info.set("%s:%s:%s" % (ip, port, code))
        if name:
            self.conn_name.set(name)
        self.status_lbl.configure(text="已识别: %s:%s 配对码 %s" % (ip, port, code),
                                  foreground="#2b6cb0")
        messagebox.showinfo("识别成功",
                            "已识别连接信息:\n  IP: %s\n  端口: %s\n  配对码: %s%s\n\n"
                            "可点“连接并保存”。" % (ip, port, code,
                                              ("\n  设备名: %s" % name) if name else ""),
                            parent=self.dlg)

    def _do_connect(self):
        """解析连接信息并探测对方设备, 成功则保存到 devices.json。"""
        raw = self.conn_info.get().strip()
        if not raw:
            messagebox.showwarning('提示', '请输入连接信息, 或点“一键粘贴识别”', parent=self.dlg)
            return
        parsed = core.parse_connection_info(raw)
        if not parsed:
            messagebox.showwarning("提示",
                                   "格式应为 IP:端口:配对码  (例 192.168.1.10:52000:ABC123)",
                                   parent=self.dlg)
            return
        ip, port, code, _parsed_name = parsed
        name = self.conn_name.get().strip()

        self.status_lbl.configure(text="正在连接 %s:%s ..." % (ip, port), foreground="#888")

        def on_ok(peer_name):
            """探测成功: 保存设备, 关闭弹窗, 由主界面反馈结果(不再连续弹窗)。"""
            display_name = name or peer_name
            try:
                core.add_device(display_name, ip, port, code)
            except core.SyncError as e:
                messagebox.showerror("保存失败", str(e), parent=self.dlg)
                return
            self.dlg.destroy()
            if self.on_changed:
                self.on_changed()
            if self.on_connected:
                self.on_connected(display_name)

        def on_err(err):
            """探测失败。"""
            self.status_lbl.configure(text="连接失败", foreground="#c0392b")
            messagebox.showerror("连接失败",
                                 "无法连接 %s:%s\n%s\n\n请确认对方已运行本程序且信息正确。" % (ip, port, err),
                                 parent=self.dlg)

        self.ctx.run_thread(core.probe_device, ip, port, code,
                            self.my_port, self.my_code,
                            on_result=on_ok, on_error=on_err)

    def _build_paired(self, nb):
        """分区2: 已配对设备列表。"""
        page = ttk.Frame(nb)
        nb.add(page, text="已配对设备")

        list_frame = ttk.Frame(page)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))
        self.paired_list = tk.Listbox(list_frame, activestyle="none",
                                      font=(FONT_FAMILY, FONT_SIZE))
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.paired_list.yview)
        self.paired_list.configure(yscrollcommand=vsb.set)
        self.paired_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._refresh_paired()

        btns = ttk.Frame(page)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="删除选中", command=self._delete_paired).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="刷新", command=self._refresh_paired).pack(side=tk.LEFT, padx=2)

    def _refresh_paired(self):
        """刷新已配对设备列表。"""
        self.paired_list.delete(0, tk.END)
        self._paired_devices = core.load_devices()
        for d in self._paired_devices:
            self.paired_list.insert(tk.END, "%s | %s:%s" % (
                d.get("name", "?"), d.get("ip"), d.get("port")))

    def _delete_paired(self):
        """删除选中的已配对设备。"""
        sel = self.paired_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的设备", parent=self.dlg)
            return
        d = self._paired_devices[sel[0]]
        if not messagebox.askyesno("确认", "确认删除设备 %s?" % d.get("name"), parent=self.dlg):
            return
        try:
            core.remove_device(d.get("ip"), d.get("port"))
        except core.SyncError as e:
            messagebox.showerror("失败", str(e), parent=self.dlg)
            return
        self._refresh_paired()
        if self.on_changed:
            self.on_changed()


class HistoryDialog:
    """同步历史记录对话框: 显示 sync_log.json 的记录。"""

    def __init__(self, ctx):
        """构建历史记录 Toplevel。"""
        self.ctx = ctx
        self.dlg = tk.Toplevel(ctx.root)
        self.dlg.title("同步历史记录")
        self.dlg.geometry("780x460")
        self.dlg.transient(ctx.root)
        self.dlg.grab_set()

        cols = ("time", "direction", "peer", "files", "bytes", "elapsed", "backup", "success")
        titles = {"time": "时间", "direction": "方向", "peer": "对方",
                  "files": "文件(传/跳)", "bytes": "数据量", "elapsed": "耗时(秒)",
                  "backup": "备份", "success": "状态"}
        widths = {"time": 150, "direction": 60, "peer": 100, "files": 110,
                  "bytes": 90, "elapsed": 80, "backup": 60, "success": 60}

        frame = ttk.Frame(self.dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=titles[c])
            self.tree.column(c, width=widths[c], anchor=tk.W)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("ok", foreground="#080")
        self.tree.tag_configure("fail", foreground="#c0392b")

        btns = ttk.Frame(self.dlg)
        btns.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(btns, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="清空历史", command=self._clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="关闭", command=self.dlg.destroy).pack(side=tk.RIGHT, padx=2)

        self._refresh()

    def _refresh(self):
        """刷新历史列表。"""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for s in core.load_sync_log():
            files = "%d/%d" % (s.get("files_sent", 0), s.get("files_total", 0))
            backup = "有" if s.get("backup_zip") else "无"
            success = "成功" if s.get("success") else "失败"
            tag = "ok" if s.get("success") else "fail"
            self.tree.insert("", tk.END, values=(
                s.get("time", ""),
                s.get("direction", ""),
                s.get("peer", ""),
                files,
                _fmt_size(s.get("bytes", 0)),
                "%.1f" % s.get("elapsed", 0),
                backup,
                success,
            ), tags=(tag,))

    def _clear(self):
        """清空历史记录。"""
        if not messagebox.askyesno("确认", "确认清空全部同步历史?", parent=self.dlg):
            return
        try:
            with open(core.SYNC_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
        self._refresh()
