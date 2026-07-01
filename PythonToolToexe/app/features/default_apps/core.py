# -*- coding: utf-8 -*-
r"""默认应用清理 - 业务逻辑层。

仅处理注册表读取/解析、可执行文件版本信息读取、还原与手动设置写入，
不依赖 tkinter。所有失败以异常或返回值形式上报，由 view 层捕获后反馈。

技术说明:
  - Windows 10/11 对 UserChoice 注册表项有 Hash 保护, 直接写 ProgId 会被系统忽略。
  - "还原"采用删除 UserChoice 的方式(完全可靠, 立即生效)。
  - "手动设置"采用删除 UserChoice + 写 HKCU\Software\Classes\<.ext> 默认值的方式,
    优先级仅次于 UserChoice, 删除 UserChoice 后即生效, 避开 Hash 校验。
  - 所有写操作均针对 HKCU(当前用户), 无需管理员权限。
"""

import os
import re
import ctypes
from ctypes import wintypes

import winreg


# ------------------------------------------------------------------
# 注册表常量
# ------------------------------------------------------------------
# FileExts 根路径: 存放用户选择的默认程序(UserChoice)
FILE_EXTS_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
# URL 协议关联根路径
URI_ASSOC_ROOT = r"Software\Microsoft\Windows\Shell\Associations\UriAssociations"
# 当前用户 Classes 根路径: 手动设置默认时写入此处
HKCU_CLASSES_ROOT = r"Software\Classes"

# 需要扫描的常见文件扩展名
SCAN_EXTS = [
    ".pdf", ".doc", ".docx", ".docm", ".rtf",
    ".xls", ".xlsx", ".xlsm", ".csv",
    ".ppt", ".pptx", ".pptm",
    ".txt", ".log",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp3", ".wav", ".flac", ".mp4", ".mkv", ".avi", ".mov",
    ".zip", ".rar", ".7z",
    ".html", ".htm", ".xml",
    ".ofd",
]
# 需要扫描的 URL 协议
SCAN_URIS = ["http", "https", "mailto", "ftp"]

# WPS 识别关键字(用于 ProgId / 路径 / 公司名综合判断)
WPS_KEYWORDS = ["wps", "kingsoft", "金山", "et.", "wpp.", "kdocs", "wpscloud",
                "ksolaunch", "kxinstall", "ksotab", "ksowps", "ksoet", "ksowpp"]
# 较短易误判的关键字, 仅在路径或公司名中出现才算
WPS_SOFT_KEYWORDS = ["et", "wpp"]


def safe_lower(s):
    """字符串安全转小写(兼容 None / 非 str)。"""
    if not s:
        return ""
    try:
        return str(s).lower()
    except Exception:
        return ""


# ==================================================================
# 版本信息读取模块 (ctypes 调用 version.dll, 无需第三方依赖)
# ==================================================================
class VersionInfoReader:
    """通过 version.dll 读取 PE 文件的版本资源(公司/产品/描述等)。"""

    def __init__(self):
        # 加载 version.dll
        self._ver = ctypes.WinDLL("version.dll")
        # GetFileVersionInfoSizeW
        self._ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        self._ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        # GetFileVersionInfoW
        self._ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        self._ver.GetFileVersionInfoW.restype = wintypes.BOOL
        # VerQueryValueW
        self._ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        self._ver.VerQueryValueW.restype = wintypes.BOOL

    def read(self, exe_path):
        """读取指定 exe 的版本信息, 返回字典(CompanyName/FileDescription/ProductName/FileVersion)。"""
        result = {"CompanyName": "", "FileDescription": "", "ProductName": "", "FileVersion": ""}
        if not exe_path or not os.path.exists(exe_path):
            return result
        try:
            size = self._ver.GetFileVersionInfoSizeW(exe_path, None)
            if not size:
                return result
            buf = (ctypes.c_char * size)()
            if not self._ver.GetFileVersionInfoW(exe_path, 0, size, buf):
                return result
            # 读取翻译表, 得到语言/代码页
            p_trans = ctypes.c_void_p()
            trans_len = wintypes.UINT()
            if not self._ver.VerQueryValueW(buf, r"\VarFileInfo\Translation",
                                            ctypes.byref(p_trans), ctypes.byref(trans_len)):
                return result
            # 解析第一个翻译项(语言ID, 代码页)
            trans_arr = ctypes.cast(p_trans, ctypes.POINTER(wintypes.USHORT))
            lang = trans_arr[0]
            codepage = trans_arr[1]
            sub_block = "\\StringFileInfo\\%04x%04x\\" % (lang, codepage)
            # 逐个读取字符串字段
            for field in ("CompanyName", "FileDescription", "ProductName", "FileVersion"):
                p_val = ctypes.c_void_p()
                val_len = wintypes.UINT()
                key = sub_block + field
                if self._ver.VerQueryValueW(buf, key, ctypes.byref(p_val), ctypes.byref(val_len)) and val_len.value:
                    val_ptr = ctypes.cast(p_val, ctypes.POINTER(wintypes.WCHAR))
                    result[field] = val_ptr[:val_len.value].rstrip("\x00")
        except Exception:
            pass
        return result


