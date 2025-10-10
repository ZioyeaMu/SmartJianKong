import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'System')))
from System.system import System, app_initializer


# 使用装饰器包装应用注册代码
@app_initializer
def register_apps(self):
    from System.apps.testapp import TestApp
    from System.apps.Bemfa import BemfaApp
    from System.apps.cloud_MsgHandle import MsgHandleApp
    from System.apps.cloud_VideoStreamServer import VideoStreamServerApp
    from System.apps.YOLOv5 import YOLOv5App
    from System.apps.cloud_OnlineDetect import OnlineDetectApp
    from System.apps.Enlighten import EnlightenApp

    # 安装应用2步骤：
    ta = TestApp(self)  # 1.实例化
    self.app_list.append(ta)  # 2.添加到清单
    self.install_app(
        app=ta,
        autostartup=False,
        startup_args=('args1', 'args2'),
        startup_kwargs={'kwargs1': 'kwargs1', 'kwargs2': 'kwargs2'}
    )   # 3.安装
    # 系统启动后会按照设定与否自动启动安装的应用
    # 应用清单的作用：相当于应用商店，告诉系统有这些软件可用

    ba = BemfaApp(self, '865c32af7d4c73322601d512f8b45b14', 'test1', 'test')
    self.app_list.append(ba)
    self.install_app(ba, autostartup=True)

    mha = MsgHandleApp(self)
    self.app_list.append(mha)
    self.install_app(mha, autostartup=True)

    vssa = VideoStreamServerApp(self)
    self.app_list.append(vssa)
    self.install_app(vssa, autostartup=False, startup_kwargs={'image_url': 'https://img-s.msn.cn/tenant/amp/entityid/AA1MxSMm.img?w=600&h=419&m=6 '})

    yolov5_params = {
        "weights": "./yolov5_master/yolov5/weights/best.pt",
        "source": "/none",
        "imgsz": (320, 320),
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
    }
    yv5a = YOLOv5App(self, **yolov5_params)
    self.app_list.append(yv5a)
    self.install_app(yv5a, autostartup=False)  # 不自动启动，由OnlineDetect控制

    oda = OnlineDetectApp(self)
    self.app_list.append(oda)
    self.install_app(oda, autostartup=False)  # 等待消息触发启动

    # 安装EnlightenApp
    ea = EnlightenApp(self)
    self.app_list.append(ea)
    self.install_app(ea, autostartup=True)  # 自动启动EnlightenApp


def run_argument():
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    # 创建互斥组
    parser.add_argument("--weights", nargs="+", type=str, default=r"./yolov5_master/yolov5/weights/best.pt",
                        help="model path(s)")
    parser.add_argument("--source", type=str, default=r"/none",
                        help="file/dir/URL/glob/screen/0(webcam)")
    parser.add_argument("--data", type=str, default="./yolov5_master/yolov5/data/coco128.yaml",
                        help="(optional) dataset.yaml path")
    parser.add_argument("--imgsz", "--img", "--img-size", nargs="+", type=int, default=(360, 360), help="inference size h,w")
    parser.add_argument("--device", default="", help="cuda device, i.e. 0 or 0,1,2,3 or cpu")
    parser.add_argument("--view-img", action="store_true", help="show results")
    parser.add_argument("--save-txt", action="store_true", help="save results to *.txt")
    parser.add_argument("--nosave", default=True, help="do not save images/videos")
    parser.add_argument("--augment", action="store_true", help="augmented inference")
    parser.add_argument("--visualize", action="store_true", help="visualize features")
    parser.add_argument("--update", action="store_true", help="update all models")
    parser.add_argument("--project", default="./yolov5_master/yolov5/runs/predict-cls",
                        help="save results to project/name")
    parser.add_argument("--name", default="exp", help="save results to project/name")
    parser.add_argument("--exist-ok", action="store_true", help="existing project/name ok, do not increment")
    parser.add_argument("--half", action="store_true", help="use FP16 half-precision inference")
    parser.add_argument("--dnn", action="store_true", help="use OpenCV DNN for ONNX inference")
    parser.add_argument("--vid-stride", type=int, default=1, help="video frame-rate stride")
    opts = parser.parse_args()
    opts.imgsz *= 2 if len(opts.imgsz) == 1 else 1  # expand
    opts.view_img = False
    return opts

if __name__ == '__main__':
    # 获取启动参数
    opts = run_argument()

    # 创建系统实例，装饰器会自动执行应用注册
    system = System(yolo_opts=opts)
    system.run()

