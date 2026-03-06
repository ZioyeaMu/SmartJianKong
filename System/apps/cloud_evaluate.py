import System.system
from System.core.base_app import BaseApp

class Evaluate(BaseApp):
    def __init__(self, system):
        super().__init__(system, "Evaluate", "1.0.0")
        pass

    def _main(self, *args, **kwargs):
        self.enlighten_app = self.system.get_app("EnlightenApp")    # 获取Enlighten软件
        self.yolov5_app = self.system.get_app("YOLOv5App")  # 获取YOLOv5软件
        pass

    def _reset(self):
        pass