# 全局单例(避免反复加载 dll)
_version_reader = None


def get_version_reader():
    """获取 VersionInfoReader 全局单例。"""
    global _version_reader
    if _version_reader is None:
        _version_reader = VersionInfoReader()
    return _version_reader


# ==================================================================
# 注册表读取 / 解析模块
# ==================================================================
def read_user_choice(ext):
    """读取文件扩展名对应的用户默认程序 ProgId (UserChoice)。

    返回: ProgId 字符串, 若不存在返回 None。
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"%s\%s\UserChoice" % (FILE_EXTS_ROOT, ext))
        try:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
            return prog_id
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def read_uri_association(proto):
    """读取 URL 协议对应的用户默认程序 ProgId。

    返回: ProgId 字符串, 若不存在返回 None。
    """
    # 优先读取 UriAssociations
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"%s\%s" % (URI_ASSOC_ROOT, proto))
        try:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
            return prog_id
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # 回退: 读 HKCU\Software\Classes\<proto> 默认值
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"%s\%s" % (HKCU_CLASSES_ROOT, proto))
        try:
            val, _ = winreg.QueryValueEx(key, "")
            if val:
                return val
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return None


def resolve_prog_command(prog_id):
    r"""解析 ProgId 对应的 shell open 命令字符串。

    查询顺序: HKCR\<ProgId>\shell\open\command
    返回: 命令字符串, 不存在返回 None。
    """
    try:
        # HKCR 已合并 HKLM + HKCU
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"%s\shell\open\command" % prog_id)
        try:
            cmd, _ = winreg.QueryValueEx(key, "")
            return cmd
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        # 尝试 HKCU\Software\Classes
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"%s\%s\shell\open\command" % (HKCU_CLASSES_ROOT, prog_id))
            try:
                cmd, _ = winreg.QueryValueEx(key, "")
                return cmd
            finally:
                winreg.CloseKey(key)
        except Exception:
            return None
    except Exception:
        return None


def extract_exe_path(cmd):
    """从 shell 命令字符串中提取可执行文件绝对路径。

    处理带引号和不带引号两种情况, 支持环境变量扩展。
    """
    if not cmd:
        return ""
    cmd = cmd.strip()
    # 带引号: "C:\path\app.exe" arg1
    m = re.match(r'^"([^"]+\.exe)"', cmd, re.IGNORECASE)
    if m:
        return os.path.expandvars(m.group(1))
    # 不带引号: C:\path\app.exe arg1
    m = re.match(r'^([^\s]+\.exe)', cmd, re.IGNORECASE)
    if m:
        return os.path.expandvars(m.group(1))
    # 兜底: 第一段
    first = cmd.split()[0] if cmd.split() else ""
    if first:
        return os.path.expandvars(first)
    return ""


def get_prog_display_name(prog_id):
    """获取 ProgId 的友好显示名(其默认值或 ProgId 本身)。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id)
        try:
            val, _ = winreg.QueryValueEx(key, "")
            if val:
                return val
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return prog_id


