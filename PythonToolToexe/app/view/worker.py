# -*- coding: utf-8 -*-
"""后台任务工具：基于 threading + tkinter after 调度。

功能视图里的扫描、导出等耗时操作通过 FeatureContext.run_thread 提交到这里执行，
执行结果通过 after 回到主线程更新 UI，避免跨线程直接操作 tkinter 控件。
"""

import threading


class Worker:
    """通用后台工作线程：包装一个可调用对象及其参数。

    通过 schedule 回调把结果/异常/完成事件投递回主线程，
    schedule 由调用方提供（通常是 root.after 的封装）。
    """

    def __init__(self, fn, args, schedule, on_result=None, on_error=None, on_finished=None):
        """初始化 Worker。

        :param fn: 要在后台线程执行的函数。
        :param args: fn 的位置参数元组。
        :param schedule: 把回调投递到主线程的函数，签名为 schedule(callable)。
        :param on_result: 成功回调，签名为 on_result(result)。
        :param on_error: 异常回调，签名为 on_error(exception)。
        :param on_finished: 完成回调，无参数。
        """
        self.fn = fn
        self.args = args
        self.schedule = schedule
        self.on_result = on_result
        self.on_error = on_error
        self.on_finished = on_finished

    def start(self):
        """启动后台守护线程。"""
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        """在线程中执行 fn，并通过 schedule 把结果/异常投递回主线程。"""
        try:
            result = self.fn(*self.args)
            if self.on_result is not None:
                # 捕获 result 到默认参数，避免闭包延迟取值
                self.schedule(lambda r=result: self.on_result(r))
        except Exception as e:
            if self.on_error is not None:
                self.schedule(lambda exc=e: self.on_error(exc))
        finally:
            if self.on_finished is not None:
                self.schedule(self.on_finished)
