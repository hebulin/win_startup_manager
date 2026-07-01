# -*- coding: utf-8 -*-
"""开机启动管理 - 业务逻辑层。

仅处理注册表读写、aliases/deleted 历史 JSON 读写与目录扫描，不依赖 tkinter。
所有失败抛 StartupError，由 view 层捕获后弹窗。
"""

import os
import json
import datetime
import winreg

from app.config import RUN_KEY_PATH, TARGET_EXTS
from app.paths import get_aliases_path, get_deleted_path


class StartupError(Exception):
    """开机启动业务异常，由 view 捕获并弹窗。"""


def load_aliases():
    """读取 aliases.json，文件不存在或格式错误时返回空字典。"""
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
        # 其他异常也返回空字典，避免影响读取流程
        return {}


def save_aliases(aliases):
    """把别名字典写入 aliases.json（结构为 {启动项名称: 别名}）。失败抛 StartupError。"""
    path = get_aliases_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(aliases, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 不再弹窗，异常向上抛由 view 处理
        raise StartupError("写入 aliases.json 失败：{0}".format(e))


def load_deleted():
    """读取 deleted_startup.json，文件不存在或格式错误时返回空字典。"""
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
    """把删除记录字典写入 deleted_startup.json。失败抛 StartupError。"""
    path = get_deleted_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(deleted, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise StartupError("写入 deleted_startup.json 失败：{0}".format(e))


def record_deleted(name, path, alias):
    """把单个被删除的启动项记录到 deleted_startup.json，便于日后追溯。"""
    deleted = load_deleted()
    deleted[name] = {
        "path": path,
        "alias": alias,
        # 记录删除时的本地时间
        "deleted_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_deleted(deleted)


def scan_directory(directory):
    """递归扫描所选目录（含子文件夹）下的可执行文件，返回排序后的完整路径列表。

    :raises StartupError: 目录无效时抛出。
    """
    if not directory or not os.path.isdir(directory):
        raise StartupError("请先选择有效的目录。")
    found_files = []
    # os.walk 会自动递归遍历所有子文件夹
    for dirpath, _dirnames, filenames in os.walk(directory):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in TARGET_EXTS:
                found_files.append(os.path.join(dirpath, fn))
    return sorted(found_files)


def add_to_startup(full_path, run_name, alias):
    """把指定程序写入注册表 Run 键，并保存别名映射。

    :param full_path: 程序完整路径。
    :param run_name: 启动项名称（别名优先，否则文件名去扩展名）。
    :param alias: 别名（可为空串）。
    :raises StartupError: 写注册表或保存别名失败时抛出。
    """
    try:
        # 打开 HKCU 下的 Run 键（需 SET_VALUE 权限）
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        # 写入值，类型为字符串
        winreg.SetValueEx(key, run_name, 0, winreg.REG_SZ, full_path)
        winreg.CloseKey(key)
    except OSError as e:
        raise StartupError("写入注册表失败：{0}".format(e))

    # 保存别名映射 {启动项名称: 别名}
    aliases = load_aliases()
    aliases[run_name] = alias
    save_aliases(aliases)


def list_startup():
    """枚举注册表 Run 键并合并 aliases，返回 [{name, path, alias}]。

    :raises StartupError: 读取注册表失败（非键不存在）时抛出。
    """
    result = []
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        index = 0
        while True:
            try:
                # 逐个枚举值：返回 (名称, 数据, 类型)
                name, value, _ = winreg.EnumValue(key, index)
                result.append({"name": name, "path": value, "alias": ""})
                index += 1
            except OSError:
                # 枚举到末尾，退出循环
                break
        winreg.CloseKey(key)
    except FileNotFoundError:
        # Run 键本身不存在，返回空列表
        return result
    except OSError as e:
        raise StartupError("读取注册表失败：{0}".format(e))

    # 合并 aliases.json 中的别名信息
    aliases = load_aliases()
    for row in result:
        row["alias"] = aliases.get(row["name"], "")
    return result


def remove_startup(items):
    """删除选中的启动项：删注册表值 + 删别名记录 + 记录到删除历史。

    :param items: 待删除项列表 [{name, path, alias}]。
    :raises StartupError: 删除注册表值失败时抛出。
    """
    aliases = load_aliases()
    aliases_changed = False

    for item in items:
        name = item["name"]
        path = item.get("path", "")
        alias = item.get("alias", "")

        # 删除注册表值
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
        except FileNotFoundError:
            # 值不存在，忽略即可
            pass
        except OSError as e:
            raise StartupError("删除注册表值失败：{0}".format(e))

        # 删除别名记录
        if name in aliases:
            del aliases[name]
            aliases_changed = True

        # 记录被删除的启动项（保留名称/路径/别名/删除时间）
        record_deleted(name, path, alias)

    # 只有别名确实变化时才回写
    if aliases_changed:
        save_aliases(aliases)


def list_deleted():
    """读取删除历史并按删除时间倒序返回 [{name, path, alias, deleted_at}]。"""
    deleted = load_deleted()

    def sort_key(info):
        """以删除时间字符串排序，缺省时排到最后。"""
        if isinstance(info, dict):
            return info.get("deleted_at", "")
        return ""

    # 按删除时间倒序展示（最近删除的排最前）
    items = list(deleted.items())
    items.sort(key=lambda kv: sort_key(kv[1]), reverse=True)

    result = []
    for name, info in items:
        # 兼容异常数据结构
        if isinstance(info, dict):
            result.append({
                "name": name,
                "path": info.get("path", ""),
                "alias": info.get("alias", ""),
                "deleted_at": info.get("deleted_at", ""),
            })
        else:
            result.append({"name": name, "path": "", "alias": "", "deleted_at": ""})
    return result


def clear_deleted():
    """清空全部删除历史。失败抛 StartupError。"""
    save_deleted({})
