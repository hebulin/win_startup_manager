# -*- coding: utf-8 -*-
"""应用入口：启动 tkinter 桌面应用。

运行：python main.py
打包：pyinstaller --onefile --noconsole --name ToolBox --clean main.py
"""

import tkinter as tk

from app.view.theme import apply_theme
from app.view.main_window import MainWindow


def main():
    """创建 Tk 根窗口、应用主题、装配主窗口并进入事件循环。"""
    root = tk.Tk()
    apply_theme(root)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
