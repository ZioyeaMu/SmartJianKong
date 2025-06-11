# import socket
# import threading
# import time
# import json
# import torch
# import cv2
# from PIL import Image
# import os
# # 导入
# from torchvision import transforms
#
#
# class TcpClient:
#     def __init__(self, model_path=None):
#         self.tcp_client_socket = None
#         self.lock = threading.Lock()
#         self.running = True
#         self.model = None
#
#         # 加载 YOLOv5 分类模型（兼容 v5.x 旧版本）
#         self.load_model(model_path)
#
#         # 巴法云配置
#         self.server_ip = "bemfa.com"  # 巴法云服务器地址
#         self.server_port = 8344  # 巴法云 TCP 端口
#         self.uid = "865c32af7d4c73322601d512f8b45b14"  # 巴法云 UID
#         self.topic = "test1"  # w的巴法云主题
#         print("执行连接测试...")
#         test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         try:
#             test_socket.connect((self.server_ip, self.server_port))
#             test_socket.send(f"cmd=1&uid={self.uid}&topic={self.topic}\r\n".encode("utf-8"))
#             response = test_socket.recv(1024)
#             print(f"连接测试响应: {response.decode('utf-8')}")
#             test_socket.close()
#         except Exception as e:
#             print(f"连接测试失败: {e}")
#
#     def load_model(self, model_path):
#         """加载 YOLOv5 分类模型（兼容 v7.x+ 版本）"""
#         try:
#             if model_path and os.path.exists(model_path):
#                 self.model = torch.hub.load(
#                     "ultralytics/yolov5",
#                     "custom",
#                     path=model_path,
#                     trust_repo=True
#                 )
#                 print(f"成功加载自定义分类模型: {model_path}")
#             else:
#                 self.model = torch.hub.load(
#                     "ultralytics/yolov5",
#                     "yolov5s-cls",  # 分类模型
#                     pretrained=True,
#                     trust_repo=True
#                 )
#                 print("加载预训练分类模型")
#
#             self.model.eval()
#             print(f"模型类别: {self.model.names}")
#             print(f"输入尺寸: 224x224")
#
#         except Exception as e:
#             print(f"模型加载失败: {e}")
#             self.running = False
#
#     def detect_image(self, image_path):
#         """更新后的分类模型检测逻辑"""
#         try:
#             # 读取图像并转换为张量
#             img = Image.open(image_path).convert('RGB')
#
#             # 预处理图像
#             img = img.resize((224, 224))  # 调整尺寸
#             img_tensor = transforms.ToTensor()(img).unsqueeze(0)  # 转换为张量并添加批次维度
#
#             # 执行推理
#             with torch.no_grad():
#                 results = self.model(img_tensor)
#
#             # 解析结果
#             pred = torch.nn.functional.softmax(results, dim=1)
#             cls_idx = pred.argmax().item()
#             confidence = pred.max().item()
#             class_name = self.model.names[cls_idx]
#
#             return [{
#                 "class": class_name,
#                 "confidence": round(confidence, 2),
#                 "model_type": "classification",
#                 "input_size": 224
#             }]
#
#         except Exception as e:
#             print(f"检测失败: {e}")
#             import traceback
#             traceback.print_exc()
#             return []
#
#     def connect_server(self):
#         """连接巴法云服务器并订阅主题"""
#         while self.running:
#             try:
#                 self.tcp_client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#                 self.tcp_client_socket.settimeout(10)
#                 self.tcp_client_socket.connect((self.server_ip, self.server_port))
#
#                 # 发送订阅指令
#                 subscribe_cmd = f"cmd=1&uid={self.uid}&topic={self.topic}\r\n"
#                 self.tcp_client_socket.send(subscribe_cmd.encode("utf-8"))
#                 print("成功连接到巴法云服务器")
#                 return True
#
#             except Exception as e:
#                 print(f"连接失败: {e}，5秒后重试")
#                 self.close_connection()
#                 time.sleep(5)
#         return False
#
#     def close_connection(self):
#         """安全关闭连接"""
#         with self.lock:
#             if self.tcp_client_socket:
#                 try:
#                     self.tcp_client_socket.shutdown(socket.SHUT_RDWR)
#                     self.tcp_client_socket.close()
#                 except:
#                     pass
#                 self.tcp_client_socket = None
#
#     def send_heartbeat(self):
#         """定时发送心跳包（30秒间隔）"""
#         while self.running:
#             try:
#                 if self.tcp_client_socket:
#                     self.tcp_client_socket.send("ping\r\n".encode("utf-8"))
#                 time.sleep(30)
#             except:
#                 self.connect_server()
#
#     def send_results(self, results):
#         if not results:
#             return
#
#         # 构造消息体 - 简化格式
#         data = {
#             "class": results[0]["class"],
#             "confidence": results[0]["confidence"],
#             "time": time.strftime("%Y-%m-%d %H:%M:%S")
#         }
#
#         # 使用巴法云推荐格式
#         msg = f"cmd=2&uid={self.uid}&topic={self.topic}&msg={json.dumps(data)}\r\n"
#         print(f"准备发送的消息: {msg}")  # 调试输出
#
#         try:
#             with self.lock:
#                 if self.tcp_client_socket:
#                     self.tcp_client_socket.send(msg.encode("utf-8"))
#                     print(f"已发送分类结果: {data}")
#
#                     # 接收并打印服务器响应
#                     response = self.tcp_client_socket.recv(1024)
#                     if response:
#                         print(f"服务器响应: {response.decode('utf-8')}")
#                     else:
#                         print("未收到服务器响应")
#         except Exception as e:
#             print(f"发送失败: {e}，尝试重连")
#             self.connect_server()
#
#     def handle_input(self):
#         """处理用户输入（图片路径/摄像头/退出）"""
#         while self.running:
#             user_input = input("请输入图片路径 (或 'camera' 打开摄像头, 'exit' 退出): ").strip()
#
#             if user_input.lower() == "exit":
#                 self.running = False
#                 break
#             elif user_input.lower() == "camera":
#                 self.handle_camera()
#             else:
#                 if os.path.exists(user_input):
#                     results = self.detect_image(user_input)
#                     if results:
#                         self.send_results(results)
#                 else:
#                     print(f"错误：文件不存在 {user_input}")
#
#     def handle_camera(self):
#         print("打开摄像头... 按 'q' 退出")
#         cap = cv2.VideoCapture(0)
#
#         # 创建转换器
#         transform = transforms.Compose([
#             transforms.Resize((224, 224)),
#             transforms.ToTensor(),
#         ])
#
#         while self.running:
#             ret, frame = cap.read()
#             if not ret:
#                 print("无法获取摄像头画面")
#                 break
#
#             try:
#                 # 直接处理帧数据 - 不再使用临时文件
#                 frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
#                 img_pil = Image.fromarray(frame_rgb)
#
#                 # 预处理图像
#                 img_tensor = transform(img_pil).unsqueeze(0)
#
#                 # 执行推理
#                 with torch.no_grad():
#                     results = self.model(img_tensor)
#
#                 # 解析结果
#                 pred = torch.nn.functional.softmax(results, dim=1)
#                 cls_idx = pred.argmax().item()
#                 confidence = pred.max().item()
#                 class_name = self.model.names[cls_idx]
#
#                 result_data = [{
#                     "class": class_name,
#                     "confidence": round(confidence, 2),
#                     "model_type": "classification",
#                     "input_size": 224
#                 }]
#                 self.send_results(result_data)
#
#                 # 在画面上显示结果
#                 cv2.putText(frame, f"{class_name} {confidence:.2f}", (10, 30),
#                             cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
#
#             except Exception as e:
#                 print(f"摄像头检测失败: {e}")
#
#             cv2.imshow("Camera Detection", frame)
#             if cv2.waitKey(1) & 0xFF == ord('q'):
#                 break
#
#
# if __name__ == "__main__":
#     MODEL_PATH = r"D:\PPYTHON\PyProjects\SmartJianKong\yolov5_master\our_models\traffic_exp122\weights\best.pt"  # 我的模型路径
#     # MODEL_PATH = None  #
#
#     client = TcpClient(model_path=MODEL_PATH)
#
#     if not client.model:
#         print("模型加载失败，程序退出")
#         exit(1)
#
#     # 启动连接线程
#     connect_thread = threading.Thread(target=client.connect_server)
#     connect_thread.daemon = True
#     connect_thread.start()
#
#     # 启动心跳线程
#     heartbeat_thread = threading.Thread(target=client.send_heartbeat)
#     heartbeat_thread.daemon = True
#     heartbeat_thread.start()
#
#     # 启动用户输入线程
#     input_thread = threading.Thread(target=client.handle_input)
#     input_thread.daemon = True
#     input_thread.start()
#
#     # 主线程保持运行
#     try:
#         while client.running:
#             time.sleep(1)
#     except KeyboardInterrupt:
#         print("\n程序被用户中断")
#     finally:
#         client.running = False
#         client.close_connection()
#         print("程序已退出")
import json
# ========================================================================================================================================================================================================================================================

