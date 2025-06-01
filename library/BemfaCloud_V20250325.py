import threading
import logging
import socket
import time
import requests

class BemfaCloud:
    def __init__(self, uid='test', msg_topic='test1', img_topic='test', device_name=''):
        self.server_ip = 'bemfa.com'
        self.server_port = 8344
        self.uid = uid
        self.msg_topic = msg_topic
        self.img_topic = img_topic
        self.device_name = device_name

        self.heartbeat_thread = threading.Thread(target=self.send_heartbeat_loop)

        self.reconnect_timeout = 5  # 重连间隔时间（秒）
        self.retry = 0
        self.is_connected = False
        self.socket = None

        self.heart_run_event = threading.Event()

    def connect(self):
        """建立TCP连接"""
        try:
            if self.retry == 0:
                logging.info("[巴法云] 正在连接巴法云服务器...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_ip, self.server_port))
            self.socket.setblocking(False)
            self.is_connected = True
            self.retry = 0
            logging.info(f"[巴法云] 已连接到服务器 {self.server_ip}:{self.server_port}")
            self.send_subscribe_command()
            self.start_heartbeat_thread()
        except Exception as e:
            self.is_connected = False
            if self.retry == 0:
                logging.error(f"[巴法云] 连接失败：{e}，{self.reconnect_timeout}秒后尝试第{self.retry}次重连...")
                time.sleep(self.reconnect_timeout)
                self.reconnect()
            else:
                raise Exception(e)

    def reconnect(self):
        """重新连接"""
        self.is_connected = False
        logging.warning("[巴法云] 正在尝试重连...")
        while not self.is_connected:
            try:
                self.retry += 1
                self.connect()
            except Exception as e:
                self.is_connected = False
                logging.error(f"[巴法云] 重新连接失败：{e}，{self.reconnect_timeout}秒后尝试第{self.retry}次重连...")
                time.sleep(self.reconnect_timeout)

    def send_subscribe_command(self):
        """发送订阅指令"""
        substr = f"cmd=1&uid={self.uid}&topic={self.msg_topic}\r\n"
        try:
            self.socket.send(substr.encode("utf-8"))
            logging.info(f"[巴法云] 订阅主题：{self.msg_topic}")
        except Exception as e:
            logging.error(f"[巴法云] 发送订阅指令失败：{e}，{self.reconnect_timeout}秒后尝试重连...")
            time.sleep(self.reconnect_timeout)
            self.reconnect()

    def start_heartbeat_thread(self):
        """启动心跳线程"""
        if not self.heartbeat_thread.is_alive():
            self.heartbeat_thread.daemon = True
            self.heartbeat_thread.start()
        else:
            self.heart_run_event.clear()
            time.sleep(1)
        self.heart_run_event.set()
        logging.info("[巴法云] 心跳线程已启动")

    def send_heartbeat_loop(self):
        """心跳线程的主循环"""
        while True:
            self.heart_run_event.wait()
            try:
                self.send_heartbeat()
                for _ in range(0, 200):  # 每 20 秒发送一次心跳
                    if self.heart_run_event.is_set():
                        time.sleep(0.1)
                    else:
                        break
            except Exception as e:
                logging.error(f"[巴法云] 心跳线程发生错误：{e}，心跳发送已终止")
                self.heart_run_event.clear()

    def send_heartbeat(self):
        """发送心跳"""
        try:
            self.socket.send("ping\r\n".encode("utf-8"))
            logging.debug("[巴法云] 已发送心跳")
        except Exception as e:
            logging.error(f"[巴法云] 发送心跳失败：{e}，重连服务器中...")
            self.reconnect()

    def upload_image(self, image_path):
        """上传图片到服务器"""
        try:
            url = "https://apis.bemfa.com/vb/api/v1/imagesUpload"
            files = {'image': open(image_path, 'rb')}
            data = {
                'openID': self.uid,
                'topic': self.img_topic,
                'wechat': '',
                'pash': '',
            }
            response = requests.post(url, data=data, files=files)
            files['image'].close()
            # 处理响应
            if response.status_code == 200:
                # 解析JSON响应
                result = response.json()
                if result['code'] == 0:
                    logging.info(f"上传图片成功！图片路径：\"{image_path}\"")
                else:
                    logging.error(f"上传图片失败: {result['msg']}")
            else:
                logging.error(f"请求失败, 状态码: {response.status_code}")
        except Exception as e:
            logging.error(f"上传图片时发生错误：{e}")

    def send(self, msg):
        data = {
            "user": self.device_name,
            "time": time.time(),
            "msg": msg,
            "target": "admin"
        }
        try:
            msg = 'cmd=2&uid=' + self.uid + '&topic=' + self.msg_topic + '/set&msg=' + str(data)
            self.socket.send(msg.encode("utf-8"))
            logging.info(f'[巴法云] 已发送消息：{data}')
        except Exception as e:
            logging.error(f"[巴法云] 发送消息失败：{e}，重连服务器中...")
            self.reconnect()