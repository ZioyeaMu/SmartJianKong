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
    from System.apps.STP import STPApp
    from System.apps.camera import CameraApp
    from System.apps.monitor_MsgHandle import MsgHandleApp

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

    ca = CameraApp(self,resolution=(800, 600), fps=15)
    self.app_list.append(ca)
    self.install_app(ca, autostartup=True, startup_kwargs={'enable_streaming': True})
    
    # 安装监控消息处理应用
    mha = MsgHandleApp(self)
    self.app_list.append(mha)
    self.install_app(mha, autostartup=True)

    sa = STPApp(self, hash_verification=False)
    self.app_list.append(sa)
    self.install_app(sa, autostartup=True)

    # 安装中继应用（客户端模式）
    from System.apps.relay import RelayApp
    ra = RelayApp(self, server_mode=False, server_port=12345)
    self.app_list.append(ra)
    self.install_app(ra, autostartup=True)


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
    system = System()
    system.run()

