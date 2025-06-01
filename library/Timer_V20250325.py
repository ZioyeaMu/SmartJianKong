import threading
import time


class Timer:
    def __init__(self, name='unnamed_timer'):
        self.name = name
        self.start_time = None
        self.elapsed_time = 0
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        """启动计时器"""
        with self.lock:
            if not self.running:
                self.start_time = time.time() - self.elapsed_time
                self.running = True

    def stop(self):
        """停止计时器并显示时间"""
        with self.lock:
            if self.running:
                self.elapsed_time = time.time() - self.start_time
                self.running = False
                return self.elapsed_time

    def reset(self):
        """重置计时器"""
        with self.lock:
            self.start_time = None
            self.elapsed_time = 0
            self.running = False
            return True

    def get_elapsed_time(self):
        """获取当前计时器已过的时间"""
        with self.lock:
            if self.running:
                return time.time() - self.start_time
            return self.elapsed_time