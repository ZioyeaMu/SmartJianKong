import copy
import sys
import threading
import logging
import time
import ast
import socket
import queue
from System.core.base_app import BaseApp
from library.BemfaCloud_V20250606 import BemfaCloud


class BemfaApp(BaseApp):
    """巴法云应用，负责与巴法云服务器通信"""

    def __init__(self, system, uid, msg_topic, img_topic, device_name=None, type='cloud'):
        super().__init__(system, "BemfaApp", "1.0")
        if device_name == None:
            device_name = system.device_name
        self.bfc = BemfaCloud(uid=uid, msg_topic=msg_topic, img_topic=img_topic,
                              device_name=device_name, type=type)
        self.uid = self.bfc.uid
        self.msg_topic = self.bfc.msg_topic
        self.img_topic = self.bfc.img_topic

        # 消息存储
        self.msg_version = 0
        self.msg_dict = {}

        # 消息订阅者字典，每个元素应该为队列类型
        self.msg_subscriptions = {}
        # 用于保护订阅者字典的锁
        self.subscriptions_lock = threading.RLock()

        # 连接状态
        self.bfc.is_connected = False
        self.connection_thread = None

    def _main(self):
        """主循环，负责连接服务器和处理消息"""
        # 连接服务器
        self.bfc.connect()

        # 消息处理循环
        while self.running:
            try:
                # 接收服务器发送的数据
                RecvRowData = self.bfc.socket.recv(1024)
                if len(RecvRowData) != 0:
                    self._process_received_data(RecvRowData)
            except BlockingIOError:
                # 没有数据时继续循环
                time.sleep(0.1)
            except (ConnectionResetError, ConnectionAbortedError):
                logging.error(f"[{self.name}] 连接断开，尝试重新连接")
                self.bfc.reconnect()
            except Exception as e:
                logging.error(f"[{self.name}] 处理消息时发生错误: {e}")
                time.sleep(1)

    def _process_received_data(self, data):
        """处理接收到的数据"""
        recvData = data.decode('utf-8').strip('\r\n').split('\n')

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

                # 处理不同类型的消息
                if recvDict.get('cmd') == '0' and recvDict.get('res') == '1':
                    logging.debug(f"[{self.name}] 心跳包接收完成")
                elif 'msg' in recvDict:
                    logging.debug(f"[{self.name}] 收到消息: {recvDict['msg']}")
                    self.msg_dict = recvDict['msg']
                    self.msg_version += 1

                    self.publish_msg(self.msg_dict)

                    # 废弃代码，原本想做个事件机制的
                    # 通知系统有新消息到达
                    # if hasattr(self.system, 'on_bemfa_message'):
                    #     self.system.on_bemfa_message(self.msg_dict)
                elif recvDict == {'cmd': '1', 'res': '1'}:
                    pass
                elif recvDict == {'cmd': '2', 'res': '1'}:
                    pass
                else:
                    logging.warning(f"[{self.name}] 未处理的服务器响应: {recvDict}")
            except Exception as e:
                logging.error(f"[{self.name}] 解析错误: {e}, 源消息: {msg}")

    def subscribe_msg(self, subscriber, buffer):
        """订阅消息
        :param subscriber: 订阅者唯一标识符
        :param buffer: 消息队列
        """
        with self.subscriptions_lock:
            self.msg_subscriptions[subscriber] = buffer
            logging.info(f"[{self.name}] 订阅者 {subscriber} 已订阅消息")

    def unsubscribe_msg(self, subscriber):
        """取消订阅消息
        :param subscriber: 订阅者唯一标识符
        """
        with self.subscriptions_lock:
            if subscriber in self.msg_subscriptions:
                del self.msg_subscriptions[subscriber]
                logging.info(f"[{self.name}] 订阅者 {subscriber} 已取消订阅")
            else:
                logging.warning(f"[{self.name}] 尝试取消不存在的订阅者: {subscriber}")

    def publish_msg(self, data):
        """发布消息到所有订阅者
        :param data: 要发布的消息数据
        """
        with self.subscriptions_lock:
            for subscriber, buffer in self.msg_subscriptions.items():
                try:
                    # 深拷贝数据以避免修改影响其他订阅者
                    data_copy = copy.deepcopy(data)
                    buffer.put(data_copy)
                except Exception as e:
                    logging.error(f"[{self.name}] 向订阅者 {subscriber} 发布消息时出错: {e}")

    def send(self, *args, **kwargs):
        """发送消息到巴法云"""
        self.bfc.send(*args, **kwargs)

    def upload_image(self, *args, **kwargs):
        """上传图片到巴法云"""
        return self.bfc.upload_image(*args, **kwargs)

    def get_message(self):
        """获取最新消息"""
        return self.msg_dict, self.msg_version

    def _reset(self):
        """重置应用，清理资源"""
        with self.subscriptions_lock:  # 获取锁以确保线程安全
            self.msg_subscriptions.clear()

        self.is_connected = False
        try:
            if self.bfc.socket:
                self.bfc.socket.shutdown(socket.SHUT_RDWR)
        except OSError as e:
            if e.errno != 9:  # 不是"Bad file descriptor"错误
                logging.warning(f"[{self.name}] 关闭socket时发生异常: {e}")
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
        logging.info(f"[{self.name}] 已清理资源")
