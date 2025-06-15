# ========================================================================================================================================================================================================================================================
import hashlib
import logging
import queue
import threading
import time
import sys
import os
import socket
import ast
import cv2
import requests
import argparse
import numpy as np
import uuid
import base64
import json
import flask
import multiprocessing

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'YOLOv5_master')))
from yolov5_master.yolov5.classify import mypredict as yv5d
from library.BemfaCloud_V20250606 import BemfaCloud
from library.Timer_V20250325 import Timer


# ========================================================================================================================================================================================================================================================
# 配置日志记录
def setup_logging(log_file="logfile.log"):
    logging.basicConfig(
        filename=log_file,  # 日志文件
        level=logging.INFO,  # 最低日志级别
        format="%(asctime)s - %(levelname)s - %(message)s",  # 日志格式
        datefmt="%Y-%m-%d %H:%M:%S",  # 时间格式
        encoding='utf-8',  # 指定UTF-8编码
        # stream=sys.stdout
    )


# 使用日志记录
def log_example():
    logging.debug("This is a debug message.")
    logging.info("This is an info message.")
    logging.warning("This is a warning message.")
    logging.error("This is an error message.")
    logging.critical("This is a critical message.")


# ========================================================================================================================================================================================================================================================


# ========================================================================================================================================================================================================================================================


