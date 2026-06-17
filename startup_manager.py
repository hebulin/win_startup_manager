# -*- coding: utf-8 -*-
r"""
开机启动管理器
功能：在 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 下管理开机启动项。
依赖：仅使用 Python 标准库（tkinter、os、sys、json、threading、datetime、webbrowser、winreg）。
运行：python startup_manager.py
打包：pyinstaller --onefile --windowed startup_manager.py
"""

import os
import sys
import json
import threading
import datetime
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import winreg

# 注册表 Run 键的固定路径（HKCU 下，不需要管理员权限）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# 需要扫描的可执行文件扩展名
TARGET_EXTS = (".exe", ".bat", ".cmd")

# 程序版本号与项目地址（用于“关于”选项卡展示）
APP_VERSION = "1.0.1"
PROJECT_URL = "https://github.com/hebulin/win_startup_manager"


def get_app_dir():
    """获取程序所在目录，兼容 PyInstaller 打包后的 exe 环境"""
    if getattr(sys, "frozen", False):
        # 打包成 exe 后运行：sys.executable 指向 exe 自身，取其所在目录
        return os.path.dirname(sys.executable)
    # 源码直接运行时，取脚本所在目录
    return os.path.dirname(os.path.abspath(__file__))


def get_aliases_path():
    """获取 aliases.json 的完整路径（与 exe/脚本同目录）"""
    return os.path.join(get_app_dir(), "aliases.json")


def get_deleted_path():
    """获取 deleted_startup.json 的完整路径，用于记录被删除的启动项"""
    return os.path.join(get_app_dir(), "deleted_startup.json")


def load_aliases():
    """读取 aliases.json，文件不存在或格式错误时返回空字典"""
    path = get_aliases_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 只接受字典结构
            if isinstance(data, dict):
                return data
            return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception:
        # 其他异常也返回空字典，避免闪退
        return {}


