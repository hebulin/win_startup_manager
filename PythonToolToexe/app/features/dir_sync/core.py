# -*- coding: utf-8 -*-
r"""目录数据同步器 - 业务逻辑层。

仅处理设备配对 json 读写、TCP 通信、文件递归遍历与传输、目标目录备份，
不依赖 tkinter。所有失败以 SyncError 抛出，由 view 层捕获后反馈。

设计要点:
  - 局域网 TCP 直连，自定义消息帧: 4字节大端长度 + JSON头 + 二进制body。
  - 角色: 目标端=服务端(监听), 源端=客户端(连接并发送文件)。
  - 同步策略: 增量复制, 不删除目标多余文件; 同名且 size+mtime 相同则跳过。
  - 含隐藏文件/目录: os.walk 默认包含, 不主动过滤; Windows 下用 ctypes 还原隐藏属性。
  - 目标非空时先 zip 备份整个目标目录, 再同步。
"""

import os
import sys
import json
import time
import socket
import random
import struct
import zipfile
import datetime
import threading

from app.paths import get_app_dir


# ------------------------------------------------------------------
# 常量
# ------------------------------------------------------------------
# 设备记录文件(与 exe 同目录)
DEVICES_FILE = os.path.join(get_app_dir(), "devices.json")

# 默认监听端口
DEFAULT_PORT = 52000
# 文件传输缓冲区大小
CHUNK_SIZE = 64 * 1024
# 连接超时(秒)
CONNECT_TIMEOUT = 10
# Windows 隐藏文件属性
FILE_ATTRIBUTE_HIDDEN = 0x2


class SyncError(Exception):
    """同步业务异常, 由 view 捕获并弹窗。"""


# 服务端同步流程串行锁: 并发化监听后, 多个同步连接需排队写目标目录,
# 避免并发写同一 target_dir 导致备份竞争/文件交错; probe 不持锁, 不阻塞探测
_sync_lock = threading.Lock()


