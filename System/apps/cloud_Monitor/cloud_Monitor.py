import logging
import time
import cv2
import threading
import queue
import os

class Monitor:
    """监控核心模块 - 严格基于原有monitor.py的功能重构"""

    def __init__(self, bemfa_client, device_id):

        self.bfc = bemfa_client
        self.device_id = device_id

        # 严格保持原有的App_record逻辑
        self.app_record = self.AppRecord(self)

        # 初始化数据存储（与原有代码一致）
        self.msg_version = 0
        self.msg_dict = {}

        # 消息队列用于模块化通信
        self.msg_queue = queue.Queue()
        self.bfc.subscribe_msg(f"monitor_{device_id}", self.msg_queue)

        logging.info(f"[MonitorCore] 监控核心初始化完成 - 设备: {device_id}")

    class AppRecord:
        """严格保持原有的App_record类逻辑，只做最小化修改"""

        def __init__(self, parent):
            self.parent = parent
            self.thread = threading.Thread(target=self.__main)
            self.thread.daemon = True
            self.record_thread = threading.Thread(target=self.__record_video)
            self.record_thread.daemon = True
            self.msg_version = 0
            self.is_recording = False
            self.connect_device = None
            self.shake_hands_time = None
            self.timeout = 5
            self.heart = False

        def __reset(self):
            """原有重置逻辑"""
            self.thread = threading.Thread(target=self.__main)
            self.thread.daemon = True
            self.record_thread = threading.Thread(target=self.__record_video)
            self.record_thread.daemon = True
            self.msg_version = 0
            self.is_recording = False
            self.connect_device = None
            self.shake_hands_time = None
            self.timeout = 5

        def run(self):
            """原有运行逻辑"""
            if not self.thread.is_alive() and self.is_recording is False:
                self.is_recording = True
                self.parent.bfc.send("record.record0", target="cloud")
                self.shake_hands_time = time.time()
                self.thread.start()
            else:
                self.parent.bfc.send('程序已在运行。', target=self.parent.msg_dict['user'])

        def __record_video(self, resolution=(1280, 720), fps=10):
            """原有录像逻辑 - 完全保持不变"""
            cap = cv2.VideoCapture(0)
            try:
                if not cap.isOpened():
                    raise Exception("无法打开摄像头")

                cap.set(3, resolution[0])
                cap.set(4, resolution[1])

                last_capture_time = time.time()
                frame_count = 0

                while self.is_recording:
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    current_time = time.time()
                    if current_time - last_capture_time >= 1 / fps:
                        frame_count += 1

                        # 将图片编码为JPEG格式并保存到内存中
                        _, img_encoded = cv2.imencode('.jpg', frame)
                        image_data = img_encoded.tobytes()

                        # 从内存中读取图片数据并上传
                        self.parent.bfc.upload_image(image_data)

                        last_capture_time = current_time
                    time.sleep(0.01)

            except Exception as e:
                logging.error(f"[app.record] 录像线程出现错误：{e}，APP终止")
                self.__reset()
            finally:
                cap.release()

        def __main(self):
            """原有主线程逻辑 - 完全保持不变"""
            try:
                while self.is_recording:
                    nowtime = time.time()
                    if nowtime - self.shake_hands_time >= self.timeout:
                        logging.info(f"[app.record] 握手超时，APP退出")
                        break
                    if self.parent.msg_version != self.msg_version:
                        if "msg" in self.parent.msg_dict:
                            command = self.parent.msg_dict["msg"]
                            if command == 'record.record1' and self.is_recording and self.connect_device is None:
                                self.connect_device = self.parent.msg_dict['user']
                                self.parent.bfc.send("record.record2", target=self.connect_device)
                            elif command == 'record.record3' and self.is_recording and self.parent.msg_dict[
                                'user'] == self.connect_device:
                                logging.info(f"[app.record] 与设备{self.connect_device}握手成功，启动录像线程")
                                self.timeout = 60
                                self.record_thread.start()
                            elif command == 'record.KEEP' and self.is_recording and self.parent.msg_dict[
                                'user'] == self.connect_device:
                                self.parent.bfc.send("record.OK", target=self.connect_device)
                                self.shake_hands_time = nowtime
                            elif command == 'record.stop' and self.is_recording:
                                logging.info("[app.record] 停止录像")
                                break
                            elif self.parent.msg_dict['msg'] == 'record.OK' and self.is_recording and \
                                    self.parent.msg_dict['user'] == self.connect_device:
                                self.shake_hands_time = nowtime
                                self.heart = False
                        self.msg_version = self.parent.msg_version
                    if self.is_recording and self.connect_device is not None:
                        if (nowtime - self.shake_hands_time) >= (
                                self.timeout - 10) and not self.heart and self.timeout != 5:
                            self.parent.bfc.send("record.KEEP", target=self.connect_device)
                            self.heart = True
            except Exception as e:
                logging.error(f"[app.record] 主线程出现错误：{e}，APP终止")
            finally:
                self.__reset()

    def start(self):
        """启动监控核心"""
        logging.info("[MonitorCore] 监控核心已启动")

    def stop(self):
        """停止监控核心"""
        # 停止录像应用
        self.app_record.is_recording = False
        logging.info("[MonitorCore] 监控核心已停止")

    def process_message(self, msg_dict):
        """
        处理消息 - 严格保持原有的命令和处理逻辑

        只支持原有命令：
        - capture: 拍照
        - record: 开始录像
        - shutdown: 关机
        - who: 身份查询
        """
        try:
            # 先检查msg字段是否是JSON字符串（原有逻辑）
            if 'msg' in msg_dict and isinstance(msg_dict['msg'], str):
                try:
                    # 使用原有相同的JSON解析逻辑
                    inner_msg = msg_dict['msg'].replace("'", '"')
                    import json
                    inner_msg_dict = json.loads(inner_msg)
                    if isinstance(inner_msg_dict, dict):
                        msg_dict.update(inner_msg_dict)
                except:
                    pass  # 保持原有逻辑：如果不是JSON，保持原样

            # 只处理发给本设备或全体设备的命令（原有逻辑）
            if msg_dict.get('target', '') == 'all' or msg_dict.get('target', '') == self.device_id:
                command = msg_dict.get('msg', '')
                logging.info(f"[MonitorCore] 收到命令: {command}")

                # 严格只支持原有的4个命令
                if command == 'capture':
                    logging.info("[MonitorCore] 执行拍照命令")
                    self.capture_photo()
                    # 原有成功消息发送逻辑
                    self.bfc.send('successfully', target="cloud")
                    logging.info("[MonitorCore] 已发送成功消息到巴法云")

                elif command == 'record':
                    logging.info("[MonitorCore] 执行录像命令")
                    self.app_record.run()

                elif command == 'shutdown':
                    logging.info("[MonitorCore] 执行关机命令")
                    # 这里返回关机状态，由调用者处理
                    return 'shutdown'

                elif command == 'who':
                    self.bfc.send('me')

                else:
                    logging.warning(f"[MonitorCore] 未知命令: {command}")

        except Exception as e:
            logging.error(f"[MonitorCore] 处理消息出错: {str(e)}")

    def capture_photo(self, filename=None, resolution=(1280, 720)):
        """拍照功能 - 严格保持原有逻辑"""
        if filename is None:
            filename = f"photo_{time.strftime('%Y%m%d%H%M%S')}.jpg"

        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                raise Exception("无法打开摄像头")

            cap.set(3, resolution[0])
            cap.set(4, resolution[1])

            ret, frame = cap.read()
            if ret:
                temp_path = f"./temp_{filename}"
                cv2.imwrite(temp_path, frame)
                logging.info(f"[MonitorCore] 照片已保存到 {temp_path}")

                # 只调用一次 upload_image() 并保存结果（原有逻辑）
                image_url = self.bfc.upload_image(temp_path)

                os.remove(temp_path)
            else:
                logging.error("[MonitorCore] 无法捕获照片")
                # 发送失败消息（原有逻辑）
                fail_msg = "msg=capture failed: no frame captured"
                self.bfc.send(fail_msg.encode('utf-8'), target="cloud")
        except Exception as e:
            logging.error(f"[MonitorCore] 拍照出错: {str(e)}")
            # 发送错误消息（原有逻辑）
            error_msg = f"msg=capture error: {str(e)}"
            self.bfc.send(error_msg.encode('utf-8'), target="cloud")
        finally:
            cap.release()

    def get_status(self):
        """获取状态信息"""
        return {
            'device_id': self.device_id,
            'recording': self.app_record.is_recording,
            'connect_device': self.app_record.connect_device
        }