def save_aliases(aliases):
    """把别名字典写入 aliases.json（结构为 {启动项名称: 别名}）"""
    path = get_aliases_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(aliases, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showerror("保存失败", f"写入 aliases.json 失败：\n{e}")


def load_deleted():
    """读取 deleted_startup.json，文件不存在或格式错误时返回空字典"""
    path = get_deleted_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception:
        return {}


def save_deleted(deleted):
    """把删除记录字典写入 deleted_startup.json"""
    path = get_deleted_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(deleted, f, ensure_ascii=False, indent=2)
    except Exception as e:
        messagebox.showerror("保存失败", f"写入 deleted_startup.json 失败：\n{e}")


def record_deleted(name, path, alias):
    """把单个被删除的启动项记录到 deleted_startup.json，便于日后追溯"""
    deleted = load_deleted()
    deleted[name] = {
        "path": path,
        "alias": alias,
        # 记录删除时的本地时间
        "deleted_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_deleted(deleted)


def browse_directory(entry_dir):
    """打开目录选择对话框，并把所选目录填入输入框"""
    folder = filedialog.askdirectory(title="选择目标目录")
    if folder:
        entry_dir.delete(0, tk.END)
        entry_dir.insert(0, folder)


def scan_directory(entry_dir, listbox_candidates, progress_scan, btn_scan):
    """在后台线程中递归扫描所选目录（含子文件夹）下的可执行文件，扫描完成后填入列表"""
    directory = entry_dir.get().strip()
    if not directory or not os.path.isdir(directory):
        messagebox.showwarning("提示", "请先选择有效的目录。")
        return

    # 清空旧列表
    listbox_candidates.delete(0, tk.END)
    # 启动 indeterminate 进度条，并禁用扫描按钮防止重复点击
    progress_scan.start()
    btn_scan.config(state=tk.DISABLED)

    # 后台扫描：放到子线程，避免递归大目录时界面卡死、进度条不动
    def worker():
        found_files = []
        try:
            # os.walk 会自动递归遍历所有子文件夹
            for dirpath, dirnames, filenames in os.walk(directory):
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in TARGET_EXTS:
                        found_files.append(os.path.join(dirpath, fn))
            # 扫描成功：用 after 把结果投递回主线程更新界面
            listbox_candidates.after(
                0, on_scan_done, found_files, None,
                listbox_candidates, progress_scan, btn_scan,
            )
        except Exception as e:
            # 扫描出错：把异常投递回主线程处理
            listbox_candidates.after(
                0, on_scan_done, [], e,
                listbox_candidates, progress_scan, btn_scan,
            )

    # 启动后台线程（daemon=True，程序退出时自动结束）
    threading.Thread(target=worker, daemon=True).start()


def on_scan_done(found_files, error, listbox_candidates, progress_scan, btn_scan):
    """扫描线程结束后，在主线程执行的收尾逻辑：停进度条、填列表"""
    # 停止进度条并恢复按钮
    progress_scan.stop()
    progress_scan["value"] = 0
    btn_scan.config(state=tk.NORMAL)

    if error is not None:
        messagebox.showerror("扫描失败", f"读取目录失败：\n{error}")
        return

    if not found_files:
        messagebox.showinfo("提示", "该目录（含子文件夹）下没有找到可执行文件。")
        return

    # 排序后填入列表框（内部保存完整路径）
    for fp in sorted(found_files):
        listbox_candidates.insert(tk.END, fp)


def on_candidate_select(event, listbox_candidates, entry_alias):
    """选中候选文件时，自动用文件名（不含扩展名）填充别名输入框"""
    selection = listbox_candidates.curselection()
    if not selection:
        return
    full_path = listbox_candidates.get(selection[0])
    file_name = os.path.basename(full_path)
    name_no_ext = os.path.splitext(file_name)[0]
    entry_alias.delete(0, tk.END)
    entry_alias.insert(0, name_no_ext)


def add_to_startup(listbox_candidates, entry_alias, tree_startup):
    """把选中文件写入注册表 Run 键，并保存别名映射（写入前需二次确认）"""
    selection = listbox_candidates.curselection()
    if not selection:
        messagebox.showwarning("提示", "请先在候选列表中选择一个文件。")
        return

    full_path = listbox_candidates.get(selection[0])
    file_name = os.path.basename(full_path)
    name_no_ext = os.path.splitext(file_name)[0]

    alias = entry_alias.get().strip()
    # 启动项名称：别名优先，否则用文件名（不含扩展名）
    run_name = alias if alias else name_no_ext

    # 二次确认：把名称和路径展示给用户核对，取消则不做任何修改
    confirm = messagebox.askokcancel(
        "二次确认",
        f"确认添加以下开机启动项？\n\n"
        f"启动项名称：{run_name}\n"
        f"程序路径：{full_path}",
    )
    if not confirm:
        return

    try:
        # 打开 HKCU 下的 Run 键（需 SET_VALUE 权限）
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        # 写入值，类型为字符串
        winreg.SetValueEx(key, run_name, 0, winreg.REG_SZ, full_path)
        winreg.CloseKey(key)
    except Exception as e:
        messagebox.showerror("添加失败", f"写入注册表失败：\n{e}")
        return

    # 保存别名映射 {启动项名称: 别名}
    aliases = load_aliases()
    aliases[run_name] = alias
    save_aliases(aliases)

    messagebox.showinfo("添加成功", f"已添加开机启动项：\n{run_name}")
    # 添加成功后自动刷新“取消”页的列表
    refresh_startup_list(tree_startup)


def refresh_startup_list(tree_startup):
    """重新读取注册表 Run 键与 aliases.json，刷新当前启动项列表"""
    # 清空表格中已有项
    for item in tree_startup.get_children():
        tree_startup.delete(item)

    # 读取注册表 Run 键下的所有值
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_READ,
        )
        index = 0
        while True:
            try:
                # 逐个枚举值：返回 (名称, 数据, 类型)
                name, value, _ = winreg.EnumValue(key, index)
                # 先插入，别名稍后从 aliases.json 合并
                tree_startup.insert("", tk.END, values=(name, value, "", ""))
                index += 1
            except OSError:
                # 枚举到末尾，退出循环
                break
        winreg.CloseKey(key)
    except FileNotFoundError:
        # Run 键本身不存在
        return
    except Exception as e:
        messagebox.showerror("读取失败", f"读取注册表失败：\n{e}")
        return

    # 合并 aliases.json 中的别名信息，更新第三列
    aliases = load_aliases()
    for item in tree_startup.get_children():
        values = tree_startup.item(item, "values")
        name = values[0]
        path = values[1]
        alias = aliases.get(name, "")
        tree_startup.item(item, values=(name, path, alias, ""))


def remove_startup(tree_startup, history_tree):
    """删除选中的启动项：二次确认后删除注册表值 + 删别名记录 + 记录到删除历史"""
    selected = tree_startup.selection()
    if not selected:
        messagebox.showwarning("提示", "请先选中要取消的启动项。")
        return

    # 收集本次待删除项的信息，用于二次确认
    pending = []
    for item in selected:
        values = tree_startup.item(item, "values")
        pending.append({"name": values[0], "path": values[1], "alias": values[2]})

    # 二次确认：列出名称与路径，取消则直接返回
    detail_lines = "\n".join(
        f"• 名称：{p['name']}　路径：{p['path']}" for p in pending
    )
    confirm = messagebox.askokcancel(
        "二次确认",
        f"确认取消以下开机启动项？此操作不可撤销：\n\n{detail_lines}",
    )
    if not confirm:
        return

    aliases = load_aliases()
    aliases_changed = False

    for item in selected:
        values = tree_startup.item(item, "values")
        name = values[0]
        path = values[1]
        alias = values[2]

        # 删除注册表值
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
        except FileNotFoundError:
            # 值不存在，忽略即可
            pass
        except Exception as e:
            messagebox.showerror("删除失败", f"删除注册表值失败：\n{e}")
            return

        # 删除别名记录
        if name in aliases:
            del aliases[name]
            aliases_changed = True

        # 记录被删除的启动项（保留名称/路径/别名/删除时间）
        record_deleted(name, path, alias)

    # 只有别名确实变化时才回写
    if aliases_changed:
        save_aliases(aliases)

    messagebox.showinfo("成功", "已取消选中的启动项。")
    # 删除成功后刷新当前列表与历史列表
    refresh_startup_list(tree_startup)
    refresh_deleted_list(history_tree)


def refresh_deleted_list(history_tree):
    """重新读取 deleted_startup.json，刷新删除历史表格"""
    # 清空历史表格
    for item in history_tree.get_children():
        history_tree.delete(item)

    deleted = load_deleted()
    # 按删除时间倒序展示（最近删除的排最前）
    items = list(deleted.items())

    def sort_key(kv):
        """以删除时间字符串排序，缺省时排到最后"""
        info = kv[1]
        if isinstance(info, dict):
            return info.get("deleted_at", "")
        return ""

    items.sort(key=sort_key, reverse=True)

    for name, info in items:
        # 兼容异常数据结构
        if isinstance(info, dict):
            path = info.get("path", "")
            alias = info.get("alias", "")
            deleted_at = info.get("deleted_at", "")
        else:
            path = ""
            alias = ""
            deleted_at = ""
        # 四列：启动项名称 / 程序路径 / 别名 / 删除时间
        history_tree.insert("", tk.END, values=(name, path, alias, deleted_at))


def clear_deleted_history(history_tree):
    """清空全部删除历史（二次确认后清空 deleted_startup.json）"""
    deleted = load_deleted()
    if not deleted:
        messagebox.showinfo("提示", "删除历史为空，无需清空。")
        return

    # 二次确认，避免误清空
    confirm = messagebox.askokcancel("二次确认", "确认清空全部删除历史？此操作不可撤销。")
    if not confirm:
        return

    save_deleted({})
    refresh_deleted_list(history_tree)
    messagebox.showinfo("成功", "已清空删除历史。")


def copy_project_url(root):
    """把项目地址复制到系统剪贴板，并弹窗提示"""
    try:
        root.clipboard_clear()
        root.clipboard_append(PROJECT_URL)
        messagebox.showinfo("复制成功", "项目地址已复制到剪贴板。")
    except Exception as e:
        messagebox.showerror("复制失败", f"复制地址失败：\n{e}")


def open_project_url():
    """用系统默认浏览器打开项目地址"""
    try:
        opened = webbrowser.open(PROJECT_URL)
        if not opened:
            # webbrowser.open 失败时给出提示
            messagebox.showwarning("打开失败", f"无法打开浏览器，请手动访问：\n{PROJECT_URL}")
    except Exception as e:
        messagebox.showerror("打开失败", f"打开浏览器失败：\n{e}")


if __name__ == "__main__":
    # 创建主窗口
    root = tk.Tk()
    root.title("开机启动管理器")

    # 窗口大小 700x500，并居中显示
    window_width = 700
    window_height = 500
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    pos_x = (screen_width - window_width) // 2
    pos_y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")

    # ===== 选项卡容器：设置 / 取消 / 历史 / 关于 =====
    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True)

    tab_setup = ttk.Frame(notebook)
    tab_remove = ttk.Frame(notebook)
    tab_history = ttk.Frame(notebook)
    tab_about = ttk.Frame(notebook)
    notebook.add(tab_setup, text="设置开机启动应用")
    notebook.add(tab_remove, text="取消开机启动应用")
    notebook.add(tab_history, text="应用取消历史")
    notebook.add(tab_about, text="关于")

    # ========== Tab1：设置开机启动应用 ==========
    # 1-1 目录选择区
    frame_dir = tk.LabelFrame(tab_setup, text="目录选择")
    frame_dir.pack(fill=tk.X, padx=8, pady=(8, 4))

    tk.Label(frame_dir, text="目标目录：").grid(row=0, column=0, padx=5, pady=8, sticky=tk.W)
    entry_dir = tk.Entry(frame_dir)
    entry_dir.grid(row=0, column=1, padx=5, pady=8, sticky=tk.EW)
    btn_browse = tk.Button(frame_dir, text="浏览...", command=lambda: browse_directory(entry_dir))
    btn_browse.grid(row=0, column=2, padx=5, pady=8)
    btn_scan = tk.Button(
        frame_dir,
        text="扫描",
        command=lambda: scan_directory(entry_dir, listbox_candidates, progress_scan, btn_scan),
    )
    btn_scan.grid(row=0, column=3, padx=5, pady=8)
    # 让输入框所在列随窗口拉伸
    frame_dir.columnconfigure(1, weight=1)

    # 1-2 候选文件区（含扫描进度条）
    frame_candidates = tk.LabelFrame(tab_setup, text="目录中的可执行文件")
    frame_candidates.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

    # 扫描进度条（indeterminate 模式，扫描期间来回滚动）
    progress_scan = ttk.Progressbar(frame_candidates, mode="indeterminate")
    progress_scan.pack(fill=tk.X, padx=5, pady=(5, 0))

    listbox_candidates = tk.Listbox(frame_candidates, height=8)
    listbox_candidates.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # 1-3 添加启动区
    frame_add = tk.LabelFrame(tab_setup, text="设置别名（可选）")
    frame_add.pack(fill=tk.X, padx=8, pady=4)

    tk.Label(frame_add, text="别名：").grid(row=0, column=0, padx=5, pady=8, sticky=tk.W)
    entry_alias = tk.Entry(frame_add)
    entry_alias.grid(row=0, column=1, padx=5, pady=8, sticky=tk.EW)
    btn_add = tk.Button(
        frame_add,
        text="添加为开机启动",
        command=lambda: add_to_startup(listbox_candidates, entry_alias, tree_startup),
    )
    btn_add.grid(row=0, column=2, padx=5, pady=8)
    frame_add.columnconfigure(1, weight=1)

    # 选中候选文件时，自动填充别名（entry_alias 此时已创建）
    listbox_candidates.bind(
        "<<ListboxSelect>>",
        lambda e: on_candidate_select(e, listbox_candidates, entry_alias),
    )

    # ========== Tab2：取消开机启动应用 ==========
    frame_startup = tk.LabelFrame(tab_remove, text="当前开机启动项（HKCU）")
    frame_startup.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

    # 使用 Treeview 显示四列：启动项名称 / 程序路径 / 别名 / 备注
    columns = ("name", "path", "alias", "remark")
    tree_startup = ttk.Treeview(frame_startup, columns=columns, show="headings", height=10)
    tree_startup.heading("name", text="启动项名称")
    tree_startup.heading("path", text="程序路径")
    tree_startup.heading("alias", text="别名")
    tree_startup.heading("remark", text="备注")
    tree_startup.column("name", width=120, anchor=tk.W)
    tree_startup.column("path", width=320, anchor=tk.W)
    tree_startup.column("alias", width=120, anchor=tk.W)
    tree_startup.column("remark", width=80, anchor=tk.W)

    # 给 Treeview 配上垂直滚动条
    scrollbar = ttk.Scrollbar(frame_startup, orient="vertical", command=tree_startup.yview)
    tree_startup.configure(yscrollcommand=scrollbar.set)
    tree_startup.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

    # 当前启动项区的操作按钮
    frame_startup_btns = tk.Frame(tab_remove)
    frame_startup_btns.pack(fill=tk.X, padx=8, pady=(0, 8))
    tk.Button(frame_startup_btns, text="刷新列表", command=lambda: refresh_startup_list(tree_startup)).pack(side=tk.LEFT, padx=5)
    tk.Button(
        frame_startup_btns,
        text="取消选中启动项",
        command=lambda: remove_startup(tree_startup, history_tree),
    ).pack(side=tk.LEFT, padx=5)

    # ========== Tab3：应用取消历史 ==========
    frame_history = tk.LabelFrame(tab_history, text="已取消的启动项历史")
    frame_history.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

    # 历史表格四列：启动项名称 / 程序路径 / 别名 / 删除时间
    history_columns = ("name", "path", "alias", "deleted_at")
    history_tree = ttk.Treeview(frame_history, columns=history_columns, show="headings", height=10)
    history_tree.heading("name", text="启动项名称")
    history_tree.heading("path", text="程序路径")
    history_tree.heading("alias", text="别名")
    history_tree.heading("deleted_at", text="删除时间")
    history_tree.column("name", width=120, anchor=tk.W)
    history_tree.column("path", width=300, anchor=tk.W)
    history_tree.column("alias", width=100, anchor=tk.W)
    history_tree.column("deleted_at", width=140, anchor=tk.W)

    # 历史表格的垂直滚动条
    history_scrollbar = ttk.Scrollbar(frame_history, orient="vertical", command=history_tree.yview)
    history_tree.configure(yscrollcommand=history_scrollbar.set)
    history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
    history_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

    # 历史区的操作按钮
    frame_history_btns = tk.Frame(tab_history)
    frame_history_btns.pack(fill=tk.X, padx=8, pady=(0, 8))
    tk.Button(frame_history_btns, text="刷新历史", command=lambda: refresh_deleted_list(history_tree)).pack(side=tk.LEFT, padx=5)
    tk.Button(
        frame_history_btns,
        text="清空历史",
        command=lambda: clear_deleted_history(history_tree),
    ).pack(side=tk.LEFT, padx=5)

    # ========== Tab4：关于 ==========
    # 用 place 让内容在 tab_about 内垂直水平居中
    about_inner = tk.Frame(tab_about)
    about_inner.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # 标题
    tk.Label(
        about_inner, text="开机启动管理器", font=("Microsoft YaHei", 20, "bold")
    ).grid(row=0, column=0, pady=(0, 25))

    # 版本号
    tk.Label(
        about_inner, text=f"版本号：v{APP_VERSION}", font=("Microsoft YaHei", 12)
    ).grid(row=1, column=0, pady=6)

    # “项目地址：”提示
    tk.Label(
        about_inner, text="项目地址：", font=("Microsoft YaHei", 12)
    ).grid(row=2, column=0, pady=(10, 6))

    # 项目地址，显示为蓝色链接样式，点击用默认浏览器打开
    url_label = tk.Label(
        about_inner,
        text=PROJECT_URL,
        fg="#0645ad",
        cursor="hand2",
        font=("Microsoft YaHei", 11),
    )
    url_label.grid(row=3, column=0, pady=6)
    url_label.bind("<Button-1>", lambda e: open_project_url())

    # 操作按钮：打开浏览器 / 复制地址
    frame_about_btns = tk.Frame(about_inner)
    frame_about_btns.grid(row=4, column=0, pady=20)
    tk.Button(frame_about_btns, text="在浏览器中打开", command=open_project_url).pack(side=tk.LEFT, padx=5)
    tk.Button(frame_about_btns, text="复制地址", command=lambda: copy_project_url(root)).pack(side=tk.LEFT, padx=5)

    # 程序启动时先刷新一次启动项列表与历史
    refresh_startup_list(tree_startup)
    refresh_deleted_list(history_tree)

    # 进入主事件循环
    root.mainloop()