class System:
    class App_YOLOv5:
        def __init__(self, parent):
            self.parent = parent
            self.running = False

            self.child_pipe, self.parent_pipe = multiprocessing.Pipe()
            self.yolov5_params = {
                "weights": self.parent.opt.weights,
                "source": self.parent.opt.source,
                "imgsz": self.parent.opt.imgsz,
                "device": self.parent.opt.device,
                "view_img": self.parent.opt.view_img,
                "save_txt": self.parent.opt.save_txt,
                "nosave": self.parent.opt.nosave,
                "augment": self.parent.opt.augment,
                "visualize": self.parent.opt.visualize,
                "update": self.parent.opt.update,
                "project": self.parent.opt.project,
                "name": self.parent.opt.name,
                "exist_ok": self.parent.opt.exist_ok,
                "half": self.parent.opt.half,
                "dnn": self.parent.opt.dnn,
                "vid_stride": self.parent.opt.vid_stride,
                "pipe": self.child_pipe,

            }
            # 使用 multiprocessing.Process 创建子进程
            self.yv5d_process = None

        def run(self):
            if not self.running:
                self.yv5d_process = multiprocessing.Process(target=yv5d.run, kwargs=self.yolov5_params)
                self.yv5d_process.daemon = True  # 设置为守护进程
                self.yv5d_process.start()  # 启动子进程

        def stop(self):
            self.__reset()

        def __main(self):
            pass

        def __reset(self):
            self.running = False
            if self.yv5d_process is not None:
                if self.yv5d_process.is_alive():
                    self.yv5d_process.terminate()
                    self.yv5d_process.join(timeout=5.0)
                    if self.yv5d_process.is_alive():
                        self.yv5d_process.kill()
                self.yv5d_process.close()

                self.child_pipe, self.parent_pipe = multiprocessing.Pipe()
                self.yolov5_params = {
                    "weights": self.parent.opt.weights,
                    "source": self.parent.opt.source,
                    "imgsz": self.parent.opt.imgsz,
                    "device": self.parent.opt.device,
                    "view_img": self.parent.opt.view_img,
                    "save_txt": self.parent.opt.save_txt,
                    "nosave": self.parent.opt.nosave,
                    "augment": self.parent.opt.augment,
                    "visualize": self.parent.opt.visualize,
                    "update": self.parent.opt.update,
                    "project": self.parent.opt.project,
                    "name": self.parent.opt.name,
                    "exist_ok": self.parent.opt.exist_ok,
                    "half": self.parent.opt.half,
                    "dnn": self.parent.opt.dnn,
                    "vid_stride": self.parent.opt.vid_stride,
                    "pipe": self.child_pipe,

                }

                self.yv5d_process = None

    class App_VideoStreamServer:
        def __init__(self, parent):
            self.parent = parent
            self.app = flask.Flask(__name__)
            self.running = False
            self.image_url = None
            self.port = 5000

            self.server_thread = threading.Thread(target=self.__run_server)
            self.server_thread.daemon = True

            # 注册路由
            self.app.add_url_rule('/video_feed', 'video_feed', self.__video_feed)
            self.app.add_url_rule('/', 'index', self.__index)

        def __generate_frames(self):
            """生成视频帧的生成器函数"""
            while self.running:
                try:
                    # 获取最新图片
                    response = requests.get(self.image_url, stream=True, timeout=5)
                    if response.status_code == 200:
                        # 获取图片二进制数据
                        frame = response.content

                        # 以MJPEG帧格式输出
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                    else:
                        logging.error(f"获取图片失败，状态码: {response.status_code}")

                except Exception as e:
                    logging.error(f"发生错误: {str(e)}")

                # 控制帧率（每秒10帧）
                time.sleep(0.1)

        def __video_feed(self):
            """视频流路由"""
            return flask.Response(
                self.__generate_frames(),
                mimetype='multipart/x-mixed-replace; boundary=frame'
            )

        def __index(self):
            """提供简单的测试页面"""
            return """
            <html>
              <head>
                <title>图片视频流</title>
              </head>
              <body>
                <h1>动态图片视频流</h1>
                <img src="/video_feed" width="640">
                <p>当前源URL: <code>{}</code></p>
              </body>
            </html>
            """.format(self.image_url)

        def run(self, image_url):
            """启动视频流服务器"""
            self.image_url = image_url
            if not self.running:
                self.running = True
                self.server_thread.start()
                logging.info("视频流服务器已启动")

        def stop(self):
            """停止视频流服务器"""
            if self.running:
                self.running = False
                time.sleep(1)  # 等待线程停止
                logging.info("视频流服务器已停止")

        def __reset(self):
            self.app = flask.Flask(__name__)
            self.running = False
            self.image_url = None
            self.port = 5000

            self.server_thread = threading.Thread(target=self.__run_server)
            self.server_thread.daemon = True

            # 注册路由
            self.app.add_url_rule('/video_feed', 'video_feed', self.__video_feed)
            self.app.add_url_rule('/', 'index', self.__index)

        def __run_server(self):
            """运行Flask服务器"""
            self.app.run(host='0.0.0.0', port=self.port, threaded=True)

    class App_OnlineDetect:
        def __init__(self, parent):
            self.parent = parent
            self.msg_version = 0
            self.running = False
            self.thread = threading.Thread(target=self.__main)
            self.thread.daemon = True
            self.detect_thread = threading.Thread(target=self.__detect)
            self.detect_thread.daemon = True
            self.shake_hands_time = None
            self.timeout = 5
            self.connect_device = None
            self.heart = False

            self.detect_prob = []
            self.detect_names = []

        def run(self):
            if not self.thread.is_alive() and self.running is False:
                self.running = True
                self.parent.bfc.send("record.record1", target=self.parent.msg_dict['user'])
                self.shake_hands_time = time.time()
                self.thread.start()

        def __reset(self):
            self.msg_version = 0
            self.running = False
            self.thread = threading.Thread(target=self.__main)
            self.thread.daemon = True
            self.detect_thread = threading.Thread(target=self.__detect)
            self.detect_thread.daemon = True
            self.shake_hands_time = None
            self.timeout = 5
            self.connect_device = None

            self.detect_prob = []
            self.detect_names = []

            self.parent.app_YOLOv5.stop()

        def __main(self):
            try:
                while self.running:
                    nowtime = time.time()
                    if nowtime - self.shake_hands_time >= self.timeout:
                        logging.info(f"[app.OnlineDetect] 握手超时，APP退出")
                        break

                    if self.parent.msg_version != self.msg_version:
                        if self.parent.msg_dict['msg'] == 'record.record2' and self.connect_device is None:
                            self.connect_device = self.parent.msg_dict['user']
                            self.parent.bfc.send("record.record3", target=self.connect_device)
                            topic_md5 = hashlib.md5(
                                (self.parent.uid + self.parent.img_topic).encode('utf-8')).hexdigest()
                            self.parent.app_VideoStreamServer.run(
                                f"https://img2.bemfa.com/{topic_md5}-{self.connect_device}.jpg")
                            self.parent.app_YOLOv5.yolov5_params["source"] = "http://localhost:5000/video_feed"
                            self.timeout = 60
                            # self.yv5d_thread.start()
                            self.detect_thread.start()
                        elif self.parent.msg_dict['msg'] == 'record.OK' and self.running and self.parent.msg_dict[
                            'user'] == self.connect_device:
                            self.shake_hands_time = nowtime
                            self.heart = False
                        elif self.parent.msg_dict['msg'] == 'record.KEEP' and self.running and self.parent.msg_dict[
                            'user'] == self.connect_device:
                            self.parent.bfc.send("record.OK", target=self.connect_device)
                            self.shake_hands_time = nowtime
                        elif self.parent.msg_dict['msg'] == 'record.stop' and self.running and (self.parent.msg_dict[
                            'user'] == self.connect_device or self.parent.msg_dict['user'] == "admin"):
                            break

                        self.msg_version = self.parent.msg_version

                    if self.running and self.connect_device is not None:
                        if (nowtime - self.shake_hands_time) >= (self.timeout - 10) and not self.heart:
                            self.parent.bfc.send("record.KEEP", target=self.connect_device)
                            self.heart = True

            except Exception as e:
                logging.error(f"[app.OnlineDetect] 主线程出现错误：{e}，APP终止")
            finally:
                self.__reset()

        def __detect(self):
            try:
                self.parent.app_YOLOv5.run()

                while self.running:
                    pipe = self.parent.app_YOLOv5.parent_pipe
                    self.detect_prob, self.detect_names = pipe.recv()
                    if len(self.detect_names) != 0 and len(self.detect_prob) != 0 and len(self.detect_names) == len(
                            self.detect_prob):
                        s = ''
                        for i in range(0, len(self.detect_names)):
                            s += f"{self.detect_prob[i]} {self.detect_names[i]}, "
                        s = s.rstrip(", ")
                        s += '。'
                        logging.debug(f'[app.OnlineDetect] 检测完成，类别：{s}')

                        print(f'/share {type(dict(zip(self.detect_names, self.detect_prob)))} detect_result {dict({self.detect_names[0]: self.detect_prob[0]})}')
                        self.parent.bfc.send(dict({self.detect_names[0]: self.detect_prob[0]}), as_=self.connect_device)

                    while True:
                        try:
                            if pipe.poll(timeout=0.01):
                                msg = pipe.recv()
                            else:
                                break
                        except:
                            break
                    time.sleep(0.5)
            except Exception as e:
                print(e)
                logging.error(f"[app.OnlineDetect] 检测线程出现错误：{e}，APP终止")
                self.__reset()

    def __init__(self, opt, uid='test', msg_topic='test1', img_topic='test'):
        self.device_name = self.get_mac()
        # self.device_name = 'mHupH'
        self.detcon = None
        self.opt = opt
        self.uid = uid
        self.msg_topic = msg_topic
        self.img_topic = img_topic
        self.power = True
        self.log_dir = './logs/'  # 日志路径
        self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())  # 系统运行时间

        # 设置日志配置
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        setup_logging("./logs/" + self.run_time + ".txt")

        # 系统启动
        logging.info("系统已于" + self.run_time + "启动")

        # 初始化数据存储
        self.msg_version = 0
        self.msg_dict = {}

        # 初始化应用
        self.app_VideoStreamServer = self.App_VideoStreamServer(self)
        self.app_OnlineDetect = self.App_OnlineDetect(self)
        self.app_YOLOv5 = self.App_YOLOv5(self)

        self.bfc = BemfaCloud(uid=uid, msg_topic=msg_topic, img_topic=img_topic, device_name=self.device_name,
                              type='cloud')

    def off(self):
        self.power = False
        try:
            if self.bfc.socket:
                self.bfc.socket.shutdown(socket.SHUT_RDWR)
        except OSError as e:
            if e.errno != 9:
                logging.warning(f"关闭socket时发生异常: {e}")
        finally:
            try:
                if self.bfc.socket:
                    self.bfc.socket.close()
            except AttributeError:
                pass
            finally:
                self.bfc.socket = None
        self.bfc.is_connected = False
        self.bfc.heart_run_event.clear()
        time.sleep(1)
        logging.info("系统已正常关闭")

    def get_mac(self):
        mac = uuid.getnode()
        mac_hex = '%012x' % mac
        mac_bytes = bytes.fromhex(mac_hex)
        base64_bytes = base64.b64encode(mac_bytes)
        base64_string = base64_bytes.decode('utf-8')
        six_char_string = base64_string[:6].replace('+', 'A').replace('/', 'B')
        return six_char_string

    def msg_handle(self, msg_dict):
        if msg_dict['target'] == self.device_name or msg_dict['target'] == 'all' or msg_dict['target'] == 'cloud':
            if msg_dict['msg'] == 'shutdown':
                self.power = False
            elif msg_dict["msg"] == 'who':
                self.bfc.send('me')
            elif msg_dict['msg'] == 'detect':
                response = requests.get(
                    f"https://apis.bemfa.com/vb/api/v1/imagesTopicList?openID={self.uid}&topicID={self.img_topic}")
                if response.status_code == 200:
                    result = response.json()
                    if result['code'] == 0:
                        logging.info(f"获取图片成功！图片网址：\"{result['data']['array'][0]['url']}\"")
                        response = requests.get(result['data']['array'][0]['url'])
                        if response.status_code == 200:
                            image_data = response.content
                            image = np.asarray(bytearray(image_data), dtype=np.uint8)
                            image = cv2.imdecode(image, cv2.IMREAD_COLOR)
                            save_dir = f'./cache/detect_img'
                            save_name = f'{time.strftime("%Y%m%d%H%M%S", time.localtime())}.jpg'
                            save_file = f'{save_dir}/{save_name}'
                            if not os.path.exists(save_dir):
                                os.makedirs(save_dir)
                            cv2.imwrite(save_file, image)
                            self.opt.source = save_file
                            yolov5_params = {
                                "weights": self.opt.weights,
                                "source": self.opt.source,
                                "imgsz": self.opt.imgsz,
                                "device": self.opt.device,
                                "view_img": self.opt.view_img,
                                "save_txt": self.opt.save_txt,
                                "nosave": self.opt.nosave,
                                "augment": self.opt.augment,
                                "visualize": self.opt.visualize,
                                "update": self.opt.update,
                                "project": self.opt.project,
                                "name": self.opt.name,
                                "exist_ok": self.opt.exist_ok,
                                "half": self.opt.half,
                                "dnn": self.opt.dnn,
                                "vid_stride": self.opt.vid_stride
                            }
                            try:
                                names_prob, names = yv5d.run(**yolov5_params)
                                s = ''
                                for i in range(0, len(names)):
                                    s += f"{names_prob[i]} {names[i]}, "
                                s = s.rstrip(", ")
                                s += '。'
                                logging.info(f'[图像识别] 检测完成，类别：{s}')
                                print(
                                    f'/share {type(dict(zip(names, names_prob)))} detect_result {dict({names[0]: names_prob[0]})}')
                                self.bfc.send(dict({names[0]: names_prob[0]}))
                            except Exception as e:
                                logging.error(f"[图像识别] 发生了错误，原因：{e}")
                        else:
                            logging.error(f"图片下载失败，状态码：{response.status_code}")
                    else:
                        logging.error(f"获取图片失败: {result['msg']}")
                else:
                    logging.error(f"请求失败, 状态码: {response.status_code}")
            elif msg_dict['msg'] == 'record.record0' and self.detcon is None:
                self.app_OnlineDetect.run()