def is_wps(prog_id, exe_path, company, product):
    """综合判断该默认应用是否由 WPS / 金山占用或捆绑。

    判断依据: ProgId、exe 路径、公司名、产品名中是否含 WPS 相关关键字。
    """
    blob = " ".join([safe_lower(prog_id), safe_lower(exe_path),
                     safe_lower(company), safe_lower(product)])
    # 强关键字命中即判定
    for kw in WPS_KEYWORDS:
        if kw in blob:
            return True
    # 软关键字: 仅在 exe 路径或公司名中匹配才算(避免误判)
    soft_blob = safe_lower(exe_path) + " " + safe_lower(company) + " " + safe_lower(product)
    for kw in WPS_SOFT_KEYWORDS:
        if kw in soft_blob:
            # 进一步要求路径或公司里同时出现 kso / kingsoft / 金山 / wps 之一才确认
            if any(x in soft_blob for x in ["kso", "kingsoft", "金山", "wps"]):
                return True
    return False


# ==================================================================
# 关联项数据模型
# ==================================================================
class AssocItem:
    """一个默认应用关联项的数据载体。"""

    def __init__(self, kind, identifier, prog_id):
        self.kind = kind                  # "文件" 或 "协议"
        self.identifier = identifier      # 扩展名(.pdf) 或协议(http)
        self.prog_id = prog_id            # UserChoice ProgId
        self.exe_path = ""                # 可执行文件路径
        self.company = ""                 # 公司名
        self.description = ""             # 文件描述(常用作软件名)
        self.product = ""                 # 产品名
        self.is_wps = False               # 是否 WPS 占用
        self.resolve()                    # 立即解析详情

    def resolve(self):
        """解析 ProgId -> exe 路径 -> 版本信息, 并判定 WPS。"""
        if not self.prog_id:
            return
        cmd = resolve_prog_command(self.prog_id)
        self.exe_path = extract_exe_path(cmd)
        if self.exe_path:
            ver = get_version_reader().read(self.exe_path)
            self.company = ver.get("CompanyName", "")
            self.description = ver.get("FileDescription", "")
            self.product = ver.get("ProductName", "")
        if not self.description:
            self.description = get_prog_display_name(self.prog_id)
        self.is_wps = is_wps(self.prog_id, self.exe_path, self.company, self.product)


# ==================================================================
# 注册表写入模块(还原 / 手动设置)
# ==================================================================
def delete_user_choice(ext):
    """删除指定扩展名的 UserChoice 项(还原为系统默认)。

    返回 (成功布尔, 消息)。
    """
    sub = r"%s\%s\UserChoice" % (FILE_EXTS_ROOT, ext)
    try:
        # 递归删除该键(其下无子键, 用 DeleteKey 即可)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        return True, "已还原 %s" % ext
    except FileNotFoundError:
        return True, "%s 无用户自定义设置" % ext
    except PermissionError:
        return False, "还原 %s 被拒绝(可能需关闭占用进程或以管理员运行)" % ext
    except Exception as e:
        return False, "还原 %s 失败: %s" % (ext, e)


def delete_uri_association(proto):
    """删除指定协议的用户自定义关联(还原为系统默认)。

    返回 (成功布尔, 消息)。优先删 UriAssociations 下的 ProgId 值。
    """
    sub = r"%s\%s" % (URI_ASSOC_ROOT, proto)
    try:
        try:
            winreg.DeleteValue(winreg.HKEY_CURRENT_USER, sub, "ProgId")
        except FileNotFoundError:
            pass
        # 若键为空则删除键
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except Exception:
            pass
        return True, "已还原 %s 协议" % proto
    except PermissionError:
        return False, "还原 %s 协议被拒绝" % proto
    except Exception as e:
        return False, "还原 %s 协议失败: %s" % (proto, e)


def set_default_for_ext(ext, prog_id):
    r"""手动设置扩展名的默认程序(删除旧 UserChoice + 写 HKCU\Classes)。

    返回 (成功布尔, 消息)。
    此方式避开 UserChoice Hash 校验: 删除 UserChoice 后,
    系统按 HKCU\Software\Classes\<.ext> 默认值解析 ProgId。
    """
    if not prog_id:
        return False, "未指定目标程序"
    try:
        # 1. 先删除旧 UserChoice
        delete_user_choice(ext)
        # 2. 写 HKCU\Software\Classes\<ext> 默认值 = ProgId
        cls_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                   r"%s\%s" % (HKCU_CLASSES_ROOT, ext))
        try:
            winreg.SetValueEx(cls_key, "", 0, winreg.REG_SZ, prog_id)
        finally:
            winreg.CloseKey(cls_key)
        # 3. 写 OpenWithProgids 以便出现在"打开方式"列表
        ow_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  r"%s\%s\OpenWithProgids" % (HKCU_CLASSES_ROOT, ext))
        try:
            winreg.SetValueEx(ow_key, prog_id, 0, winreg.REG_NONE, b"")
        finally:
            winreg.CloseKey(ow_key)
        # 4. 通知系统刷新关联
        notify_shell_change()
        return True, "已设置 %s -> %s" % (ext, prog_id)
    except PermissionError:
        return False, "设置 %s 被拒绝(权限不足)" % ext
    except Exception as e:
        return False, "设置 %s 失败: %s" % (ext, e)