def _fmt_bytes(n):
    """把字节数格式化为人类可读字符串(如 1.2 MB)。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f PB" % n


# ==================================================================
# 设备管理 (devices.json)
# ==================================================================
def load_devices():
    """读取已配对设备列表, 返回 [{name, ip, port, code}]。文件不存在或格式错误返回 []。"""
    try:
        with open(DEVICES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        return []


def save_devices(devices):
    """把设备列表写入 devices.json。失败抛 SyncError。"""
    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise SyncError("保存设备列表失败: %s" % e)


def add_device(name, ip, port, code):
    """添加或更新一个设备(按 ip+port 去重), 写回 json。"""
    devices = load_devices()
    # 去重: 同 ip+port 视为同一设备, 更新其 name/code
    devices = [d for d in devices if not (d.get("ip") == ip and d.get("port") == port)]
    devices.append({"name": name or ip, "ip": ip, "port": int(port), "code": code})
    save_devices(devices)


def remove_device(ip, port):
    """删除指定 ip+port 的设备, 写回 json。"""
    devices = load_devices()
    devices = [d for d in devices if not (d.get("ip") == ip and d.get("port") == int(port))]
    save_devices(devices)


def get_local_info():
    """获取本机 IPv4 地址列表与主机名。返回 (ip_list, hostname)。"""
    hostname = socket.gethostname()
    ips = []
    try:
        # gethostbyname_ex 返回 (hostname, aliaslist, ipaddrlist)
        _, _, ipaddrlist = socket.gethostbyname_ex(hostname)
        ips = [ip for ip in ipaddrlist if "." in ip]
    except Exception:
        pass
    # 回退: 连接外部地址获取本机出口 IP(不实际发送数据)
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    # 始终包含回环地址便于本机自测
    if "127.0.0.1" not in ips:
        ips.append("127.0.0.1")
    return ips, hostname


def generate_pair_code():
    """生成 6 位配对码(数字+大写字母)。"""
    chars = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choice(chars) for _ in range(6))


# ------------------------------------------------------------------
# 本机配对码持久化(首次随机生成, 之后复用, 便于对方长期保存)
# ------------------------------------------------------------------
PAIR_CODE_FILE = os.path.join(get_app_dir(), "pair_code.json")


def load_pair_code():
    """读取本机持久化配对码, 不存在则生成并保存。返回配对码字符串。"""
    try:
        with open(PAIR_CODE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            code = data.get("code") if isinstance(data, dict) else None
            if code:
                return code
    except Exception:
        pass
    # 生成新的并保存
    code = generate_pair_code()
    try:
        with open(PAIR_CODE_FILE, "w", encoding="utf-8") as f:
            json.dump({"code": code}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return code


# ------------------------------------------------------------------
# 同步历史日志(追加记录每次同步会话)
# ------------------------------------------------------------------
SYNC_LOG_FILE = os.path.join(get_app_dir(), "sync_log.json")


def load_sync_log():
    """读取同步历史日志列表, 最新在前。返回 [session_dict]。"""
    try:
        with open(SYNC_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def append_sync_log(session):
    """追加一条同步会话记录到 sync_log.json (保留最近 200 条)。

    :param session: dict, 含 start_time/end_time/elapsed/direction/peer/
                    files_total/files_sent/files_skipped/bytes/success/backup_zip/target_dir。
    """
    log = load_sync_log()
    log.insert(0, session)
    del log[200:]
    try:
        with open(SYNC_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def format_connection_info(ip, port, code, name=None):
    """格式化连接信息为一行字符串, 便于复制粘贴。

    格式: IP:端口:配对码  (可选附带设备名, 用 | 分隔)
    例: 192.168.1.10:52000:ABC123
        192.168.1.10:52000:ABC123 | MyPC
    """
    base = "%s:%s:%s" % (ip, port, code)
    if name:
        return "%s | %s" % (base, name)
    return base


def parse_connection_info(text):
    """从字符串解析连接信息, 返回 (ip, port, code, name) 或 None。

    支持多种格式:
      - IP:端口:配对码
      - IP:端口:配对码 | 设备名
      - 含其他分隔符或多余空白的容错解析
    """
    if not text:
        return None
    text = text.strip()
    # 去掉可能的前导说明文字, 取首个含 IP:端口:配对码 形态的片段
    import re
    # 匹配 IP:端口:配对码, IP 用 IPv4 或主机名
    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9\-]+):(\d{1,5}):([A-Za-z0-9]{4,8})", text)
    if not m:
        return None
    ip, port_str, code = m.group(1), m.group(2), m.group(3)
    try:
        port = int(port_str)
    except ValueError:
        return None
    if port <= 0 or port > 65535:
        return None
    # 设备名: 取 | 后的内容
    name = None
    if "|" in text:
        after = text.split("|", 1)[1].strip()
        # 去掉尾部标点
        after = after.strip(" \t,，。.")
        if after:
            name = after
    return ip, port, code, name


# ==================================================================
# TCP 消息协议 (length-prefixed: 4字节大端长度 + JSON头 + body)
# ==================================================================
def _send_msg(sock, cmd, meta=None, body=b""):
    """发送一条消息: JSON头(含 cmd/meta/body_len) + 二进制 body。"""
    meta = meta or {}
    header = {"cmd": cmd}
    header.update(meta)
    header_bytes = json.dumps(header, ensure_ascii=False).encode("utf-8")
    # 帧: [4字节 header_len][header json][body]
    sock.sendall(struct.pack(">I", len(header_bytes)) + header_bytes)
    if body:
        sock.sendall(body)


def _recv_exact(sock, n):
    """精确接收 n 字节, 连接断开返回 None。"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_msg(sock):
    """接收一条消息, 返回 (cmd, meta, body)。连接断开返回 (None, None, None)。

    注意: 此函数仅接收 body_len <= MAX_INLINE_BODY 的内联 body;
    大文件 body 走流式收发(_send_file_stream/_recv_file_stream), 不经此函数。
    """
    head_len_bytes = _recv_exact(sock, 4)
    if head_len_bytes is None:
        return None, None, None
    head_len = struct.unpack(">I", head_len_bytes)[0]
    header_bytes = _recv_exact(sock, head_len)
    if header_bytes is None:
        return None, None, None
    header = json.loads(header_bytes.decode("utf-8"))
    cmd = header.get("cmd")
    body_len = header.get("body_len", 0)
    body = b""
    if body_len:
        body = _recv_exact(sock, body_len)
        if body is None:
            return None, None, None
    return cmd, header, body


