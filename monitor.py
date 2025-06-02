import logging
import time
import os
import cv2
import uuid
import base64
import argparse
import json  # 新增json模块导入
from library.BemfaCloud_V20250325 import BemfaCloud


# 配置日志
def setup_logging(log_file="logfile.log"):
    logging.basicConfig(
        filename=log_file,  # 日志文件
        level=logging.DEBUG,  # 最低日志级别
        format="%(asctime)s - %(levelname)s - %(message)s",  # 日志格式
        datefmt="%Y-%m-%d %H:%M:%S",  # 时间格式
        encoding='utf-8',  # 指定UTF-8编码
        # stream=sys.stdout
    )


# 获取设备唯一标识
def get_device_id():
    mac = uuid.getnode()
    mac_hex = '%012x' % mac
    mac_bytes = bytes.fromhex(mac_hex)
    base64_bytes = base64.b64encode(mac_bytes)
    base64_string = base64_bytes.decode('utf-8')
    return base64_string[:6].replace('+', 'A').replace('/', 'B')


class System:
    def __init__(self):
        self.device_id = get_device_id()
        self.uid = '865c32af7d4c73322601d512f8b45b14'
        self.msg_topic = 'test1'
        self.img_topic = 'test'
        self.power = True
        self.log_dir = './logs/'  # 日志路径
        self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())  # 系统运行时间
        # 设置日志配置
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        setup_logging("./logs/" + self.run_time + ".txt")

        logging.info("系统已于" + self.run_time + "启动")

        # 初始化巴法云连接
        self.bfc = BemfaCloud(uid=self.uid, msg_topic=self.msg_topic, img_topic=self.img_topic, device_name=self.device_id)
        self.power = True
        self.last_heartbeat = time.time()

        # 连接服务器
        self._connect()
        logging.info("初始化完成，设备ID: %s", self.device_id)

    def _connect(self):
        """连接服务器"""
        self.bfc.connect()
        self.last_heartbeat = time.time()

    def _check_heartbeat(self):
        """检查心跳是否超时"""
        if time.time() - self.last_heartbeat > 60:
            logging.warning("心跳超时，连接已断开")
            self.bfc.is_connected = False
            self._reconnect()

    def _reconnect(self):
        """重连服务器"""
        logging.info("尝试重新连接...")
        try:
            self.bfc.connect()
            self.last_heartbeat = time.time()
            logging.info("重新连接成功")
        except Exception as e:
            logging.error(f"重新连接失败: {str(e)}")
            time.sleep(5)
            self._reconnect()

    def _process_message(self, msg_dict):
        """处理接收到的消息"""
        try:
            # 先检查msg字段是否是JSON字符串
            if 'msg' in msg_dict and isinstance(msg_dict['msg'], str):
                try:
                    inner_msg = json.loads(msg_dict['msg'])  # 解析JSON字符串
                    if isinstance(inner_msg, dict):
                        msg_dict.update(inner_msg)  # 合并到主字典
                except json.JSONDecodeError:
                    pass  # 如果不是JSON，保持原样

            # 现在可以直接从msg_dict获取命令
            command = msg_dict.get('msg', '').lower()

            if command == 'capture':
                logging.info("执行拍照命令")
                self.capture_photo()
            elif command == 'record':
                logging.info("执行录像命令")
                duration = 10
                if 'duration' in msg_dict:
                    try:
                        duration = int(msg_dict['duration'])
                    except ValueError:
                        pass
                self.record_video(duration=duration)
            elif command == 'shutdown':
                logging.info("执行关机命令")
                self.power = False
            elif command == 'who':
                self.bfc.send('me')
            else:
                logging.warning(f"未知命令: {command} 完整消息: {msg_dict}")

        except Exception as e:
            logging.error(f"处理消息出错: {str(e)} 原始消息: {msg_dict}")

    def capture_photo(self, filename=None, resolution=(1280, 720)):
        """拍照并上传"""
        if filename is None:
            filename = f"photo_{time.strftime('%Y%m%d%H%M%S')}.jpg"

        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                raise Exception("无法打开摄像头")

            # 设置分辨率
            cap.set(3, resolution[0])
            cap.set(4, resolution[1])

            ret, frame = cap.read()
            if ret:
                # 临时保存照片
                temp_path = f"./temp_{filename}"
                cv2.imwrite(temp_path, frame)
                logging.info(f"照片已保存到 {temp_path}")

                # 上传到巴法云
                if self.bfc.upload_image(temp_path):
                    logging.info("照片上传成功")
                else:
                    logging.error("照片上传失败")

                # 删除临时文件
                os.remove(temp_path)
            else:
                logging.error("无法捕获照片")
        except Exception as e:
            logging.error(f"拍照出错: {str(e)}")
        finally:
            cap.release()

    def record_video(self, duration=10, filename=None, fps=20.0, resolution=(1280, 720)):
        """录制视频并上传"""
        if filename is None:
            filename = f"video_{time.strftime('%Y%m%d%H%M%S')}.mp4"

        temp_path = f"./temp_{filename}"
        cap = cv2.VideoCapture(0)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_path, fourcc, fps, resolution)

        try:
            if not cap.isOpened():
                raise Exception("无法打开摄像头")

            # 设置分辨率
            cap.set(3, resolution[0])
            cap.set(4, resolution[1])

            logging.info(f"开始录制 {duration} 秒视频...")
            start_time = time.time()

            while (time.time() - start_time) < duration:
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)

                # 按'q'键可提前结束
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            logging.info(f"视频已保存到 {temp_path}")

            # 上传视频（注意：原始BemfaCloud可能只支持图片上传）
            # 这里我们尝试上传，但可能需要修改BemfaCloud库
            if self.bfc.upload_image(temp_path):  # 可能需要改为upload_video
                logging.info("视频上传成功")
            else:
                logging.error("视频上传失败")

        except Exception as e:
            logging.error(f"录像出错: {str(e)}")
        finally:
            out.release()
            cap.release()
            cv2.destroyAllWindows()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def run(self):
        """运行主消息循环"""
        try:
            while self.power:
                self._check_heartbeat()

                try:
                    recv_data = self.bfc.socket.recv(1024)
                    if len(recv_data) != 0:
                        self.bfc.retry = 0
                        self.bfc.is_connected = True
                        self.last_heartbeat = time.time()

                        messages = recv_data.decode('utf-8').strip('\r\n').split('\n')
                        for msg in messages:
                            try:
                                msg = msg.strip('\r')
                                pairs = msg.split('&')
                                recv_dict = {}
                                for pair in pairs:
                                    key, value = pair.split('=')
                                    recv_dict[key] = value

                                if recv_dict.get('cmd') == '0' and recv_dict.get('res') == '1':
                                    logging.debug("收到心跳包")
                                else:
                                    logging.info(f"收到原始消息: {recv_dict}")
                                    self._process_message(recv_dict)
                            except Exception as e:
                                logging.error(f"消息解析错误: {str(e)} 原始消息: {msg}")
                except BlockingIOError:
                    pass
                except ConnectionResetError:
                    self._reconnect()

                time.sleep(0.1)

        except KeyboardInterrupt:
            logging.info("用户中断程序")
        finally:
            self.power = False
            logging.info("程序结束")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='通过巴法云消息控制摄像头')
    args = parser.parse_args()

    system = System()
    system.run()
