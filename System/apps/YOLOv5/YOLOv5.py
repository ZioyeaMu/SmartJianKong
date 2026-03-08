# System/apps/YOLOv5.py
import multiprocessing
import logging
import time
import sys
import os

import System.system

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'YOLOv5_master')))
from yolov5_master.yolov5.classify import mypredict as yv5d

from System.core.base_app import BaseApp


class YOLOv5App(BaseApp):
    def __init__(self, system, **kwargs):
        super().__init__(system, "YOLOv5App", '1.0')
        self.params = kwargs
        self.process = None
        self.child_pipe, self.parent_pipe = multiprocessing.Pipe()

        self.system:System.system.System
        # 定义默认参数
        self.default_params = {
            "weights": "./yolov5_master/yolov5/weights/best.pt",
            "source": "/none",
            "imgsz": (224, 224),
            "device": "",
            "view_img": False,
            "save_txt": False,
            "nosave": True,
            "augment": False,
            "visualize": False,
            "update": False,
            "project": "./yolov5_master/yolov5/runs/predict-cls",
            "name": "exp",
            "exist_ok": False,
            "half": False,
            "dnn": False,
            "vid_stride": 1,
            "pipe": self.child_pipe,
        }

        # 如果系统配置中有 yolo_opts，则用它更新默认参数
        if 'yolo_opts' in self.system.config:
            # 将 Namespace 对象转换为字典
            yolo_opts_dict = vars(self.system.config['yolo_opts'])
            self.default_params.update(yolo_opts_dict)

        # 更新参数
        self.default_params.update(kwargs)
        self.params = self.default_params

    def _main(self, *args, **kwargs):
        """运行YOLOv5检测进程"""
        try:
            logging.info(f"[{self.name}] 启动YOLOv5检测进程")
            self.process = multiprocessing.Process(target=yv5d.run, kwargs=self.params)
            self.process.daemon = True
            self.process.start()
            logging.info(f"[{self.name}] YOLOv5检测进程已启动，PID: {self.process.pid}")

            # 等待进程运行
            while self.running and self.process.is_alive():
                time.sleep(0.1)

        except Exception as e:
            logging.error(f"[{self.name}] 启动YOLOv5检测进程时出错: {e}")
            raise

    def get_detection_results(self, timeout=0.1):
        """获取检测结果"""
        try:
            if self.parent_pipe.poll(timeout):
                detect_prob, detect_names = self.parent_pipe.recv()
                return detect_prob, detect_names
        except Exception as e:
            logging.error(f"[{self.name}] 获取检测结果时出错: {e}")
        return [], []

    def update_source(self, source):
        """更新视频源"""
        self.params["source"] = source
        # 需要重启进程来应用新的源
        if self.running:
            self.stop()
            time.sleep(1)
            self.run()

    def _reset(self):
        """重置应用"""
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5.0)
            if self.process.is_alive():
                self.process.kill()
            self.process.close()
        self.process = None
        # 重新创建管道
        self.child_pipe, self.parent_pipe = multiprocessing.Pipe()
        self.params["pipe"] = self.child_pipe

    def get_status(self):
        """获取应用状态"""
        status = super().get_status()
        status.update({
            "process_alive": self.process.is_alive() if self.process else False,
            "source": self.params.get("source", "unknown")
        })
        return status