def set_uri_default(proto, prog_id):
    """手动设置 URL 协议的默认程序(写 UriAssociations)。

    返回 (成功布尔, 消息)。
    """
    try:
        # 先删除旧的 UriAssociations 记录, 再写新的
        delete_uri_association(proto)
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                               r"%s\%s" % (URI_ASSOC_ROOT, proto))
        try:
            winreg.SetValueEx(key, "ProgId", 0, winreg.REG_SZ, prog_id)
        finally:
            winreg.CloseKey(key)
        # 同步写 HKCU\Software\Classes\<proto> 默认值
        cls_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                   r"%s\%s" % (HKCU_CLASSES_ROOT, proto))
        try:
            winreg.SetValueEx(cls_key, "", 0, winreg.REG_SZ, "URL:%s" % proto)
        finally:
            winreg.CloseKey(cls_key)
        notify_shell_change()
        return True, "已设置 %s 协议 -> %s" % (proto, prog_id)
    except Exception as e:
        return False, "设置 %s 协议失败: %s" % (proto, e)


def notify_shell_change():
    """通知 Shell 文件关联已变化, 使设置立即生效。"""
    try:
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def list_candidate_progids(ext_or_proto, is_uri=False):
    """枚举某扩展名/协议的候选 ProgId(用于手动设置下拉框)。

    来源: OpenWithProgids 值 + OpenWithList 项。返回去重后的 ProgId 列表。
    """
    candidates = []
    # OpenWithProgids
    if is_uri:
        sub = r"%s\%s" % (URI_ASSOC_ROOT, ext_or_proto)
    else:
        sub = r"%s\%s\OpenWithProgids" % (FILE_EXTS_ROOT, ext_or_proto)
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub)
        try:
            i = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, i)
                    if name:
                        candidates.append(name)
                    i += 1
                except OSError:
                    break
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # OpenWithList(文件)
    if not is_uri:
        sub = r"%s\%s\OpenWithList" % (FILE_EXTS_ROOT, ext_or_proto)
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub)
            try:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        if val:
                            candidates.append(val)
                        i += 1
                    except OSError:
                        break
            finally:
                winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception:
            pass
    # 去重保序
    seen = set()
    result = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    # 补充常见原生 Office / 浏览器 ProgId 以便手动选回
    for fallback in ("Word.Document.12", "Excel.Sheet.12", "PowerPoint.Show.12",
                     "AcroExch.Document.DC", "Acrobat.Document.DC", "txtfile",
                     "htmlfile", "MSEdgeHTM", "ChromeHTML"):
        if fallback not in seen:
            result.append(fallback)
    return result


# ==================================================================
# 扫描入口
# ==================================================================
def scan_all_associations():
    """扫描所有预设扩展名与协议, 返回 AssocItem 列表(仅含被用户自定义的项)。"""
    items = []
    for ext in SCAN_EXTS:
        prog_id = read_user_choice(ext)
        if not prog_id:
            continue  # 未被用户自定义, 跳过(说明未被篡改)
        items.append(AssocItem("文件", ext, prog_id))
    for proto in SCAN_URIS:
        prog_id = read_uri_association(proto)
        if not prog_id:
            continue
        items.append(AssocItem("协议", proto, prog_id))
    return items


def restore_item(item):
    """还原单个关联项(文件删 UserChoice, 协议删 UriAssociations)。

    返回 (成功布尔, 消息)。
    """
    if item.kind == "协议":
        return delete_uri_association(item.identifier)
    return delete_user_choice(item.identifier)


def set_item_default(item, prog_id):
    """手动设置单个关联项的默认程序。

    返回 (成功布尔, 消息)。
    """
    if item.kind == "协议":
        return set_uri_default(item.identifier, prog_id)
    return set_default_for_ext(item.identifier, prog_id)