import logging
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
# aa
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'YOLOv5_Lite_master')))
from yolov5_master.yolov5.classify import mypredict as yv5d
from library.BemfaCloud_V20250606 import BemfaCloud
from library.Timer_V20250325 import Timer

# ========================================================================================================================================================================================================================================================


# 配置日志记录
def setup_logging(log_file="logfile.log"):
    logging.basicConfig(
        filename=log_file,  # 日志文件
        level=logging.DEBUG,  # 最低日志级别
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


class System:
    def __init__(self, opt, uid='test', msg_topic='test1', img_topic='test'):
        self.detcon = None
        self.opt = opt
        self.uid = uid
        self.msg_topic = msg_topic
        self.img_topic = img_topic
        self.power = True
        self.log_dir = './logs/'  # 日志路径
        self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())  # 系统运行时间
        # self.device_name = self.get_mac()
        self.device_name = 'mHupH'
        self.bfc = BemfaCloud(uid=uid, msg_topic=msg_topic, img_topic=img_topic, device_name=self.device_name, type='cloud')

        # 设置日志配置
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        setup_logging("./logs/" + self.run_time + ".txt")

        # 系统启动
        logging.info("系统已于" + self.run_time + "启动")

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
                                print(f'/share {type(dict(zip(names, names_prob)))} detect_result {dict({names[0]:names_prob[0]})}')
                                self.bfc.send(dict({names[0]:names_prob[0]}))
                            except Exception as e:
                                logging.error(f"[图像识别] 发生了错误，原因：{e}")
                        else:
                            logging.error(f"图片下载失败，状态码：{response.status_code}")
                    else:
                        logging.error(f"获取图片失败: {result['msg']}")
                else:
                    logging.error(f"请求失败, 状态码: {response.status_code}")
            elif msg_dict['msg'] == 'record0' and self.detcon is None:
                self.bfc.send("record1", target=msg_dict['user'])
            elif msg_dict['msg'] == 'record2' and self.detcon is None:
                self.detcon = msg_dict['user']
                self.bfc.send("record3", target=self.detcon)
                # todo:进入持续识别模式
                print("detect mode")


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
    parser.add_argument("--weights", nargs="+", type=str, default=r"./yolov5_master/yolov5/weights/best.pt", help="model path(s)")
    parser.add_argument("--source", type=str, default=r"..\..\datasets\my_datas\test", help="file/dir/URL/glob/screen/0(webcam)")
    parser.add_argument("--data", type=str, default="./yolov5_master/yolov5/data/coco128.yaml", help="(optional) dataset.yaml path")
    parser.add_argument("--imgsz", "--img", "--img-size", nargs="+", type=int, default=[224], help="inference size h,w")
    parser.add_argument("--device", default="", help="cuda device, i.e. 0 or 0,1,2,3 or cpu")
    parser.add_argument("--view-img", action="store_true", help="show results")
    parser.add_argument("--save-txt", action="store_true", help="save results to *.txt")
    parser.add_argument("--nosave", default=True, help="do not save images/videos")
    parser.add_argument("--augment", action="store_true", help="augmented inference")
    parser.add_argument("--visualize", action="store_true", help="visualize features")
    parser.add_argument("--update", action="store_true", help="update all models")
    parser.add_argument("--project", default="./yolov5_master/yolov5/runs/predict-cls", help="save results to project/name")
    parser.add_argument("--name", default="exp", help="save results to project/name")
    parser.add_argument("--exist-ok", action="store_true", help="existing project/name ok, do not increment")
    parser.add_argument("--half", action="store_true", help="use FP16 half-precision inference")
    parser.add_argument("--dnn", action="store_true", help="use OpenCV DNN for ONNX inference")
    parser.add_argument("--vid-stride", type=int, default=1, help="video frame-rate stride")
    opts = parser.parse_args()
    opts.imgsz *= 2 if len(opts.imgsz) == 1 else 1  # expand

    try:
        main(opts)
    except KeyboardInterrupt as er:
        logging.critical("程序被强制结束")
        raise KeyboardInterrupt(er)
    except Exception as er:
        logging.critical("程序异常终止：" + str(er))
        raise Exception(er)
