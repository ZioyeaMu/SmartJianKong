import logging
import os
import queue
import sys
import time
import cv2
import numpy as np
import requests


import System.system
from System.core.base_app import BaseApp
from System.apps.Bemfa import BemfaApp

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'YOLOv5_master')))
from yolov5_master.yolov5.classify import mypredict as yv5d


class MsgHandleApp(BaseApp):
    def __init__(self, system):
        super().__init__(system, "MsgHandleApp", '1.0')
        self.msg_queue = queue.Queue()
        self.opt = self.system.config['yolo_opts']

    def _main(self):
        self.bemfa_app = self.system.get_app("BemfaApp")
        self.yv5_app = self.system.get_app("YOLOv5App")
        self.VideoStreamServer_app = self.system.get_app("VideoStreamServerApp")
        self.OnlineDetect_app = self.system.get_app("OnlineDetectApp")
        if self.bemfa_app:
            logging.info(f'[{self.name}] 检测到已安装巴法云')
        else:
            logging.warning(f'[{self.name}] 未检测到巴法云应用！')


        if self.bemfa_app:
            # 订阅消息，使用应用名作为订阅者ID
            self.bemfa_app.subscribe_msg(self.name, self.msg_queue)

        while self.running:
            try:
                self.system: System.system.System
                self.bemfa_app: BemfaApp

                msg_dict = self.msg_queue.get(timeout=1)
                if msg_dict['target'] == self.system.device_name or msg_dict['target'] == 'all' or msg_dict[
                    'target'] == 'cloud':
                    if msg_dict['msg'] == 'shutdown':
                        self.system.power = False
                    elif msg_dict["msg"] == 'who':
                        self.bemfa_app.send('me')
                    elif msg_dict['msg'] == 'detect':
                        response = requests.get(
                            f"https://apis.bemfa.com/vb/api/v1/imagesTopicList?openID={self.bemfa_app.uid}&topicID={self.bemfa_app.img_topic}")
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
                                        self.bemfa_app.send(dict({names[0]: names_prob[0]}))
                                    except Exception as e:
                                        logging.error(f"[图像识别] 发生了错误，原因：{e}")
                                else:
                                    logging.error(f"图片下载失败，状态码：{response.status_code}")
                            else:
                                logging.error(f"获取图片失败: {result['msg']}")
                        else:
                            logging.error(f"请求失败, 状态码: {response.status_code}")
                    elif msg_dict['msg'] == 'record.record0':
                        self.OnlineDetect_app.run(user=msg_dict['user'])
            except queue.Empty:
                continue


    def _reset(self):
        if self.bemfa_app:
            self.bemfa_app.unsubscribe_msg(self.name)