# 流式文件传输: 头消息不带 body, 之后按 CHUNK_SIZE 流式收发 size 字节
def _send_file_body(sock, file_obj, size, on_progress=None):
    """从 file_obj 流式读取并发送 size 字节(头消息已由调用方发送)。

    :param sock: 已连接 socket。
    :param file_obj: 已打开的二进制文件对象(读模式)。
    :param size: 文件总字节数。
    :param on_progress: 可选, 进度回调 (sent_bytes, total_bytes)。
    """
    sent = 0
    while sent < size:
        chunk = file_obj.read(CHUNK_SIZE)
        if not chunk:
            break
        sock.sendall(chunk)
        sent += len(chunk)
        if on_progress is not None:
            on_progress(sent, size)


def _recv_file_stream(sock, size, dest_path, on_progress=None):
    """从 sock 流式接收 size 字节, 直接写入 dest_path 文件。

    :param sock: 已连接 socket。
    :param size: 文件总字节数。
    :param dest_path: 目标文件写入路径。
    :param on_progress: 可选, 进度回调 (received_bytes, total_bytes)。
    """
    received = 0
    with open(dest_path, "wb") as f:
        while received < size:
            want = min(CHUNK_SIZE, size - received)
            chunk = sock.recv(want)
            if not chunk:
                raise SyncError("接收文件时连接中断 (已收 %d/%d)" % (received, size))
            f.write(chunk)
            received += len(chunk)
            if on_progress is not None:
                on_progress(received, size)


def _drain_file_stream(sock, size):
    """从 sock 丢弃 size 字节(用于路径非法时保持协议对齐)。"""
    drained = 0
    while drained < size:
        want = min(CHUNK_SIZE, size - drained)
        chunk = sock.recv(want)
        if not chunk:
            raise SyncError("丢弃文件数据时连接中断")
        drained += len(chunk)


# ==================================================================
# 文件系统遍历与隐藏属性
# ==================================================================
def _is_hidden(path):
    """判断文件/目录是否为隐藏(Windows 属性或以 . 开头)。"""
    name = os.path.basename(path)
    if name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
            if attrs != -1 and (attrs & FILE_ATTRIBUTE_HIDDEN):
                return True
        except Exception:
            pass
    return False


def _is_reserved_name(name):
    """判断文件名是否为 Windows 保留设备名(如 nul/con/prn/aux/com1/lpt1)。

    这些名称在 Windows 上会被解析为设备路径(如 \\-\\nul), 进入 os.path.relpath
    会触发跨 mount 报错 "path is on mount 'X', start on mount 'Y'", 需跳过。
    带扩展名时(如 nul.txt)同样保留, 故只取主名判断。
    """
    if not name:
        return False
    stem = name.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    if stem in reserved:
        return True
    if stem.startswith("COM") and stem[3:].isdigit() and 1 <= int(stem[3:]) <= 9:
        return True
    if stem.startswith("LPT") and stem[3:].isdigit() and 1 <= int(stem[3:]) <= 9:
        return True
    return False


