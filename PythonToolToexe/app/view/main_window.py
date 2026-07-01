# -*- coding: utf-8 -*-
"""主窗口：tkinter 版。

采用 ttk.Notebook 承载各功能页签，底部 ttk.Label 作为状态栏。
功能包通过 register(add_page, ctx) 注册页面，add_page(label) 返回一个 ttk.Frame 供其填充。
"""

import webbrowser
import tkinter as tk
from tkinter import ttk

from app.config import APP_NAME, APP_VERSION, PROJECT_URL, WINDOW_WIDTH, WINDOW_HEIGHT
from app.view.theme import apply_theme, COLOR_LINK, COLOR_BG
from app.view.context import FeatureContext
from app.features.markdown_tools import view as markdown_view
from app.features.startup_manager import view as startup_view
from app.features.default_apps import view as default_apps_view
from app.features.dir_sync import view as dir_sync_view


class MainWindow:
    """应用主窗口：组装各功能页签与状态栏。"""

    def __init__(self, root):
        """初始化主窗口：尺寸、标题、Notebook、状态栏、页面装配。"""
        self.root = root
        root.title(APP_NAME)
        root.geometry("{0}x{1}".format(WINDOW_WIDTH, WINDOW_HEIGHT))
        root.minsize(860, 560)

        # 状态栏（先建，供 ctx 使用），位于底部
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = ttk.Label(root, textvariable=self.status_var,
                                      style="Status.TLabel", anchor="w")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        # 页签容器
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 功能上下文：共享给 feature view
        self.ctx = FeatureContext(root, self.status_var, self.status_label)

        def add_page(label):
            """feature view 注册页面的回调：创建一个 ttk.Frame 加入 Notebook 并返回。"""
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=label)
            return frame

        # 注册各功能页签
        markdown_view.register(add_page, self.ctx)
        startup_view.register(add_page, self.ctx)
        default_apps_view.register(add_page, self.ctx)
        dir_sync_view.register(add_page, self.ctx)

        # 关于页由主窗口自己构造
        self._build_about(add_page("关于"))

    def _build_about(self, page):
        """构建关于页：标题 + 版本 + 项目地址 + 打开/复制按钮。"""
        # 顶部留白
        ttk.Frame(page).pack(fill=tk.BOTH, expand=True)

        center = ttk.Frame(page)
        center.pack()

        title = ttk.Label(center, text=APP_NAME,
                          font=("Microsoft YaHei", 20, "bold"))
        title.pack(pady=(0, 8))

        version = ttk.Label(center, text="版本号：v{0}".format(APP_VERSION))
        version.pack(pady=(0, 16))

        url_label = ttk.Label(center, text=PROJECT_URL, foreground=COLOR_LINK,
                              cursor="hand2")
        url_label.pack(pady=(0, 16))
        # 点击链接也可打开
        url_label.bind("<Button-1>", lambda _e: self._open_url())

        btn_layout = ttk.Frame(center)
        btn_layout.pack()
        ttk.Button(btn_layout, text="在浏览器中打开",
                   command=self._open_url).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_layout, text="复制地址",
                   command=self._copy_url).pack(side=tk.LEFT, padx=4)

        # 底部留白
        ttk.Frame(page).pack(fill=tk.BOTH, expand=True)

    def _open_url(self):
        """用系统默认浏览器打开项目地址。"""
        if webbrowser.open(PROJECT_URL):
            self.ctx.set_status("已打开项目主页", "info")
        else:
            self.ctx.set_status("打开浏览器失败", "error")

    def _copy_url(self):
        """把项目地址写入系统剪贴板。"""
        try:
            self.ctx.clipboard_set_text(PROJECT_URL)
            self.ctx.set_status("项目地址已复制到剪贴板", "info")
        except Exception as e:
            self.ctx.set_status("复制地址失败：{0}".format(e), "error")


def main():
    """tkinter 应用入口：创建 Tk 根窗口、应用主题、装配主窗口并进入事件循环。"""
    root = tk.Tk()
    apply_theme(root)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
