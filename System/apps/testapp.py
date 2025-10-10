import time
from System.core.base_app import BaseApp
import logging


class TestApp(BaseApp):
    """测试应用，用于验证系统基本功能"""

    def __init__(self, system, name="TestApp", version="1.0"):
        super().__init__(system, name, version)
        self.counter = 0
        self.interval = 1  # 运行间隔(秒)

    def _main(self, *args, **kwargs):
        """测试应用的主循环"""
        logging.info(f"[{self.name}] 测试应用启动，版本 {self.version}，参数:\nargs:\n{args}\nkwargs:\n{kwargs}")

        # time.sleep(10)
        # self.system.uninstall_app('VideoStreamServer')

        while self.running:
            self.counter += 1
            status = self.system.get_status()
            logging.info(f"[{self.name}] 运行中... 计数: {self.counter}")
            logging.info(f"[{self.name}] 系统状态: 运行时间 {status['run_time']}, 设备名 {status['device_name']}, 应用状态：{status['apps']}")

            # 模拟一些工作
            time.sleep(self.interval)

    def _reset(self):
        """清理资源"""
        logging.info(f"[{self.name}] 执行清理，最终计数: {self.counter}")
        self.counter = 0