def _set_hidden(path, hidden):
    """设置 Windows 文件/目录的隐藏属性。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        cur = ctypes.windll.kernel32.GetFileAttributesW(path)
        if cur == -1:
            return
        if hidden:
            new_attr = cur | FILE_ATTRIBUTE_HIDDEN
        else:
            new_attr = cur & ~FILE_ATTRIBUTE_HIDDEN
        ctypes.windll.kernel32.SetFileAttributesW(path, new_attr)
    except Exception:
        pass


def walk_source(src_dir):
    """递归遍历源目录, 返回 (dir_list, file_list)。

    dir_list: [{relpath, is_hidden}] (含源目录自身的子目录, 不含源目录本身)
    file_list: [{relpath, abspath, size, mtime, is_hidden}]
    relpath 用 "/" 分隔, 相对 src_dir。
    """
    dir_list = []
    file_list = []
    src_dir = os.path.abspath(src_dir)
    for dirpath, dirnames, filenames in os.walk(src_dir):
        # 跳过 Windows 保留设备名目录(避免 relpath 跨 mount 报错), 并就地剪枝防止下钻
        dirnames[:] = [d for d in dirnames if not _is_reserved_name(d)]
        # 子目录元信息
        for d in dirnames:
            full = os.path.join(dirpath, d)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            dir_list.append({"relpath": rel, "is_hidden": _is_hidden(full)})
        # 文件元信息
        for fn in filenames:
            if _is_reserved_name(fn):
                continue  # 跳过保留设备名文件(如 nul), 避免 relpath/stat 异常
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            try:
                st = os.stat(full)
                file_list.append({
                    "relpath": rel, "abspath": full,
                    "size": st.st_size, "mtime": int(st.st_mtime),
                    "is_hidden": _is_hidden(full),
                })
            except OSError:
                # 无法访问的文件跳过
                continue
    return dir_list, file_list


def is_dir_empty(path):
    """判断目录是否为空(不存在视为空)。"""
    if not os.path.isdir(path):
        return True
    for _ in os.listdir(path):
        return False
    return True


def backup_target(target_dir):
    """把目标目录全部内容打包成 zip, 放在目标目录同级位置。

    返回 zip 文件路径。失败抛 SyncError。
    """
    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        raise SyncError("目标目录不存在: %s" % target_dir)
    parent = os.path.dirname(target_dir)
    name = os.path.basename(target_dir)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(parent, "%s_backup_%s.zip" % (name, ts))
    skipped_files = []
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirnames, filenames in os.walk(target_dir):
                for fn in filenames:
                    if _is_reserved_name(fn):
                        continue  # 跳过保留设备名, 避免 relpath 跨 mount 报错
                    full = os.path.join(dirpath, fn)
                    arc = os.path.relpath(full, target_dir)
                    try:
                        zf.write(full, arc)
                    except (OSError, ValueError) as e:
                        # 单个文件无法读取/路径异常时跳过, 不中断整个备份
                        skipped_files.append("%s (%s)" % (arc, e))
        return zip_path
    except Exception as e:
        raise SyncError("备份目标目录失败: %s" % e)


# ==================================================================
# 服务端 (目标端): 监听并接收文件
# ==================================================================
def start_server(ports, code, target_dir, on_log, on_progress, on_done,
                 on_listening=None, stop_flag=None, on_conn_done=None):
    """启动服务端监听, 自动选择可用端口, 持续接收连接并写入 target_dir。

    持续 accept, 每个接入连接由独立线程处理(probe/同步可并发, 互不阻塞),
    仅在停止或异常时通过 on_done 通知监听结束。

    :param ports: 候选端口列表(如 [52000, 52001, ...]), 依次尝试直到可用。
    :param code: 配对码。
    :param target_dir: 接收到的文件写入此目录(可被客户端覆盖)。
    :param on_log: 日志回调 (text)。
    :param on_progress: 进度回调 (current, total)。
    :param on_done: 监听结束回调 (ok, msg, stats), 用于异常恢复/重启监听。
    :param on_listening: 监听已启动回调 (port, code), 通知 view 实际端口。
    :param stop_flag: threading.Event, 外部置位则停止。
    :param on_conn_done: 单个连接处理完成回调 (ok, msg, stats); 缺省回退到 on_done。
    """
    conn_done = on_conn_done or on_done
    srv = None
    actual_port = None
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 自动选端口
        last_err = None
        for p in ports:
            try:
                srv.bind(("0.0.0.0", p))
                actual_port = p
                break
            except OSError as e:
                last_err = e
                continue
        if actual_port is None:
            on_done(False, "无可用端口: %s" % last_err, None)
            return
        srv.listen(8)
        srv.settimeout(1.0)  # 便于周期性检查 stop_flag
        if on_listening is not None:
            on_listening(actual_port, code)
        else:
            on_log("监听中 端口:%d 配对码:%s" % (actual_port, code))
        # 持续监听: 每个连接独立线程处理, probe 与同步连接互不阻塞
        while not (stop_flag and stop_flag.is_set()):
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # srv 已关闭
            conn.settimeout(None)
            threading.Thread(
                target=_handle_connection,
                args=(conn, addr, code, actual_port, target_dir,
                      on_log, on_progress, conn_done),
                daemon=True,
            ).start()
        on_done(False, "已停止监听", None)
    except Exception as e:
        on_done(False, "服务端错误: %s" % e, None)
    finally:
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass


def _handle_connection(conn, addr, code, my_port, target_dir, on_log, on_progress, on_conn_done):
    """处理单个接入连接(独立线程): 握手并接收文件或响应探测, 完成后回调。

    :param conn: 已接入的客户端 socket。
    :param addr: 客户端地址 (ip, port)。
    :param code: 本机配对码。
    :param my_port: 本机实际监听端口。
    :param target_dir: 接收文件写入此目录。
    :param on_log: 日志回调。
    :param on_progress: 进度回调。
    :param on_conn_done: 完成回调 (ok, msg, stats)。
    """
    try:
        stats = _serve_one(conn, code, my_port, target_dir, on_log, on_progress)
        if stats and stats.get("probe"):
            on_conn_done(True, "探测连接", stats)
        else:
            on_conn_done(True, "同步完成", stats)
    except Exception as e:
        on_conn_done(False, "服务端错误: %s" % e, None)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _serve_one(conn, code, my_port, target_dir, on_log, on_progress):
    """服务端处理一次同步: 校验配对码, 接收文件。返回统计 stats dict。

    :param conn: 已接入的客户端 socket。
    :param code: 本机配对码(用于校验对方)。
    :param my_port: 本机实际监听端口, 回握时告知对方以便其保存本机为已配对设备。
    :param target_dir: 接收文件写入此目录。
    :param on_log: 日志回调。
    :param on_progress: 进度回调。
    """
    start_ts = time.time()
    peer_name = "未知"
    backup_zip = None
    received = 0
    received_bytes = 0
    skipped = 0
    total_files = 0
    total_bytes = 0

    # 1. 握手
    cmd, meta, _body = _recv_msg(conn)
    if cmd != "HELLO":
        raise SyncError("期望握手, 收到: %s" % cmd)
    if meta.get("code") != code:
        _send_msg(conn, "ERROR", {"msg": "配对码不匹配"})
        raise SyncError("客户端配对码不匹配")
    peer_name = meta.get("name", "未知")
    is_probe = bool(meta.get("probe"))
    # 对方在 HELLO 中附带自身连接信息, 自动保存为已配对设备(实现双向可见)
    peer_ip = None
    try:
        peer_ip = conn.getpeername()[0]
    except Exception:
        pass
    peer_port = meta.get("my_port")
    peer_code = meta.get("my_code")
    if peer_ip and peer_port and peer_code:
        try:
            add_device(peer_name, peer_ip, peer_port, peer_code)
        except Exception:
            pass
    if not is_probe:
        on_log("服务端: %s 已连接到本机" % (peer_ip or "未知"))
        on_log("服务端: 配对成功, 对方 %s" % peer_name)
    _send_msg(conn, "HELLO_ACK", {
        "name": socket.gethostname(),
        "my_port": my_port,
        "my_code": code,
    })

    # 探测连接: 对方仅用于验证连通性/在线状态, 握手确认后直接结束, 不走同步流程, 不记日志避免刷屏
    if is_probe:
        return {
            "direction": "接收", "peer": peer_name, "target_dir": target_dir,
            "files_total": 0, "files_sent": 0, "files_skipped": 0,
            "bytes": 0, "backup_zip": None,
            "start_ts": start_ts, "elapsed": time.time() - start_ts,
            "probe": True,
        }

    # 同步流程串行: 多个设备同时同步到本机时排队执行, 避免并发写同一目标目录
    # probe 已在上方返回, 不进入此锁, 故在线探测不会被同步阻塞
    with _sync_lock:
        # 2. 接收目标目录路径(客户端告知写哪里)与备份请求
        cmd, meta, _body = _recv_msg(conn)
        if cmd == "SET_TARGET":
            target_dir = meta.get("target_dir") or target_dir
        # target_dir 为空时用默认接收目录(exe 同目录下的 received/), 避免空路径报错
        if not target_dir:
            target_dir = os.path.join(get_app_dir(), "received")
        # 确保目标目录存在
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        _send_msg(conn, "TARGET_OK", {"empty": is_dir_empty(target_dir)})

        # 3. 备份请求(若目标非空)
        cmd, meta, _body = _recv_msg(conn)
        if cmd == "BACKUP":
            on_log("服务端: 目标目录非空, 正在备份...")
            zip_path = backup_target(target_dir)
            backup_zip = zip_path
            on_log("服务端: 已备份到 %s" % zip_path)
            _send_msg(conn, "BACKUP_DONE", {"zip": zip_path})
        elif cmd == "NO_BACKUP":
            pass

        # 4. 接收同步开始
        cmd, meta, _body = _recv_msg(conn)
        if cmd != "SYNC_START":
            raise SyncError("期望 SYNC_START, 收到: %s" % cmd)
        total_files = meta.get("file_count", 0)
        total_bytes = meta.get("total_bytes", 0)
        on_log("服务端: 开始接收 %d 个文件, 共 %s" % (total_files, _fmt_bytes(total_bytes)))
        _send_msg(conn, "SYNC_ACK")

        # 5. 逐个接收文件/目录
        while True:
            cmd, meta, body = _recv_msg(conn)
            if cmd is None:
                raise SyncError("连接中断")
            if cmd == "SYNC_END":
                break
            if cmd == "DIR":
                rel = meta.get("relpath", "")
                if ".." in rel:
                    continue  # 防路径穿越
                dest = os.path.join(target_dir, rel.replace("/", os.sep))
                os.makedirs(dest, exist_ok=True)
                if meta.get("is_hidden"):
                    _set_hidden(dest, True)
                continue
            if cmd == "FILE":
                rel = meta.get("relpath", "")
                if ".." in rel:
                    # 路径非法: 仍需消费流式 body 避免协议错位
                    _drain_file_stream(conn, meta.get("size", 0))
                    continue
                size = meta.get("size", 0)
                mtime = meta.get("mtime", 0)
                is_hidden = meta.get("is_hidden", False)
                dest = os.path.join(target_dir, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest) or target_dir, exist_ok=True)
                # 增量判断: 同名且 size+mtime 相同则跳过(通知对方不发 body)
                if (os.path.isfile(dest)
                        and os.path.getsize(dest) == size
                        and int(os.path.getmtime(dest)) == mtime):
                    _send_msg(conn, "SKIP")
                    skipped += 1
                    received += 1
                    on_progress(received, total_files)
                    continue
                _send_msg(conn, "RECV")
                # 流式接收文件 body 直接写入磁盘
                _recv_file_stream(conn, size, dest,
                                  on_progress=lambda r, t: on_progress(received, total_files))
                received_bytes += size
                # 还原 mtime
                try:
                    os.utime(dest, (mtime, mtime))
                except OSError:
                    pass
                if is_hidden:
                    _set_hidden(dest, True)
                received += 1
                on_log("服务端: 已接收 %s (%s)" % (rel, _fmt_bytes(size)))
                on_progress(received, total_files)
            if cmd == "ERROR":
                raise SyncError(meta.get("msg", "未知错误"))

        _send_msg(conn, "SYNC_DONE", {"ok": True, "msg": "完成"})
        on_log("服务端: 接收完成, 共 %d 个文件" % received)
        return {
            "direction": "接收",
            "peer": peer_name,
            "target_dir": target_dir,
            "files_total": total_files,
            "files_sent": received - skipped,
            "files_skipped": skipped,
            "bytes": received_bytes,
            "backup_zip": backup_zip,
            "start_ts": start_ts,
            "elapsed": time.time() - start_ts,
        }


# ==================================================================
# 客户端 (源端): 连接并发送文件
# ==================================================================
def connect_and_sync(ip, port, code, src_dir, target_dir,
                     on_log, on_progress, need_backup_callback, on_file_progress=None,
                     my_port=None, my_code=None):
    """连接目标端, 把 src_dir(或单个文件) 同步到对方的 target_dir。

    :param ip: 目标端 IP。
    :param port: 目标端端口。
    :param code: 配对码。
    :param src_dir: 本机源目录或单个源文件。
    :param target_dir: 对方机器上的目标目录路径。
    :param on_log: 日志回调。
    :param on_progress: 文件级进度回调 (current, total)。
    :param need_backup_callback: 目标非空时由 view 决定是否备份, 返回 bool。
    :param on_file_progress: 可选, 单文件传输字节进度 (file_rel, sent, total)。
    :param my_port: 本机监听端口, 握手时告知对方以便其保存本机为已配对设备。
    :param my_code: 本机配对码, 握手时告知对方。
    """
    src_dir = os.path.abspath(src_dir)
    if not os.path.exists(src_dir):
        raise SyncError("源路径不存在: %s" % src_dir)
    # 单文件模式: 直接发送该文件, relpath 取文件名
    is_single_file = os.path.isfile(src_dir)
    if not is_single_file and not os.path.isdir(src_dir):
        raise SyncError("源路径既非文件也非目录: %s" % src_dir)

    start_ts = time.time()
    peer_name = "未知"
    backup_zip = None
    sent = 0
    skipped = 0
    total_files = 0
    total_bytes = 0

    sock = None
    try:
        # 连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        on_log("客户端: 正在连接 %s:%d ..." % (ip, port))
        sock.connect((ip, int(port)))
        sock.settimeout(None)
        on_log("客户端: 连接成功")

        # 1. 握手(附带本机连接信息, 供对方保存)
        _send_msg(sock, "HELLO", {
            "code": code, "name": socket.gethostname(),
            "my_port": my_port, "my_code": my_code, "probe": False,
        })
        cmd, meta, _body = _recv_msg(sock)
        if cmd == "ERROR":
            raise SyncError(meta.get("msg", "对方拒绝"))
        if cmd != "HELLO_ACK":
            raise SyncError("握手失败: %s" % cmd)
        peer_name = meta.get("name", "未知")
        # 对方回握时附带其连接信息, 保存/更新为已配对设备
        peer_port = meta.get("my_port")
        peer_code = meta.get("my_code")
        if peer_port and peer_code:
            try:
                add_device(peer_name, ip, peer_port, peer_code)
            except Exception:
                pass
        on_log("客户端: 配对成功, 对方 %s" % peer_name)

        # 2. 告知目标目录
        _send_msg(sock, "SET_TARGET", {"target_dir": target_dir})
        cmd, meta, _body = _recv_msg(sock)
        if cmd != "TARGET_OK":
            raise SyncError("设置目标目录失败")
        target_empty = meta.get("empty", True)

        # 3. 备份决策
        if target_empty:
            _send_msg(sock, "NO_BACKUP")
            on_log("客户端: 目标目录为空, 直接同步")
        else:
            do_backup = need_backup_callback(target_dir)
            if not do_backup:
                raise SyncError("用户取消同步(目标非空未确认备份)")
            _send_msg(sock, "BACKUP")
            cmd, meta, _body = _recv_msg(sock)
            if cmd != "BACKUP_DONE":
                raise SyncError("备份失败: %s" % cmd)
            backup_zip = meta.get("zip", "")
            on_log("客户端: 对方已备份 %s" % backup_zip)

        # 4. 遍历源(单文件或目录)
        if is_single_file:
            # 单文件: 仅一个文件, 相对路径为文件名
            try:
                st = os.stat(src_dir)
                file_list = [{
                    "relpath": os.path.basename(src_dir),
                    "abspath": src_dir,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "is_hidden": _is_hidden(src_dir),
                }]
            except OSError as e:
                raise SyncError("无法读取源文件: %s" % e)
            dir_list = []
            on_log("客户端: 单文件模式, 发送 %s" % file_list[0]["relpath"])
        else:
            dir_list, file_list = walk_source(src_dir)
        total_files = len(file_list)
        total_bytes = sum(f["size"] for f in file_list)
        if is_single_file:
            on_log("客户端: 待发送 1 个文件, 共 %s" % _fmt_bytes(total_bytes))
        else:
            on_log("客户端: 待同步 %d 个目录, %d 个文件, 共 %s" %
                   (len(dir_list), total_files, _fmt_bytes(total_bytes)))
        _send_msg(sock, "SYNC_START",
                  {"file_count": total_files, "total_bytes": total_bytes})
        cmd, _meta, _body = _recv_msg(sock)
        if cmd != "SYNC_ACK":
            raise SyncError("对方未确认同步开始")

        # 5. 发送目录
        for d in dir_list:
            _send_msg(sock, "DIR", {"relpath": d["relpath"], "is_hidden": d["is_hidden"]})

        # 6. 逐个发送文件(流式)
        for f in file_list:
            fpath = f["abspath"]
            try:
                fp = open(fpath, "rb")
            except OSError as e:
                on_log("客户端: 跳过无法读取的文件 %s: %s" % (f["relpath"], e))
                sent += 1
                on_progress(sent, total_files)
                continue
            try:
                # 发送文件头(不含 body), body 走流式
                _send_msg(sock, "FILE", {
                    "relpath": f["relpath"], "size": f["size"],
                    "mtime": f["mtime"], "is_hidden": f["is_hidden"],
                })
                # 等待对方决定: RECV(需要发 body) / SKIP(已存在, 不发 body)
                cmd, _meta, _body = _recv_msg(sock)
                if cmd == "SKIP":
                    skipped += 1
                    sent += 1
                    on_progress(sent, total_files)
                    if sent % 20 == 0 or sent == total_files:
                        on_log("客户端: 已处理 %d/%d (跳过 %d)" % (sent, total_files, skipped))
                    continue
                if cmd != "RECV":
                    raise SyncError("期望 RECV/SKIP, 收到: %s" % cmd)
                # 流式发送文件内容
                def fp_progress(done, total, rel=f["relpath"]):
                    """单文件字节进度回调。"""
                    if on_file_progress is not None:
                        on_file_progress(rel, done, total)
                _send_file_body(sock, fp, f["size"], on_progress=fp_progress)
                sent += 1
                on_progress(sent, total_files)
                if sent % 10 == 0 or sent == total_files:
                    on_log("客户端: 已发送 %d/%d: %s" % (sent, total_files, f["relpath"]))
            finally:
                fp.close()

        # 7. 结束
        _send_msg(sock, "SYNC_END")
        cmd, meta, _body = _recv_msg(sock)
        if cmd != "SYNC_DONE":
            raise SyncError("同步未正常结束: %s" % cmd)
        on_log("客户端: 同步完成, 共发送 %d 个文件" % sent)
        return {
            "direction": "发送",
            "peer": peer_name,
            "target_dir": target_dir,
            "files_total": total_files,
            "files_sent": sent - skipped,
            "files_skipped": skipped,
            "bytes": total_bytes,
            "backup_zip": backup_zip,
            "start_ts": start_ts,
            "elapsed": time.time() - start_ts,
        }
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


# ==================================================================
# 设备连接探测(用于"连接到目标设备"时快速校验连通)
# ==================================================================
def probe_device(ip, port, code, my_port=None, my_code=None, timeout=CONNECT_TIMEOUT):
    """探测目标设备是否在线且配对码匹配。返回对方设备名, 失败抛 SyncError。

    :param ip: 目标端 IP。
    :param port: 目标端端口。
    :param code: 目标端配对码(用于校验)。
    :param my_port: 本机监听端口, 握手时告知对方以便其保存本机为已配对设备。
    :param my_code: 本机配对码, 握手时告知对方。
    :param timeout: 连接超时秒数。
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, int(port)))
        sock.settimeout(None)
        # 探测连接: 标识 probe=True, 服务端握手确认后即结束, 不走同步流程
        _send_msg(sock, "HELLO", {
            "code": code, "name": socket.gethostname(),
            "my_port": my_port, "my_code": my_code, "probe": True,
        })
        cmd, meta, _body = _recv_msg(sock)
        if cmd == "ERROR":
            raise SyncError(meta.get("msg", "对方拒绝"))
        if cmd != "HELLO_ACK":
            raise SyncError("握手失败")
        peer_name = meta.get("name", "未知")
        # 对方回握时附带其连接信息, 保存/更新为已配对设备
        peer_port = meta.get("my_port")
        peer_code = meta.get("my_code")
        if peer_port and peer_code:
            try:
                add_device(peer_name, ip, peer_port, peer_code)
            except Exception:
                pass
        return peer_name
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def check_device_online(ip, port, code, timeout=2):
    """快速探测目标设备是否在线且配对码匹配(轻量探测, 不保存设备, 不打扰对方日志)。

    :param ip: 目标端 IP。
    :param port: 目标端端口。
    :param code: 目标端配对码。
    :param timeout: 连接/收发超时秒数。
    :return: (online: bool, name: str|None)。
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, int(port)))
        sock.settimeout(timeout)
        # 仅探测在线状态, 不携带本机连接信息, 避免污染对方设备列表
        _send_msg(sock, "HELLO", {"code": code, "name": socket.gethostname(), "probe": True})
        cmd, meta, _body = _recv_msg(sock)
        if cmd != "HELLO_ACK":
            return False, None
        return True, meta.get("name", "未知")
    except Exception:
        return False, None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
