# System/apps/cloud_OnlineDetect.py
import logging
import queue
import time
import hashlib
import threading

import System.apps.cloud_VideoStreamServer
from System.core.base_app import BaseApp
from System.apps.Bemfa import BemfaApp
from System.apps.YOLOv5 import YOLOv5App
from System.apps.cloud_VideoStreamServer import VideoStreamServerApp


class OnlineDetectApp(BaseApp):
    def __init__(self, system):
        super().__init__(system, "OnlineDetectApp", '1.0')

        # 应用状态
        self.msg_version = 0
        self.shake_hands_time = None
        self.timeout = 5
        self.connect_device = None
        self.heart = False

        # 检测结果
        self.detect_prob = []
        self.detect_names = []

        # 依赖应用
        self.bemfa_app = None
        self.yolov5_app = None
        self.video_stream_app = None

        # 检测线程
        self.detect_thread = None
        self.detect_running = False

    def _main(self, **kwargs):
        """主循环"""
        # 获取依赖应用
        self.bemfa_app = self.system.get_app("BemfaApp")
        self.yolov5_app = self.system.get_app("YOLOv5App")
        self.video_stream_app = self.system.get_app("VideoStreamServerApp")

        if not all([self.bemfa_app, self.yolov5_app, self.video_stream_app]):
            print(self.bemfa_app)
            print(self.yolov5_app)
            print(self.video_stream_app)
            logging.error(f"[{self.name}] 缺少依赖应用，无法启动在线监测")
            return

        self.user = kwargs['user']

        # 订阅消息
        msg_queue = queue.Queue()
        self.bemfa_app.subscribe_msg(self.name, msg_queue)

        self._start_online_detect()

        try:
            while self.running:
                # 处理消息
                try:
                    msg_dict = msg_queue.get_nowait()
                    self._handle_message(msg_dict)
                except queue.Empty:
                    pass

                # 检查超时
                if self.shake_hands_time and time.time() - self.shake_hands_time >= self.timeout:
                    logging.info(f"[{self.name}] 握手超时，退出在线监测")
                    break

                # 发送心跳
                self._send_heartbeat()

                time.sleep(0.1)

        except Exception as e:
            logging.error(f"[{self.name}] 主循环出错: {e}")
        finally:
            self._cleanup()

    def _handle_message(self, msg_dict):
        """处理消息"""
        if msg_dict.get('target') in [self.system.device_name, 'all', 'cloud']:
            msg = msg_dict.get('msg', '')
            user = msg_dict.get('user', '')

            # if msg == 'record.record0' and self.connect_device is None:
            #     self._start_online_detect()
            if msg == 'record.record2' and self.connect_device is None:
                self._confirm_connection(user)
            elif msg == 'record.OK' and user == self.connect_device:
                self.shake_hands_time = time.time()
                self.heart = False
            elif msg == 'record.KEEP' and user == self.connect_device:
                self.bemfa_app.send("record.OK", target=self.connect_device)
                self.shake_hands_time = time.time()
            elif msg == 'record.stop' and user in [self.connect_device, "admin"]:
                logging.info(f"[{self.name}] 收到停止指令，退出在线监测")
                self.running = False

    def _start_online_detect(self):
        """开始在线监测"""
        logging.info(f"[{self.name}] 用户: {self.user}请求云端资源")
        self.bemfa_app.send("record.record1", target=self.user)
        self.shake_hands_time = time.time()

    def _confirm_connection(self, user):
        """确认连接"""
        logging.info(f"[{self.name}] 确认连接，用户: {user}")
        self.connect_device = user
        self.bemfa_app.send("record.record3", target=self.connect_device)

        # 启动视频流和YOLOv5检测
        self._start_detection_pipeline()

        self.timeout = 60  # 延长超时时间

    def _start_detection_pipeline(self):
        """启动检测流水线"""
        try:
            # 生成视频流URL
            topic_md5 = hashlib.md5(
                (self.bemfa_app.uid + self.bemfa_app.img_topic).encode('utf-8')
            ).hexdigest()
            image_url = f"https://img2.bemfa.com/{topic_md5}-{self.connect_device}.jpg"

            self.video_stream_app: System.apps.cloud_VideoStreamServer.VideoStreamServerApp
            # 启动视频流服务器
            self.video_stream_app.set_image_url(image_url)
            if not self.video_stream_app.running:
                self.video_stream_app.run()

            # 更新YOLOv5源并启动
            self.yolov5_app.update_source("http://localhost:5000/video_feed")
            if not self.yolov5_app.running:
                self.yolov5_app.run()

            # 启动检测线程
            self.detect_running = True
            self.detect_thread = threading.Thread(target=self._detection_loop)
            self.detect_thread.daemon = True
            self.detect_thread.start()

            logging.info(f"[{self.name}] 检测流水线已启动")

        except Exception as e:
            logging.error(f"[{self.name}] 启动检测流水线时出错: {e}")

    def _detection_loop(self):
        """检测循环"""
        while self.detect_running and self.running:
            try:
                # 获取检测结果
                detect_prob, detect_names = self.yolov5_app.get_detection_results()

                if (detect_names and detect_prob and
                        len(detect_names) == len(detect_prob) and
                        len(detect_names) > 0):
                    # 格式化检测结果
                    result_str = ', '.join(
                        f"{prob} {name}" for prob, name in zip(detect_prob, detect_names)
                    )
                    result_str += '。'

                    logging.debug(f'[{self.name}] 检测完成: {result_str}')

                    # 发送检测结果
                    result_dict = {detect_names[0]: detect_prob[0]}
                    self.bemfa_app.send(
                        result_dict,
                        as_=self.connect_device,
                        type="monitor",
                        hide=True
                    )

                time.sleep(0.5)

            except Exception as e:
                logging.error(f"[{self.name}] 检测循环出错: {e}")
                time.sleep(1)

    def _send_heartbeat(self):
        """发送心跳"""
        if (self.connect_device and
                self.shake_hands_time and
                time.time() - self.shake_hands_time >= (self.timeout - 10) and
                not self.heart and
                self.timeout != 5):     # 如果已经连接了设备并且握手成功（存在握手时间）并且还剩10秒超时并且超时时间不为默认（防止未连接就发送心跳）并且心跳包未发送（防止频繁发送心跳包）
            self.bemfa_app.send("record.KEEP", target=self.connect_device)
            self.heart = True

    def _cleanup(self):
        """清理资源"""
        self.detect_running = False

        # 停止检测线程
        if self.detect_thread and self.detect_thread.is_alive():
            self.detect_thread.join(timeout=5.0)

        # 停止YOLOv5
        if self.yolov5_app:
            self.yolov5_app.stop()

        # 停止视频流服务器
        if self.video_stream_app:
            self.video_stream_app.stop()

        # 重置状态
        self.connect_device = None
        self.shake_hands_time = None
        self.timeout = 5
        self.heart = False

        logging.info(f"[{self.name}] 在线监测已停止")

    def _reset(self):
        """重置应用"""
        self._cleanup()
        self.msg_version = 0
        self.detect_prob = []
        self.detect_names = []

    def get_status(self):
        """获取应用状态"""
        status = super().get_status()
        status.update({
            "connected_device": self.connect_device,
            "timeout": self.timeout,
            "detection_running": self.detect_running,
            "last_detection": {
                "names": self.detect_names,
                "probabilities": self.detect_prob
            } if self.detect_names else None
        })
        return status