# ========================================================================================================================================================================================================================================================
def main(opt):
    system = System(opt, uid='865c32af7d4c73322601d512f8b45b14', msg_topic='test1', img_topic='test')
    heart_timer = Timer()

    # 连接服务器
    system.bfc.connect()

    heart_timer.start()
    while system.power:
        # 检测是否断开连接
        if heart_timer.get_elapsed_time() > 60:
            system.bfc.is_connected = False
        # 接收服务器发送过来的数据
        try:
            RecvRowData = system.bfc.socket.recv(1024)
            if len(RecvRowData) != 0:
                system.bfc.retry = 0
                system.bfc.is_connected = True
                heart_timer.reset()
                heart_timer.start()

                recvData = RecvRowData.decode('utf-8').strip('\r\n').split('\n')

                for msg in recvData:
                    try:
                        msg = msg.strip('\r')
                        # 1. 按 `&` 分割
                        pairs = msg.split('&')
                        # 2. 创建字典
                        recvDict = {}
                        for pair in pairs:
                            key, value = pair.split('=')
                            # 3. 如果 key 是 'msg'，我们需要解析它为字典
                            if key == 'msg':
                                # 使用 ast.literal_eval 安全地将字符串转换为字典
                                value = ast.literal_eval(value)
                            # 将键值对加入字典
                            recvDict[key] = value
                        # print('Extracted msg as dict:', recvDict)
                        if recvDict['cmd'] == '0' and recvDict['res'] == '1':
                            logging.debug("心跳包接收完成")
                        elif 'msg' in recvDict:
                            logging.info("收到消息：" + str(recvDict['msg']))
                            system.msg_dict = recvDict['msg']
                            system.msg_version += 1
                            system.msg_handle(recvDict['msg'])
                        else:
                            logging.warning("未处理的服务器响应：" + str(recvDict))
                    except Exception as e:
                        # print("解析错误:" + str(e) + "\t源消息：" + msg)
                        logging.error("解析错误:" + str(e) + "\t源消息：" + msg)
        except BlockingIOError:
            pass
        except ConnectionResetError:
            system.bfc.reconnect()
        time.sleep(0.1)

    system.off()


if __name__ == "__main__":

    # 解析命令行参数
    parser = argparse.ArgumentParser()
    # 创建互斥组
    parser.add_argument("--weights", nargs="+", type=str, default=r"./yolov5_master/yolov5/weights/best.pt",
                        help="model path(s)")
    parser.add_argument("--source", type=str, default=r"/none",
                        help="file/dir/URL/glob/screen/0(webcam)")
    parser.add_argument("--data", type=str, default="./yolov5_master/yolov5/data/coco128.yaml",
                        help="(optional) dataset.yaml path")
    parser.add_argument("--imgsz", "--img", "--img-size", nargs="+", type=int, default=[224], help="inference size h,w")
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

    try:
        main(opts)
    except KeyboardInterrupt as er:
        logging.critical("程序被强制结束")
        raise KeyboardInterrupt(er)
    except Exception as er:
        logging.critical("程序异常终止：" + str(er))
        raise Exception(er)
