# -*- coding: utf-8 -*-
r"""
开机启动管理器
功能：在 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 下管理开机启动项。
依赖：仅使用 Python 标准库（tkinter、os、json、winreg）。
运行：python startup_manager.py
"""

import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import winreg

# 注册表 Run 键的固定路径（HKCU 下，不需要管理员权限）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# 需要扫描的可执行文件扩展名
TARGET_EXTS = (".exe", ".bat", ".cmd")


def get_aliases_path():
    """获取 aliases.json 的完整路径（与本脚本同目录）"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "aliases.json")


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


def browse_directory(entry_dir):
    """打开目录选择对话框，并把所选目录填入输入框"""
    folder = filedialog.askdirectory(title="选择目标目录")
    if folder:
        entry_dir.delete(0, tk.END)
        entry_dir.insert(0, folder)


def scan_directory(entry_dir, listbox_candidates):
    """扫描所选目录下的 .exe/.bat/.cmd 文件，把完整路径显示在候选列表中"""
    directory = entry_dir.get().strip()
    if not directory or not os.path.isdir(directory):
        messagebox.showwarning("提示", "请先选择有效的目录。")
        return

    # 先清空旧列表
    listbox_candidates.delete(0, tk.END)
    found_files = []

    try:
        # 仅扫描目录当前层级（不递归子目录）
        for name in os.listdir(directory):
            full_path = os.path.join(directory, name)
            if os.path.isfile(full_path):
                ext = os.path.splitext(name)[1].lower()
                if ext in TARGET_EXTS:
                    found_files.append(full_path)
    except Exception as e:
        messagebox.showerror("扫描失败", f"读取目录失败：\n{e}")
        return

    if not found_files:
        messagebox.showinfo("提示", "该目录下没有找到可执行文件。")
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
    """把选中文件写入注册表 Run 键，并保存别名映射"""
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
    # 添加成功后自动刷新下方列表
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
                tree_startup.insert(
                    "", tk.END, values=(name, value, "", "")
                )
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


def remove_startup(tree_startup):
    """删除选中的启动项：删除注册表值 + 删除别名记录，并刷新列表"""
    selected = tree_startup.selection()
    if not selected:
        messagebox.showwarning("提示", "请先选中要取消的启动项。")
        return

    aliases = load_aliases()
    changed = False

    for item in selected:
        # 从表格第一列读取启动项名称
        values = tree_startup.item(item, "values")
        name = values[0]

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
            changed = True

    # 只有别名确实变化时才回写
    if changed:
        save_aliases(aliases)

    messagebox.showinfo("成功", "已取消选中的启动项。")
    refresh_startup_list(tree_startup)


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

    # ========== 1. 目录选择区 ==========
    frame_dir = tk.LabelFrame(root, text="目录选择")
    frame_dir.pack(fill=tk.X, padx=8, pady=(8, 4))

    tk.Label(frame_dir, text="目标目录：").grid(row=0, column=0, padx=5, pady=8, sticky=tk.W)
    entry_dir = tk.Entry(frame_dir)
    entry_dir.grid(row=0, column=1, padx=5, pady=8, sticky=tk.EW)
    btn_browse = tk.Button(frame_dir, text="浏览...", command=lambda: browse_directory(entry_dir))
    btn_browse.grid(row=0, column=2, padx=5, pady=8)
    btn_scan = tk.Button(frame_dir, text="扫描", command=lambda: scan_directory(entry_dir, listbox_candidates))
    btn_scan.grid(row=0, column=3, padx=5, pady=8)
    # 让输入框所在列随窗口拉伸
    frame_dir.columnconfigure(1, weight=1)

    # ========== 2. 候选文件区 ==========
    frame_candidates = tk.LabelFrame(root, text="目录中的可执行文件")
    frame_candidates.pack(fill=tk.BOTH, padx=8, pady=4)

    listbox_candidates = tk.Listbox(frame_candidates, height=6)
    listbox_candidates.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # ========== 3. 添加启动区 ==========
    frame_add = tk.LabelFrame(root, text="设置别名（可选）")
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

    # ========== 4. 当前启动项区 ==========
    frame_startup = tk.LabelFrame(root, text="当前开机启动项（HKCU）")
    frame_startup.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

    # 使用 Treeview 显示四列：启动项名称 / 程序路径 / 别名 / 备注
    columns = ("name", "path", "alias", "remark")
    tree_startup = ttk.Treeview(frame_startup, columns=columns, show="headings", height=8)
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
    frame_startup_btns = tk.Frame(root)
    frame_startup_btns.pack(fill=tk.X, padx=8, pady=(0, 8))
    tk.Button(frame_startup_btns, text="刷新列表", command=lambda: refresh_startup_list(tree_startup)).pack(side=tk.LEFT, padx=5)
    tk.Button(frame_startup_btns, text="取消选中启动项", command=lambda: remove_startup(tree_startup)).pack(side=tk.LEFT, padx=5)

    # 程序启动时先刷新一次列表
    refresh_startup_list(tree_startup)

    # 进入主事件循环
    root.mainloop()
