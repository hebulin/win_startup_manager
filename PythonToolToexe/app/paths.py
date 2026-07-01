# -*- coding: utf-8 -*-
"""路径工具：获取程序所在目录（兼容 PyInstaller 打包）与各数据文件路径。

打包成 exe 后，json 数据文件需落在 exe 同目录（而非临时解包目录），
因此统一通过 get_app_dir 取基准目录。
"""

import os
import sys


def get_app_dir():
    """获取程序所在目录，兼容 PyInstaller 打包后的 exe 环境。

    - 打包成 exe 后运行：sys.executable 指向 exe 自身，取其所在目录。
    - 源码直接运行时：取脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        # 打包成 exe 后运行：sys.executable 指向 exe 自身，取其所在目录
        return os.path.dirname(sys.executable)
    # 源码直接运行时，取脚本所在目录
    return os.path.dirname(os.path.abspath(__file__))


def get_aliases_path():
    """获取 aliases.json 的完整路径（与 exe/脚本同目录），用于保存启动项别名映射。"""
    return os.path.join(get_app_dir(), "aliases.json")


def get_deleted_path():
    """获取 deleted_startup.json 的完整路径，用于记录被删除的启动项历史。"""
    return os.path.join(get_app_dir(), "deleted_startup.json")
