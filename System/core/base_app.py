import sys
import threading
import logging
import traceback


class BaseApp:
    """应用基类"""

    def __init__(self, system, name, version):
        self.system = system
        self.name = name
        self.version = version
        self.running = False
        self.thread = None

    def run(self, *args, **kwargs):
        """启动应用"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._running, args=args, kwargs=kwargs)
            self.thread.daemon = True
            self.thread.start()
            logging.info(f"[系统.BaseApp] 应用 {self.name} 已启动")

    def stop(self):
        """停止应用"""
        if self.running:
            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5.0)
            if self.thread and self.thread.is_alive():
                logging.warning(f"[系统.BaseApp] 应用 {self.name} 无法停止")
            else:
                logging.info(f"[系统.BaseApp] 应用 {self.name} 已停止")

    def reset(self):
        """重置应用"""
        self.running = False
        self.thread = None
        self._reset()

    def _running(self, *args, **kwargs):
        try:
            self._main(*args, **kwargs)
        except Exception as e:
            logging.error(f'[{self.name}] 应用运行时出错：{e}，应用已停止运行。')
            sys.stderr.write(
                f'''\n\n\n[{self.name}]\n应用运行时出错，应用已停止运行。\n以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
            sys.exit(1)
        finally:
            try:
                self.reset()
            except Exception as e:
                logging.error(f'[{self.name}] 应用重置时出错：{e}，应用已停止运行。')
                sys.stderr.write(
                    f'''\n\n\n[{self.name}]\n应用重置时出错，应用已停止运行。\n以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
                sys.exit(1)

    def _main(self, *args, **kwargs):
        """应用主循环，子类需要重写此方法"""
        raise NotImplementedError("子类必须实现 _main 方法")


    def _reset(self):
        """清理资源，子类可重写此方法"""
        logging.warning(f'[系统.BaseApp] 警告：应用{self.name}未实现重置方法')
        pass

    def get_status(self):
        """获取应用状态"""
        return {
            "name": self.name,
            "version": self.version,
            "running": self.running
        }