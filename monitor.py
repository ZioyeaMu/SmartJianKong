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
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'YOLOv5_Lite_master')))
from YOLOv5_Lite_master import mydetect as yv5d
from library.BemfaCloud_V20250325 import BemfaCloud
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
        self.opt = opt
        self.uid = uid
        self.msg_topic = msg_topic
        self.img_topic = img_topic
        self.power = True
        self.log_dir = './logs/'  # 日志路径
        self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())  # 系统运行时间
        self.device_name = self.get_mac()
        self.bfc = BemfaCloud(uid=uid, msg_topic=msg_topic, img_topic=img_topic, device_name=self.device_name)

        # 设置日志配置
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        setup_logging("./logs/" + self.run_time + ".txt")

        # 系统启动
        logging.info("系统已于" + self.run_time + "启动")
        if opt.server:
            logging.warning("系统当前运行状态：云计算服务端")

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
        # Handle case where msg_dict is a string
        if isinstance(msg_dict, str):
            try:
                msg_dict = json.loads(msg_dict)
            except json.JSONDecodeError:
                try:
                    msg_dict = ast.literal_eval(msg_dict)
                except:
                    logging.error(f"无法解析消息: {msg_dict}")
                    return

        # Ensure msg_dict is a dictionary
        if not isinstance(msg_dict, dict):
            logging.error(f"无效的消息格式: {msg_dict}")
            return

        target = msg_dict.get('target', '')
        msg = msg_dict.get('msg', '')

        if target == self.device_name or target == 'all':
            if msg == 'shutdown':
                self.power = False
            elif msg == 'who':
                self.bfc.send('me')
            if not self.opt.server:
                if msg == 'capture':
                    self.capture_photo()
                elif msg == 'record':
                    self.record_video()
            else:
                if msg == 'detect':
                    self.handle_detection()

    def handle_detection(self):
        try:
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
                        try:
                            names_number, names = yv5d.detect(self.opt)
                            s = ''
                            for i in range(0, len(names)):
                                s += f"{names_number[i]} {names[i]}{'s' * (names_number[i] > 1)}, "
                            s = s.rstrip(", ")
                            s += '。'
                            logging.info(f'[图像识别] 检测完成，共有：{s}')
                            print(
                                f'/share {type(dict(zip(names, names_number))} detect_result {dict(zip(names, names_number))}')
                        except Exception as e:
                            logging.error(f"[图像识别] 发生了错误，原因：{e}")
                    else:
                        logging.error(f"图片下载失败，状态码：{response.status_code}")
                else:
                    logging.error(f"获取图片失败: {result['msg']}")
            else:
                logging.error(f"请求失败, 状态码: {response.status_code}")
        except Exception as e:
            logging.error(f"处理检测请求时出错: {e}")

    def capture_photo(self, output_dir='./photo',
                      filename=time.strftime("%Y%m%d%H%M%S", time.localtime()) + '.jpg',
                      resolution=(640, 480)):
        """
        拍摄一张照片并保存

        :param output_dir: 照片保存的目录
        :param filename: 输出照片文件名
        :param resolution: 照片分辨率，默认是 640x480
        """
        # 确保保存目录存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        cap = cv2.VideoCapture(0)
        try:
            # 打开摄像头
            if not cap.isOpened():
                raise Exception('无法打开摄像头')
            # 设置摄像头分辨率
            cap.set(3, resolution[0])  # 宽度
            cap.set(4, resolution[1])  # 高度
            # 拍摄一帧照片
            ret, frame = cap.read()
            if ret:
                # 保存照片
                output_path = os.path.join(output_dir, filename)
                cv2.imwrite(output_path, frame)
                logging.info(f"照片已保存到 {output_path}")
                # 上传照片
                self.bfc.upload_image(output_path)
            else:
                raise Exception('无法捕捉照片')
        except cv2.error as e:
            logging.error(f"[OpenCV] 摄像头操作失败: {e}")
        except Exception as e:
            logging.error(f'[摄像头] 在调用摄像头时出错：{e}')
        finally:
            # 确保释放摄像头资源
            if cap is not None:
                if cap.isOpened():
                    cap.release()
                else:
                    logging.warning("[摄像头] 摄像头未打开，无法释放资源")

    def record_video(self, output_dir='./video', filename=time.strftime("%Y%m%d%H%M%S", time.localtime()) + '.mp4',
                     duration=10,
                     fps=20.0, resolution=(640, 480)):
        """
        录制视频并保存为 MP4 格式

        :param output_dir: 视频保存的目录
        :param filename: 输出视频文件名
        :param duration: 录制时长（秒）
        :param fps: 每秒帧数
        :param resolution: 视频分辨率，默认是 640x480
        """
        # 确保保存目录存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 打开默认摄像头
        cap = cv2.VideoCapture(0)
        # 设置视频编码和输出文件
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 使用 mp4v 编码器
        out = cv2.VideoWriter(os.path.join(output_dir, filename), fourcc, fps, resolution)
        try:
            if not cap.isOpened():
                raise Exception('无法打开摄像头')

            # 设置视频捕获的分辨率
            cap.set(3, resolution[0])  # 宽度
            cap.set(4, resolution[1])  # 高度

            logging.info(f"开始录制视频，录制时长：{duration} 秒")

            # 开始录制视频
            start_time = cv2.getTickCount()
            while True:
                ret, frame = cap.read()
                if not ret:
                    logging.warning("无法读取视频帧，录制提前结束")
                    break
                out.write(frame)  # 写入视频帧
                # 结束条件：达到录制时长
                elapsed_time = (cv2.getTickCount() - start_time) / cv2.getTickFrequency()
                if elapsed_time > duration:
                    break

                # 按 'q' 键退出
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            logging.info(f"视频已保存到 {output_dir}/{filename}")
            self.bfc.upload_image(f'{output_dir}/{filename}')

            return True
        except cv2.error as e:
            logging.error(f"[OpenCV] 摄像头操作失败: {e}")
        except Exception as e:
            logging.error(f'[摄像头] 在调用摄像头时出错：{e}')
        finally:
            if out is not None and out.isOpened():
                out.release()
            if cap is not None:
                cap.release()
            cv2.destroyAllWindows()


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
                            # 3. 如果 key 是 'msg'，我们需要解析它
                            if key == 'msg':
                                try:
                                    # 先尝试解析为JSON
                                    value = json.loads(value)
                                except json.JSONDecodeError:
                                    try:
                                        # 如果不是JSON，尝试用ast解析
                                        value = ast.literal_eval(value)
                                    except:
                                        # 如果都失败，保持原样
                                        pass
                            # 将键值对加入字典
                            recvDict[key] = value

                        if recvDict.get('cmd') == '0' and recvDict.get('res') == '1':
                            logging.debug("心跳包接收完成")
                        elif 'msg' in recvDict:
                            logging.info("收到消息：" + str(recvDict['msg']))
                            system.msg_handle(recvDict['msg'])
                        else:
                            logging.warning("未处理的服务器响应：" + str(recvDict))
                    except Exception as e:
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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-s', '--server', action='store_true', help='是否为云计算服务端', default=False)
    parser.add_argument('--weights', nargs='+', type=str, default='./YOLOv5_Lite_master/my_weights/fall/best.pt',
                        help='model.pt path(s)')
    parser.add_argument('--source', type=str, default='sample', help='source')  # file/folder, 0 for webcam
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.45, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.5, help='IOU threshold for NMS')
    parser.add_argument('--device', default='1', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--view-img', action='store_true', help='display results')
    parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
    parser.add_argument('--save-conf', action='store_true', help='save confidences in --save-txt labels')
    parser.add_argument('--nosave', action='store_true', help='do not save images/videos')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--update', action='store_true', help='update all models')
    parser.add_argument('--project', default='runs/detect', help='save results to project/name')
    parser.add_argument('--name', default='exp', help='save results to project/name')
    parser.add_argument('--exist-ok', action='store_true', help='existing project/name ok, do not increment')
    group.add_argument('-c', '--client', action='store_true', help='是否为监控设备', default=True)
    opts = parser.parse_args()

    try:
        main(opts)
    except KeyboardInterrupt as er:
        logging.critical("程序被强制结束")
        raise KeyboardInterrupt(er)
    except Exception as er:
        logging.critical("程序异常终止：" + str(er))
        raise Exception(er)