# camera_app.py
import cv2
import time
import socket
import threading
import queue
import json
import os
import struct
from datetime import datetime
from System.core.base_app import BaseApp
import logging
import numpy as np


class CameraApp(BaseApp):
    """增强版相机应用，支持拍照、视频录制、H.264编码和TCP图像流传输"""

    def __init__(self, system, camera_id=0, resolution=(1280, 720), fps=30, white_balance=True):
        super().__init__(system, "CameraApp", "2.0")

        self.relay_app = self.system.get_app("RelayApp")
        
        if not self.relay_app:
            logging.warning(f'[{self.name}] 未检测到中转应用！')

        # 相机参数
        self.camera_id = camera_id
        self.resolution = resolution
        self.fps = fps
        self.camera = None
        self.white_balance = white_balance  # 白平衡校正，默认禁用

        # 状态标志
        self.is_recording = False
        self.is_streaming = False
        self.is_saving_frames = False

        # 视频录制相关
        self.video_writer = None
        self.video_filename = None
        self.record_start_time = None

        # TCP服务器相关（作为服务器）
        self.tcp_server = None
        self.tcp_clients = []
        self.tcp_thread = None
        self.tcp_port = 5001
        self.current_frame_data = None  # 存储当前帧数据
        self.frame_lock = threading.Lock()  # 线程安全锁
        self.tcp_server_running = False  # 标记TCP服务器是否正在运行

        # TCP客户端相关（连接到其他服务器）
        self.tcp_client_sockets = {}  # 键：IP地址，值：socket对象
        self.client_receiving = {}  # 键：IP地址，值：是否正在接收
        self.client_threads = {}  # 键：IP地址，值：线程对象
        self.client_display = False
        self.client_save_video = False
        self.client_video_writer = None
        self.client_video_filename = None

        # 中继相关（通过RelayApp中转视频数据）
        self.relay_app = None
        self.relay_room_ids = {}  # 键：房间ID，值：是否正在接收
        self.relay_streaming = False
        self.relay_receiving = {}  # 键：房间ID，值：是否正在接收
        self.relay_frame_queues = {}  # 键：房间ID，值：队列对象

        # 多路图像存储
        self.frames = {}  # 键：IP地址或房间ID，值：{"frame": 当前图像, "active": 是否活跃, "last_access": 最后访问时间}
        
        # 自动断开检测线程
        self.auto_disconnect_thread = None
        self.auto_disconnect_running = False

        # 图像保存相关
        self.save_directory = "./captured_images"
        self.image_format = "jpg"

        # 视频编码器选择
        self.codec = 'mp4v'  # MP4容器
        self.video_ext = '.mp4'
        self.use_h264 = False  # 尝试使用H.264

        # 创建保存目录
        if not os.path.exists(self.save_directory):
            os.makedirs(self.save_directory)

        # 创建视频保存目录
        self.video_directory = "./recorded_videos"
        if not os.path.exists(self.video_directory):
            os.makedirs(self.video_directory)

    def gray_world_white_balance(self, img):
        """灰度世界白平衡算法"""
        # 将图像转换为浮点型
        img_float = img.astype(np.float32)
        
        # 计算每个通道的平均值
        avg_b = np.mean(img_float[:, :, 0])
        avg_g = np.mean(img_float[:, :, 1])
        avg_r = np.mean(img_float[:, :, 2])
        
        # 计算灰度平均值
        avg_gray = (avg_b + avg_g + avg_r) / 3.0
        
        # 计算每个通道的增益
        gain_b = avg_gray / avg_b
        gain_g = avg_gray / avg_g
        gain_r = avg_gray / avg_r
        
        # 应用增益
        img_float[:, :, 0] = img_float[:, :, 0] * gain_b
        img_float[:, :, 1] = img_float[:, :, 1] * gain_g
        img_float[:, :, 2] = img_float[:, :, 2] * gain_r
        
        # 裁剪到0-255范围
        return np.clip(img_float, 0, 255).astype(np.uint8)

    def _detect_codecs(self):
        """检测系统可用的视频编码器"""
        test_codecs = [
            ('avc1', '.mp4'),  # H.264 MP4
            ('h264', '.mp4'),  # H.264
            ('mp4v', '.mp4'),  # MPEG-4
            ('XVID', '.avi'),  # XVID AVI
            ('MJPG', '.avi'),  # MJPEG
        ]

        for codec, ext in test_codecs:
            try:
                # 创建临时视频写入器测试
                temp_filename = f"./temp_test{ext}"
                fourcc = cv2.VideoWriter_fourcc(*codec)
                test_writer = cv2.VideoWriter(temp_filename, fourcc, self.fps, (640, 480))

                if test_writer.isOpened():
                    test_writer.release()
                    os.remove(temp_filename)  # 删除测试文件

                    # 优先选择H.264编码器
                    if codec in ['avc1', 'h264']:
                        self.codec = codec
                        self.video_ext = ext
                        self.use_h264 = True
                        logging.info(f"[{self.name}] 检测到H.264编码器: {codec}")
                        return
                    elif self.codec == 'mp4v':  # 如果没有H.264，使用MP4V
                        self.codec = codec
                        self.video_ext = ext
                        logging.info(f"[{self.name}] 检测到编码器: {codec}")
                        return
            except:
                continue

        logging.warning(f"[{self.name}] 未检测到H.264编码器，使用默认编码器: {self.codec}")

    def _create_error_frame(self, error_message):
        """创建故障画面（蓝底白字）

        Args:
            error_message: 错误信息
        Returns:
            故障画面帧
        """
        # 创建固定分辨率的蓝底画布 (640x480)
        width, height = 640, 480
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (25, 25, 112)  # 深蓝色背景
        
        # 分割错误信息为多行
        lines = []
        current_line = ""
        words = error_message.split()
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            # 估计文本宽度
            (text_width, _), _ = cv2.getTextSize(test_line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            if text_width < width - 40:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        
        # 添加标题
        title = "SYSTEM ERROR"
        # 获取文本尺寸以实现精确居中
        (text_width, text_height), baseline = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        title_position = ((width - text_width) // 2, 50)
        cv2.putText(frame, title, title_position, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        
        # 添加错误信息
        line_height = 25
        start_y = 100
        
        for i, line in enumerate(lines[:18]):  # 最多显示18行
            position = (20, start_y + i * line_height)
            cv2.putText(frame, line, position, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # 添加时间戳
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp_position = (width - 200, height - 20)
        cv2.putText(frame, timestamp, timestamp_position, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        return frame

    def _reopen_camera(self):
        """尝试重新打开摄像头"""
        logging.info(f"[{self.name}] 尝试重新打开摄像头...")
        
        # 释放旧的相机资源
        if self.camera:
            try:
                self.camera.release()
            except Exception as e:
                logging.error(f"[{self.name}] 释放相机资源时发生错误: {e}")
            self.camera = None
        
        # 尝试打开相机
        self.camera = cv2.VideoCapture(self.camera_id)
        if not self.camera.isOpened():
            # 尝试其他摄像头ID
            logging.warning(f"[{self.name}] 无法打开摄像头 {self.camera_id}，尝试其他摄像头ID")
            for i in range(3):
                if i != self.camera_id:
                    self.camera = cv2.VideoCapture(i)
                    if self.camera.isOpened():
                        self.camera_id = i
                        logging.info(f"[{self.name}] 成功打开摄像头 {i}")
                        break
        
        if self.camera and self.camera.isOpened():
            # 设置相机参数
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            self.camera.set(cv2.CAP_PROP_FPS, self.fps)
            
            # 获取实际参数
            actual_width = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
            self.resolution = (actual_width, actual_height)
            self.fps = actual_fps if actual_fps > 0 else 30
            
            logging.info(f"[{self.name}] 摄像头重新初始化完成，分辨率: {self.resolution}, FPS: {self.fps}")
            return True
        else:
            logging.error(f"[{self.name}] 无法重新打开任何摄像头")
            return False

    def _main(self, enable_streaming=False):
        """相机应用主循环"""
        logging.info(f"[{self.name}] 正在初始化相机...")

        try:
            # 检测可用编码器
            self._detect_codecs()

            # 初始打开相机
            if not self._reopen_camera():
                logging.warning(f"[{self.name}] 无法打开任何相机，将以客户端模式运行")
                self.camera = None
                return

            # 启动TCP服务器（如果启用流媒体）
            if self.is_streaming or enable_streaming:
                self.is_streaming = True
                self._start_tcp_server()

            # 主循环：捕获和处理帧
            while self.running:
                # 检查相机是否打开
                if not self.camera or not self.camera.isOpened():
                    logging.warning(f"[{self.name}] 摄像头未打开，尝试重新打开")
                    if not self._reopen_camera():
                        error_message = f"Failed to open camera {self.camera_id}, trying other camera IDs failed"
                        logging.error(f"[{self.name}] 无法打开摄像头 {self.camera_id}，尝试其他摄像头ID失败")
                        # 生成错误画面
                        error_frame = self._create_error_frame(error_message)
                        # 更新当前帧数据为错误画面
                        if self.is_streaming:
                            try:
                                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                                _, encoded_frame = cv2.imencode('.jpg', error_frame, encode_param)
                                with self.frame_lock:
                                    self.current_frame_data = encoded_frame.tobytes()
                            except Exception as e:
                                logging.error(f"[{self.name}] 更新错误帧数据时发生错误: {e}")
                        time.sleep(5)
                        continue

                # 读取帧
                try:
                    ret, frame = self.camera.read()

                    if not ret:
                        logging.warning(f"[{self.name}] 无法从相机读取帧，尝试重新打开摄像头")
                        if not self._reopen_camera():
                            error_message = f"Failed to read frame from camera, reopening camera failed"
                            logging.error(f"[{self.name}] 无法从相机读取帧，重新打开摄像头失败")
                            # 生成错误画面
                            error_frame = self._create_error_frame(error_message)
                            # 更新当前帧数据为错误画面
                            if self.is_streaming:
                                try:
                                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                                    _, encoded_frame = cv2.imencode('.jpg', error_frame, encode_param)
                                    with self.frame_lock:
                                        self.current_frame_data = encoded_frame.tobytes()
                                except Exception as e:
                                    logging.error(f"[{self.name}] 更新错误帧数据时发生错误: {e}")
                            time.sleep(5)
                            continue
                        else:
                            # 重新打开成功后，跳过当前循环，等待下一帧
                            continue
                    
                    # 应用白平衡校正
                    if self.white_balance:
                        frame = self.gray_world_white_balance(frame)

                    # 检查并启动TCP服务器（如果需要）
                    if self.is_streaming and not self.tcp_server_running:
                        logging.info(f"[{self.name}] 检测到流媒体模式，启动TCP服务器")
                        self._start_tcp_server()

                    # 录制视频
                    if self.is_recording and self.video_writer is not None:
                        self.video_writer.write(frame)

                    # 保存帧为图片
                    if self.is_saving_frames:
                        self._save_frame(frame)
                        self.is_saving_frames = False

                    # TCP流媒体传输
                    if self.is_streaming:
                        try:
                            # 添加时间戳和水印
                            frame_with_overlays = self._add_timestamp_and_watermark(frame)
                            # 压缩图像以减少带宽
                            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                            _, encoded_frame = cv2.imencode('.jpg', frame_with_overlays, encode_param)
                            # 更新当前帧数据（线程安全）
                            with self.frame_lock:
                                self.current_frame_data = encoded_frame.tobytes()
                        except Exception as e:
                            logging.error(f"[{self.name}] 更新帧数据时发生错误: {e}")
                            # 生成错误画面
                            error_message = f"Error processing frame data: {str(e)}"
                            error_frame = self._create_error_frame(error_message)
                            # 更新当前帧数据为错误画面
                            try:
                                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 95]
                                _, encoded_frame = cv2.imencode('.jpg', error_frame, encode_param)
                                with self.frame_lock:
                                    self.current_frame_data = encoded_frame.tobytes()
                            except Exception as e:
                                logging.error(f"[{self.name}] 更新错误帧数据时发生错误: {e}")

                    # 中继流媒体传输
                    if self.relay_streaming:
                        try:
                            # 发送帧通过中继（使用current_frame_data）
                            success = self.send_frame_via_relay(use_current_frame=True)
                            if not success:
                                logging.warning(f"[{self.name}] 中继流发送失败，关闭中继")
                                self.stop_relay_streaming()
                        except Exception as e:
                            logging.error(f"[{self.name}] 中继流传输时发生错误: {e}")
                            # 发生错误时关闭中继
                            self.stop_relay_streaming()

                    # 添加延迟以控制帧率
                    time.sleep(max(0.01, 1 / self.fps - 0.01))

                except Exception as e:
                    import traceback
                    error_message = f"Error reading from camera: {str(e)}\n{traceback.format_exc()}"
                    logging.error(f"[{self.name}] 相机读取时发生错误: {e}")
                    # 生成错误画面
                    error_frame = self._create_error_frame(error_message)
                    # 更新当前帧数据为错误画面
                    if self.is_streaming:
                        try:
                            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                            _, encoded_frame = cv2.imencode('.jpg', error_frame, encode_param)
                            with self.frame_lock:
                                self.current_frame_data = encoded_frame.tobytes()
                        except Exception as e:
                            logging.error(f"[{self.name}] 更新错误帧数据时发生错误: {e}")
                    # 尝试重新打开摄像头
                    if not self._reopen_camera():
                        logging.error(f"[{self.name}] 无法打开摄像头，5秒后再次尝试")
                        time.sleep(5)

        except Exception as e:
            logging.error(f"[{self.name}] 相机运行时发生错误: {e}")
            raise
        finally:
            self._cleanup()

    def capture_photo(self, filename=None, save_to_disk=True):
        """拍照

        Args:
            filename: 文件名（可选），如果不指定则自动生成
            save_to_disk: 是否保存到磁盘
        Returns:
            保存的文件路径（如果保存到磁盘），否则返回图像数据
        """
        if not self.camera or not self.camera.isOpened():
            logging.error(f"[{self.name}] 相机未就绪，无法拍照")
            return None

        try:
            ret, frame = self.camera.read()
            if not ret:
                logging.error(f"[{self.name}] 拍照失败")
                return None
            
            # 应用白平衡校正
            if self.white_balance:
                frame = self.gray_world_white_balance(frame)

            if save_to_disk:
                if filename is None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"photo_{timestamp}.{self.image_format}"

                filepath = os.path.join(self.save_directory, filename)

                # 根据格式保存图像
                if self.image_format.lower() == "jpg" or self.image_format.lower() == "jpeg":
                    cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    cv2.imwrite(filepath, frame)

                logging.info(f"[{self.name}] 照片已保存: {filepath}")
                return filepath
            else:
                # 返回图像数据
                _, buffer = cv2.imencode(f'.{self.image_format}', frame)
                return buffer.tobytes()

        except Exception as e:
            logging.error(f"[{self.name}] 拍照时发生错误: {e}")
            return None

    def start_recording(self, filename=None):
        """开始录制视频

        Args:
            filename: 视频文件名（可选）
        Returns:
            是否成功
        """
        if self.is_recording:
            logging.warning(f"[{self.name}] 已经在录制中")
            return False

        if not self.camera or not self.camera.isOpened():
            logging.error(f"[{self.name}] 相机未就绪，无法录制")
            return False

        try:
            # 生成文件名
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"video_{timestamp}{self.video_ext}"

            filepath = os.path.join(self.video_directory, filename)

            # 获取当前帧的尺寸
            ret, frame = self.camera.read()
            if not ret:
                logging.error(f"[{self.name}] 无法获取帧尺寸")
                return False

            height, width = frame.shape[:2]

            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            self.video_writer = cv2.VideoWriter(
                filepath,
                fourcc,
                self.fps,
                (width, height)
            )

            if not self.video_writer.isOpened():
                # 尝试其他编码器
                logging.warning(f"[{self.name}] 编码器 {self.codec} 不可用，尝试其他编码器")
                alt_codecs = ['mp4v', 'XVID', 'MJPG']
                for codec in alt_codecs:
                    try:
                        fourcc = cv2.VideoWriter_fourcc(*codec)
                        self.video_writer = cv2.VideoWriter(
                            filepath.replace(self.video_ext, '.avi'),
                            fourcc,
                            self.fps,
                            (width, height)
                        )
                        if self.video_writer.isOpened():
                            logging.info(f"[{self.name}] 使用备用编码器: {codec}")
                            break
                    except:
                        continue

                if not self.video_writer.isOpened():
                    logging.error(f"[{self.name}] 无法创建视频文件")
                    self.video_writer = None
                    return False

            self.is_recording = True
            self.video_filename = filepath
            self.record_start_time = time.time()

            logging.info(f"[{self.name}] 开始录制视频: {filepath}，编码器: {self.codec}")
            return True

        except Exception as e:
            logging.error(f"[{self.name}] 开始录制时发生错误: {e}")
            self.video_writer = None
            return False

    def stop_recording(self):
        """停止录制视频"""
        if not self.is_recording or self.video_writer is None:
            logging.warning(f"[{self.name}] 未在录制中")
            return False

        try:
            self.is_recording = False
            self.video_writer.release()
            self.video_writer = None

            record_duration = time.time() - self.record_start_time
            file_size = os.path.getsize(self.video_filename) / (1024 * 1024)  # MB

            logging.info(f"[{self.name}] 停止录制，视频已保存: {self.video_filename}")
            logging.info(f"[{self.name}] 时长: {record_duration:.2f}秒，大小: {file_size:.2f}MB")

            self.video_filename = None
            self.record_start_time = None
            return True

        except Exception as e:
            logging.error(f"[{self.name}] 停止录制时发生错误: {e}")
            return False

    # ============== TCP服务器功能 ==============

    def start_streaming(self, port=5001):
        """启动TCP图像流服务器

        Args:
            port: TCP端口号
        """
        if self.is_streaming:
            logging.warning(f"[{self.name}] 已经在流媒体模式")
            return False

        self.tcp_port = port
        self.is_streaming = True

        # 如果主循环尚未启动，需要手动启动TCP服务器
        if not self.running:
            self._start_tcp_server()

        logging.info(f"[{self.name}] TCP图像流服务器已启动，端口: {port}")
        return True

    def stop_streaming(self):
        """停止TCP图像流"""
        if not self.is_streaming:
            logging.warning(f"[{self.name}] 未在流媒体模式")
            return False

        self.is_streaming = False

        # 关闭TCP服务器
        self._stop_tcp_server()

        logging.info(f"[{self.name}] TCP图像流已停止")
        return True

    def _start_tcp_server(self):
        """启动TCP服务器"""

        def tcp_server_thread():
            try:
                self.tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.tcp_server.bind(('0.0.0.0', self.tcp_port))
                self.tcp_server.listen(5)
                self.tcp_server.settimeout(1.0)

                self.tcp_server_running = True
                logging.info(f"[{self.name}] TCP服务器监听端口 {self.tcp_port}")

                while self.running and self.is_streaming:
                    try:
                        client_socket, client_address = self.tcp_server.accept()
                        logging.info(f"[{self.name}] 新客户端连接: {client_address}")

                        # 为新客户端创建线程
                        client_thread = threading.Thread(
                            target=self._handle_client,
                            args=(client_socket, client_address)
                        )
                        client_thread.daemon = True
                        client_thread.start()

                        self.tcp_clients.append((client_socket, client_thread))

                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.running and self.is_streaming:
                            logging.error(f"[{self.name}] 接受客户端连接时发生错误: {e}")

            except Exception as e:
                logging.error(f"[{self.name}] TCP服务器运行错误: {e}")
            finally:
                self.tcp_server_running = False

        # 启动TCP服务器线程
        self.tcp_thread = threading.Thread(target=tcp_server_thread)
        self.tcp_thread.daemon = True
        self.tcp_thread.start()

    def _handle_client(self, client_socket, client_address):
        """处理TCP客户端连接"""
        try:
            # 发送初始信息
            init_data = json.dumps({
                "resolution": self.resolution,
                "fps": self.fps,
                "timestamp": time.time(),
                "codec": self.codec
            }).encode('utf-8')

            # 发送数据长度和数据
            client_socket.send(struct.pack('I', len(init_data)))
            client_socket.send(init_data)

            frame_count = 0
            last_send_time = time.time()
            frame_interval = (1.0 / self.fps) * 0.8  # 每帧的时间间隔
            while self.running and self.is_streaming:
                try:
                    # 检查是否需要停止
                    if not self.running or not self.is_streaming:
                        break
                    
                    # 计算当前时间与上次发送时间的差值
                    current_time = time.time()
                    time_since_last_send = current_time - last_send_time
                    
                    # 如果时间间隔不足，等待
                    if time_since_last_send < frame_interval:
                        time.sleep(frame_interval - time_since_last_send)
                    
                    # 从成员变量获取当前帧数据（线程安全）
                    with self.frame_lock:
                        frame_data = self.current_frame_data

                    # 如果没有帧数据，等待一下再重试
                    if frame_data is None:
                        time.sleep(0.01)
                        continue

                    # 获取当前时间戳
                    timestamp = time.time()
                    timestamp_bytes = struct.pack('d', timestamp)
                    
                    # 发送时间戳和帧数据
                    # 1. 发送时间戳（8字节）
                    client_socket.send(timestamp_bytes)
                    # 2. 发送帧数据长度和数据
                    client_socket.send(struct.pack('I', len(frame_data)))
                    client_socket.send(frame_data)

                    # 更新上次发送时间
                    last_send_time = time.time()
                    
                    frame_count += 1
                    if frame_count % 100 == 0:
                        logging.debug(f"[{self.name}] 向客户端 {client_address} 发送了 {frame_count} 帧")

                except Exception as e:
                    logging.warning(f"[{self.name}] 向客户端 {client_address} 发送数据时发生错误: {e}")
                    break

        except Exception as e:
            logging.error(f"[{self.name}] 处理客户端 {client_address} 时发生错误: {e}")
        finally:
            client_socket.close()
            logging.info(f"[{self.name}] 客户端 {client_address} 已断开连接")

    def _stop_tcp_server(self):
        """停止TCP服务器"""
        # 关闭所有客户端连接
        for client_socket, _ in self.tcp_clients:
            try:
                client_socket.close()
            except:
                pass

        self.tcp_clients.clear()

        # 关闭服务器
        if self.tcp_server:
            try:
                self.tcp_server.close()
            except:
                pass

        # 等待线程结束
        if self.tcp_thread and self.tcp_thread.is_alive():
            self.tcp_thread.join(timeout=2.0)

        self.tcp_server = None
        self.tcp_thread = None
        self.tcp_server_running = False

        # 重置当前帧数据
        with self.frame_lock:
            self.current_frame_data = None

    # ============== TCP客户端功能 ==============

    def receive_stream(self, server_ip, server_port, save_to_file=False, filename=None, display=False, fps=None, timeout=10, white_balance=False):
        """连接到TCP图像服务器并立即开始接收流

        Args:
            server_ip: 服务器IP地址
            server_port: 服务器端口
            save_to_file: 是否保存为视频文件
            filename: 视频文件名（可选）
            display: 是否实时显示图像
            fps: 视频帧率（可选），默认None使用服务器协商帧率
            timeout: 连接超时时间（秒）
            white_balance: 是否启用白平衡校正，默认禁用
        Returns:
            连接和接收是否成功
        """
        stream_key = f"{server_ip}:{server_port}"
        
        # 检查是否已经在接收该流
        if stream_key in self.client_receiving and self.client_receiving[stream_key]:
            logging.warning(f"[{self.name}] 已经在接收来自 {stream_key} 的流")
            return False

        # 连接到服务器
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(timeout)
            client_socket.connect((server_ip, server_port))
            client_socket.settimeout(None)  # 重置超时

            logging.info(f"[{self.name}] 已连接到TCP服务器 {server_ip}:{server_port}")

        except Exception as e:
            logging.error(f"[{self.name}] 连接TCP服务器失败: {e}")
            return False

        # 接收服务器信息并开始接收流
        try:
            # 接收初始信息长度
            data_len_bytes = client_socket.recv(4)
            if len(data_len_bytes) != 4:
                logging.error(f"[{self.name}] 接收初始信息失败")
                client_socket.close()
                return False

            data_len = struct.unpack('I', data_len_bytes)[0]

            # 接收初始信息
            init_data = b''
            while len(init_data) < data_len:
                chunk = client_socket.recv(data_len - len(init_data))
                if not chunk:
                    break
                init_data += chunk

            if len(init_data) != data_len:
                logging.error(f"[{self.name}] 接收初始信息不完整")
                client_socket.close()
                return False

            server_info = json.loads(init_data.decode('utf-8'))
            logging.info(f"[{self.name}] 服务器信息: {server_info}")

            # 初始化视频写入器（如果需要保存）
            client_video_writer = None
            client_video_filename = None
            client_save_video = False
            client_video_fps = 30
            
            if save_to_file:
                if filename is None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"stream_{timestamp}{self.video_ext}"

                filepath = os.path.join(self.video_directory, filename)

                # 解析分辨率
                if 'resolution' in server_info:
                    width, height = server_info['resolution']
                else:
                    width, height = 640, 480  # 默认分辨率

                # 确定视频帧率
                if fps is not None:
                    initial_fps = fps  # 使用用户指定的帧率
                    logging.info(f"[{self.name}] 使用用户指定的帧率: {initial_fps}fps")
                elif 'fps' in server_info:
                    initial_fps = server_info['fps']  # 使用服务器协商的帧率
                    logging.info(f"[{self.name}] 使用服务器协商的帧率: {initial_fps}fps")
                else:
                    initial_fps = 30  # 默认帧率
                    logging.info(f"[{self.name}] 使用默认帧率: {initial_fps}fps")

                # 创建视频写入器
                fourcc = cv2.VideoWriter_fourcc(*self.codec)
                client_video_writer = cv2.VideoWriter(
                    filepath,
                    fourcc,
                    initial_fps,
                    (width, height)
                )

                if not client_video_writer.isOpened():
                    logging.error(f"[{self.name}] 无法创建视频文件")
                    client_video_writer = None
                    save_to_file = False
                else:
                    client_video_filename = filepath
                    client_save_video = True
                    client_video_fps = initial_fps  # 保存视频写入器的帧率
                    logging.info(f"[{self.name}] 开始保存视频流到: {filepath}，初始帧率: {initial_fps}fps")

            # 初始化帧存储
            with self.frame_lock:
                self.frames[stream_key] = {
                    "frame": None,
                    "active": True,
                    "last_access": time.time()
                }

            # 启动接收线程
            self.tcp_client_sockets[stream_key] = client_socket
            self.client_receiving[stream_key] = True
            
            # 启动接收线程，传递必要的参数
            self.client_threads[stream_key] = threading.Thread(
                target=self._client_receive_thread,
                kwargs={
                    'stream_key': stream_key,
                    'client_socket': client_socket,
                    'client_video_writer': client_video_writer,
                    'client_video_filename': client_video_filename,
                    'client_save_video': client_save_video,
                    'client_video_fps': client_video_fps,
                    'white_balance': white_balance,
                    'display': display
                }
            )
            self.client_threads[stream_key].daemon = True
            self.client_threads[stream_key].start()

            # 启动自动断开检测线程（如果还没有启动）
            if not self.auto_disconnect_running:
                self._start_auto_disconnect_thread()

            logging.info(f"[{self.name}] 开始接收来自 {stream_key} 的TCP图像流，显示: {display}, 保存: {save_to_file}")
            return True

        except Exception as e:
            logging.error(f"[{self.name}] 启动接收流失败: {e}")
            # 发生错误时自动断开连接
            if client_socket:
                try:
                    client_socket.close()
                except:
                    pass
            return False

    def _client_receive_thread(self, stream_key, client_socket, client_video_writer, client_video_filename, client_save_video, client_video_fps, white_balance=False, display=False):
        """TCP客户端接收线程
        
        Args:
            stream_key: 流的唯一标识（IP:端口）
            client_socket: 客户端socket对象
            client_video_writer: 视频写入器对象
            client_video_filename: 视频文件名
            client_save_video: 是否保存视频
            client_video_fps: 视频帧率
            white_balance: 是否启用白平衡校正，默认禁用
            display: 是否显示图像
        """
        # 启动视频写入线程（如果需要保存视频）
        write_thread = None
        if client_save_video and client_video_writer:
            write_thread = threading.Thread(
                target=self._video_write_thread,
                args=(stream_key, client_video_writer, client_video_fps)
            )
            write_thread.daemon = True
            write_thread.start()
            logging.info(f"[{self.name}] 视频写入线程已启动")
        
        frame_count = 0
        start_time = time.time()

        try:
            while stream_key in self.client_receiving and self.client_receiving[stream_key] and client_socket:
                try:
                    # 接收时间戳（8字节）
                    timestamp_bytes = client_socket.recv(8)
                    if len(timestamp_bytes) != 8:
                        logging.warning(f"[{self.name}] 接收时间戳失败，可能连接断开")
                        break
                    
                    # 解析时间戳
                    server_timestamp = struct.unpack('d', timestamp_bytes)[0]
                    
                    # 接收帧数据长度
                    frame_len_bytes = client_socket.recv(4)
                    if len(frame_len_bytes) != 4:
                        logging.warning(f"[{self.name}] 接收帧长度失败，可能连接断开")
                        break

                    frame_len = struct.unpack('I', frame_len_bytes)[0]

                    # 接收帧数据
                    frame_data = b''
                    while len(frame_data) < frame_len:
                        chunk = client_socket.recv(min(4096, frame_len - len(frame_data)))
                        if not chunk:
                            break
                        frame_data += chunk

                    # print(f"[{self.name}] 接收第 {frame_count} 帧，数据: {frame_data}")
                    if len(frame_data) != frame_len:
                        logging.warning(f"[{self.name}] 接收帧数据不完整")
                        break

                    # 解码图像
                    nparr = np.frombuffer(frame_data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                    if frame is None:
                        logging.warning(f"[{self.name}] 解码图像失败")
                        continue
                    
                    # 应用白平衡校正
                    if white_balance:
                        frame = self.gray_world_white_balance(frame)

                    frame_count += 1
                    
                    # 更新当前帧缓冲区（线程安全）
                    with self.frame_lock:
                        if stream_key in self.frames:
                            self.frames[stream_key]["frame"] = frame
                            self.frames[stream_key]["last_access"] = time.time()
                    
                    # 显示图像
                    if display:
                        cv2.imshow(f'TCP Image Stream - {stream_key}', frame)

                        # 检查窗口是否被关闭
                        if cv2.getWindowProperty(f'TCP Image Stream - {stream_key}', cv2.WND_PROP_VISIBLE) < 1:
                            logging.info(f"[{self.name}] 显示窗口已关闭")
                            cv2.destroyWindow(f'TCP Image Stream - {stream_key}')

                        # 按'q'键退出
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord('q'):
                            logging.info(f"[{self.name}] 用户按q键退出显示")
                            cv2.destroyWindow(f'TCP Image Stream - {stream_key}')

                    # 每100帧输出一次状态
                    if frame_count % 100 == 0:
                        elapsed_time = time.time() - start_time
                        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
                        logging.debug(f"[{self.name}] 已接收 {frame_count} 帧，平均接收FPS: {fps:.2f}")

                except socket.timeout:
                    continue
                except Exception as e:
                    logging.error(f"[{self.name}] 接收帧时发生错误: {e}")
                    break

        except Exception as e:
            logging.error(f"[{self.name}] 接收线程发生错误: {e}")
        finally:
            # 等待写入线程结束
            if write_thread and write_thread.is_alive():
                write_thread.join(timeout=2.0)
            self._stop_receiving_stream(stream_key, client_socket, client_video_writer, client_video_filename)

    def _video_write_thread(self, stream_key, client_video_writer, client_video_fps):
        """视频写入线程：按照固定时间间隔写入视频帧
        
        Args:
            stream_key: 流的唯一标识（IP:端口）
            client_video_writer: 视频写入器对象
            client_video_fps: 视频帧率
        """
        if not client_video_writer:
            return
        
        # 使用传入的帧率值
        fps = client_video_fps
        logging.info(f"[{self.name}] 视频写入线程使用帧率: {fps}fps")
        
        frame_interval = 1.0 / fps  # 每帧的时间间隔（秒）
        next_write_time = time.time()
        written_frames = 0
        start_time = time.time()
        
        logging.info(f"[{self.name}] 视频写入线程开始工作，目标帧率: {fps}fps，帧间隔: {frame_interval:.4f}秒")
        
        try:
            while stream_key in self.client_receiving and self.client_receiving[stream_key] and client_video_writer:
                current_time = time.time()
                
                # 检查是否到达写入时间
                if current_time >= next_write_time:
                    # 获取当前帧（线程安全）
                    frame_to_write = None
                    with self.frame_lock:
                        if stream_key in self.frames:
                            frame_to_write = self.frames[stream_key]["frame"]
                    
                    # 如果有帧，写入视频
                    if frame_to_write is not None:
                        client_video_writer.write(frame_to_write)
                        written_frames += 1
                        
                        # 每100帧输出一次状态
                        if written_frames % 100 == 0:
                            elapsed_time = time.time() - start_time
                            actual_fps = written_frames / elapsed_time if elapsed_time > 0 else 0
                            logging.debug(f"[{self.name}] 已写入 {written_frames} 帧，实际写入FPS: {actual_fps:.2f}")
                    
                    # 计算下一次写入时间
                    next_write_time += frame_interval
                    
                    # 如果落后太多，跳过一些时间点
                    if next_write_time < current_time - frame_interval:
                        next_write_time = current_time + frame_interval
                
                # 短暂休眠，避免CPU占用过高
                sleep_time = max(0.001, next_write_time - current_time - 0.001)
                time.sleep(sleep_time)
                
        except Exception as e:
            logging.error(f"[{self.name}] 视频写入线程发生错误: {e}")
        
        logging.info(f"[{self.name}] 视频写入线程结束，共写入 {written_frames} 帧")

    def stop_receiving_stream(self, stream_key=None):
        """停止接收TCP图像流
        
        Args:
            stream_key: 流的唯一标识（IP:端口），如果为None则停止所有流
        """
        if stream_key:
            # 停止指定的流
            if stream_key in self.client_receiving and self.client_receiving[stream_key]:
                self.client_receiving[stream_key] = False

                # 等待线程结束
                if stream_key in self.client_threads and self.client_threads[stream_key].is_alive():
                    self.client_threads[stream_key].join(timeout=2.0)

                # 清理资源
                if stream_key in self.tcp_client_sockets:
                    client_socket = self.tcp_client_sockets[stream_key]
                    client_video_writer = None  # 视频写入器在 _stop_receiving_stream 中处理
                    client_video_filename = None  # 视频文件名在 _stop_receiving_stream 中处理
                    self._stop_receiving_stream(stream_key, client_socket, client_video_writer, client_video_filename)

                logging.info(f"[{self.name}] 已停止接收来自 {stream_key} 的TCP图像流")
                return True
            else:
                logging.warning(f"[{self.name}] 流 {stream_key} 不存在或未在接收")
                return False
        else:
            # 停止所有流
            for key in list(self.client_receiving.keys()):
                if self.client_receiving[key]:
                    self.stop_receiving_stream(key)
            logging.info(f"[{self.name}] 已停止所有TCP图像流")
            return True

    def _stop_receiving_stream(self, stream_key, client_socket, client_video_writer, client_video_filename):
        """停止接收流的内部清理
        
        Args:
            stream_key: 流的唯一标识（IP:端口）
            client_socket: 客户端socket对象
            client_video_writer: 视频写入器对象
            client_video_filename: 视频文件名
        """
        # 关闭显示窗口
        try:
            cv2.destroyWindow(f'TCP Image Stream - {stream_key}')
        except:
            pass

        # 关闭视频写入器
        if client_video_writer:
            client_video_writer.release()
            if client_video_filename and os.path.exists(client_video_filename):
                file_size = os.path.getsize(client_video_filename) / (1024 * 1024)
                logging.info(f"[{self.name}] 视频流已保存: {client_video_filename}，大小: {file_size:.2f}MB")

        # 关闭套接字
        if client_socket:
            try:
                client_socket.close()
            except:
                pass

        # 清理字典
        with self.frame_lock:
            if stream_key in self.frames:
                del self.frames[stream_key]
        
        if stream_key in self.tcp_client_sockets:
            del self.tcp_client_sockets[stream_key]
        
        if stream_key in self.client_receiving:
            del self.client_receiving[stream_key]
        
        if stream_key in self.client_threads:
            del self.client_threads[stream_key]

    def disconnect_from_server(self):
        """断开与TCP服务器的连接"""
        self.stop_receiving_stream()
        logging.info(f"[{self.name}] 已断开与TCP服务器的连接")

    # ============== 辅助功能 ==============

    def _save_frame(self, frame):
        """保存当前帧为图片"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"frame_{timestamp}.{self.image_format}"
            filepath = os.path.join(self.save_directory, filename)

            if self.image_format.lower() == "jpg" or self.image_format.lower() == "jpeg":
                cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            else:
                cv2.imwrite(filepath, frame)

            logging.debug(f"[{self.name}] 帧已保存: {filepath}")

        except Exception as e:
            logging.error(f"[{self.name}] 保存帧时发生错误: {e}")

    def save_current_frame(self):
        """保存当前帧（异步）"""
        self.is_saving_frames = True

    def get_camera_info(self):
        """获取相机信息"""
        if not self.camera or not self.camera.isOpened():
            return {"status": "camera_not_available"}

        try:
            # 尝试读取一帧来检查相机状态
            ret, _ = self.camera.read()

            info = {
                "status": "active" if ret else "error",
                "camera_id": self.camera_id,
                "resolution": self.resolution,
                "fps": self.fps,
                "is_recording": self.is_recording,
                "is_streaming": self.is_streaming,
                "stream_port": self.tcp_port if self.is_streaming else None,
                "video_filename": self.video_filename if self.is_recording else None,
                "save_directory": self.save_directory,
                "video_directory": self.video_directory,
                "codec": self.codec,
                "video_ext": self.video_ext,
                "use_h264": self.use_h264,
                "client_receiving": self.client_receiving,
                "client_display": self.client_display,
                "client_save_video": self.client_save_video
            }

            if self.is_recording and self.record_start_time:
                info["record_duration"] = time.time() - self.record_start_time

            return info

        except Exception as e:
            logging.error(f"[{self.name}] 获取相机信息时发生错误: {e}")
            return {"status": "error", "error": str(e)}

    def set_resolution(self, width, height, fps=None):
        """设置相机分辨率和帧率

        Args:
            width: 宽度
            height: 高度
            fps: 帧率（可选）
        Returns:
            是否成功
        """
        if not self.camera or not self.camera.isOpened():
            logging.error(f"[{self.name}] 相机未就绪，无法设置分辨率")
            return False

        try:
            # 先停止录制（如果需要）
            was_recording = self.is_recording
            if was_recording:
                self.stop_recording()

            # 更新分辨率和帧率参数
            self.resolution = (width, height)
            if fps is not None:
                self.fps = fps

            # 重新打开摄像头以应用新参数
            success = self._reopen_camera()

            # 如果之前在录制，重新开始
            if success and was_recording:
                self.start_recording()

            if success:
                if fps is not None:
                    logging.info(f"[{self.name}] 分辨率已设置为: {self.resolution}, 帧率已设置为: {self.fps}")
                else:
                    logging.info(f"[{self.name}] 分辨率已设置为: {self.resolution}")
            else:
                logging.error(f"[{self.name}] 重新打开摄像头失败，分辨率设置可能未生效")
                
            return success

        except Exception as e:
            logging.error(f"[{self.name}] 设置分辨率时发生错误: {e}")
            return False

    def _cleanup(self):
        """清理资源"""
        try:
            # 停止录制
            if self.is_recording and self.video_writer is not None:
                self.stop_recording()

            # 停止TCP服务器
            if self.is_streaming:
                self.stop_streaming()

            # 停止TCP客户端
            self.stop_receiving_stream()

            # 释放相机
            if self.camera is not None:
                self.camera.release()
                self.camera = None

            # 重置当前帧数据
            with self.frame_lock:
                self.current_frame_data = None

            logging.info(f"[{self.name}] 资源已清理")

        except Exception as e:
            logging.error(f"[{self.name}] 清理资源时发生错误: {e}")

    def _add_timestamp_and_watermark(self, frame):
        """在图像上添加时间戳和水印

        Args:
            frame: 原始图像帧
        Returns:
            添加了时间戳和水印的图像帧
        """
        # 复制帧以避免修改原始帧
        frame_with_overlays = frame.copy()
        height, width = frame_with_overlays.shape[:2]

        # 添加时间戳（左上角）
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp_text = f"{timestamp}"
        timestamp_position = (30, 30)  # 左上角位置
        timestamp_font = cv2.FONT_HERSHEY_SIMPLEX
        timestamp_font_scale = 0.7
        timestamp_font_color = (255, 255, 255)  # 白色
        timestamp_thickness = 2
        timestamp_bg_color = (0, 0, 0)  # 黑色背景

        # 获取文本尺寸
        (text_width, text_height), _ = cv2.getTextSize(timestamp_text, timestamp_font, timestamp_font_scale, timestamp_thickness)

        # 绘制黑色背景
        cv2.rectangle(frame_with_overlays, 
                      (timestamp_position[0] - 5, timestamp_position[1] - text_height - 5),
                      (timestamp_position[0] + text_width + 5, timestamp_position[1] + 5),
                      timestamp_bg_color, -1)

        # 绘制时间戳文本
        cv2.putText(frame_with_overlays, timestamp_text, timestamp_position, 
                    timestamp_font, timestamp_font_scale, timestamp_font_color, timestamp_thickness)

        # 添加半透明水印（右下角）
        watermark_text = "SmartJianKong"
        watermark_position = (width - 300, height - 30)  # 右下角位置
        watermark_font = cv2.FONT_HERSHEY_SIMPLEX
        watermark_font_scale = 1.2
        watermark_font_color = (255, 255, 255)  # 白色
        watermark_thickness = 3

        # 创建水印层
        watermark_layer = frame_with_overlays.copy()

        # 绘制水印文本
        cv2.putText(watermark_layer, watermark_text, watermark_position, 
                    watermark_font, watermark_font_scale, watermark_font_color, watermark_thickness)

        # 混合水印层和原始帧，实现半透明效果
        alpha = 0.5  # 水印透明度
        cv2.addWeighted(watermark_layer, alpha, frame_with_overlays, 1 - alpha, 0, frame_with_overlays)

        return frame_with_overlays



    # ============== 中继相关功能 ==============

    def set_relay_app(self, relay_app):
        """设置RelayApp实例"""
        self.relay_app = relay_app
        logging.info(f"[{self.name}] RelayApp已设置")

    def start_relay_streaming(self, room_id):
        """通过中继开始流式传输
        
        Args:
            room_id: 中继房间ID
        """
        if not self.relay_app:
            logging.error(f"[{self.name}] RelayApp未设置，无法启动中继流")
            return False
        
        if self.relay_streaming:
            logging.warning(f"[{self.name}] 中继流已在运行")
            return False
        
        self.relay_room_id = room_id
        self.relay_streaming = True
        
        # 注册数据接收回调
        self.relay_app.register_receive_callback(self._relay_data_received, room_id)
        # 注册错误回调
        self.relay_app.register_error_callback(self._relay_error_callback, room_id)
        
        logging.info(f"[{self.name}] 中继流已启动，房间ID: {room_id}")
        return True

    def stop_relay_streaming(self):
        """停止中继流式传输"""
        if not self.relay_streaming:
            return False
        
        self.relay_streaming = False
        self.relay_room_id = None
        logging.info(f"[{self.name}] 中继流已停止")
        return True

    def send_frame_via_relay(self, frame=None, use_current_frame=False):
        """通过中继发送一帧图像（使用时间戳+数据长度格式）
        
        Args:
            frame: 图像帧（numpy数组），如果use_current_frame为True则忽略
            use_current_frame: 是否使用self.current_frame_data
        """
        if not self.relay_streaming or not self.relay_app or not self.relay_room_id:
            return False
        
        try:
            if use_current_frame:
                # 使用现有的current_frame_data
                with self.frame_lock:
                    frame_data = self.current_frame_data
                
                if frame_data is None:
                    logging.warning(f"[{self.name}] current_frame_data 为 None")
                    return False
            else:
                # 编码图像为JPEG
                success, encoded_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not success:
                    logging.error(f"[{self.name}] 图像编码失败")
                    return False
                
                # 转换为字节
                frame_data = encoded_frame.tobytes()
            
            # 获取当前时间戳
            timestamp = time.time()
            timestamp_bytes = struct.pack('d', timestamp)
            
            # 构造数据包：时间戳(8字节) + 数据长度(4字节) + 数据
            data_length = len(frame_data)
            length_bytes = struct.pack('I', data_length)
            
            # 组合数据包
            packet = timestamp_bytes + length_bytes + frame_data
            
            # 发送数据
            return self.relay_app.send_data(self.relay_room_id, packet)
        except Exception as e:
            logging.error(f"[{self.name}] 发送中继帧时出错: {e}")
            return False

    def start_relay_receiving(self, room_id):
        """通过中继开始接收视频流
        
        Args:
            room_id: 中继房间ID
        """
        if not self.relay_app:
            logging.error(f"[{self.name}] RelayApp未设置，无法启动中继接收")
            return False
        
        if room_id in self.relay_receiving and self.relay_receiving[room_id]:
            logging.warning(f"[{self.name}] 已经在接收来自房间 {room_id} 的中继流")
            return False
        
        # 注册数据接收回调
        self.relay_app.register_receive_callback(self._relay_data_received, room_id)
        # 注册错误回调
        self.relay_app.register_error_callback(self._relay_error_callback, room_id)
        
        # 初始化帧存储
        with self.frame_lock:
            self.frames[room_id] = {
                "frame": None,
                "active": True,
                "last_access": time.time()
            }
        
        self.relay_receiving[room_id] = True
        self.relay_frame_queues[room_id] = queue.Queue()
        
        # 启动接收处理线程
        thread = threading.Thread(
            target=self._relay_receive_thread,
            args=(room_id,)
        )
        thread.daemon = True
        thread.start()
        
        # 启动自动断开检测线程（如果还没有启动）
        if not self.auto_disconnect_running:
            self._start_auto_disconnect_thread()
        
        logging.info(f"[{self.name}] 中继接收已启动，房间ID: {room_id}")
        return True

    def stop_relay_receiving(self, room_id=None):
        """停止中继接收
        
        Args:
            room_id: 中继房间ID，如果为None则停止所有中继接收
        """
        if room_id:
            # 停止指定的中继接收
            if room_id in self.relay_receiving and self.relay_receiving[room_id]:
                self.relay_receiving[room_id] = False
                
                # 调用RelayApp的方法停止接收线程
                if self.relay_app:
                    self.relay_app.stop_client_thread(room_id)
                
                # 清理资源
                with self.frame_lock:
                    if room_id in self.frames:
                        del self.frames[room_id]
                
                if room_id in self.relay_frame_queues:
                    del self.relay_frame_queues[room_id]
                
                logging.info(f"[{self.name}] 中继接收已停止，房间ID: {room_id}")
                return True
            else:
                logging.warning(f"[{self.name}] 房间 {room_id} 不存在或未在接收")
                return False
        else:
            # 停止所有中继接收
            for key in list(self.relay_receiving.keys()):
                if self.relay_receiving[key]:
                    self.stop_relay_receiving(key)
            logging.info(f"[{self.name}] 所有中继接收已停止")
            return True

    def _relay_data_received(self, room_id, data, timestamp):
        """中继数据接收回调函数"""
        # 检查房间是否在接收列表中
        if room_id in self.relay_receiving and self.relay_receiving[room_id]:
            # 将数据放入对应房间的队列
            if room_id in self.relay_frame_queues:
                self.relay_frame_queues[room_id].put((data, timestamp))

    def _relay_receive_thread(self, room_id):
        """中继接收线程（使用时间戳+数据长度格式）
        
        Args:
            room_id: 中继房间ID
        """
        while room_id in self.relay_receiving and self.relay_receiving[room_id]:
            try:
                # 从队列获取数据
                if room_id in self.relay_frame_queues:
                    data, timestamp = self.relay_frame_queues[room_id].get(timeout=1)
                    
                    # 检查数据长度
                    if len(data) < 12:  # 时间戳(8字节) + 数据长度(4字节)
                        logging.warning(f"[{self.name}] 中继数据过短: {len(data)}字节")
                        continue
                    
                    try:
                        # 解析时间戳（8字节）
                        server_timestamp = struct.unpack('d', data[0:8])[0]
                        
                        # 解析数据长度（4字节）
                        data_length = struct.unpack('I', data[8:12])[0]
                        
                        # 检查数据长度合理性
                        if data_length <= 0 or data_length > 10 * 1024 * 1024:  # 最大10MB
                            logging.warning(f"[{self.name}] 数据长度异常: {data_length}")
                            continue
                        
                        # 提取图像数据
                        frame_data = data[12:12 + data_length]
                        
                        # 检查图像数据长度
                        if len(frame_data) != data_length:
                            logging.warning(f"[{self.name}] 图像数据长度不匹配: {len(frame_data)}/{data_length}")
                            continue
                        
                        # 检查JPEG文件头
                        if not frame_data.startswith(b'\xff\xd8'):
                            logging.warning(f"[{self.name}] 不是有效的JPEG数据")
                            continue
                        
                        # 解码图像
                        nparr = np.frombuffer(frame_data, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        
                        if frame is None:
                            logging.warning(f"[{self.name}] 解码中继图像失败")
                            continue
                        
                        # 应用白平衡校正
                        if self.white_balance:
                            frame = self.gray_world_white_balance(frame)
                        
                        # 更新当前帧缓冲区
                        with self.frame_lock:
                            if room_id in self.frames:
                                self.frames[room_id]["frame"] = frame
                                self.frames[room_id]["last_access"] = time.time()
                        
                        # 显示图像（如果启用）
                        if self.client_display:
                            cv2.imshow(f'Relay Image Stream - {room_id}', frame)
                            
                            # 按'q'键退出
                            key = cv2.waitKey(1) & 0xFF
                            if key == ord('q'):
                                logging.info(f"[{self.name}] 用户按q键退出中继显示")
                                cv2.destroyWindow(f'Relay Image Stream - {room_id}')
                    except Exception as decode_error:
                        logging.warning(f"[{self.name}] 解码图像时出错: {decode_error}")
                        continue
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"[{self.name}] 中继接收线程错误: {e}")
                time.sleep(0.1)
    
    def _relay_error_callback(self, room_id, error_message):
        """中继错误回调函数
        
        Args:
            room_id: 房间ID
            error_message: 错误信息
        """
        # 检查房间是否在接收列表中
        if room_id in self.relay_receiving and self.relay_receiving[room_id]:
            logging.error(f"[{self.name}] 中继错误: {error_message}")
            
            # 停止中继接收
            self.stop_relay_receiving(room_id)
            
            # 停止中继发送（如果当前正在为该房间发送）
            if self.relay_streaming and self.relay_room_id == room_id:
                self.stop_relay_streaming()

    def get_relay_status(self):
        """获取中继状态"""
        # 计算队列大小
        queue_sizes = {}
        for room_id, queue in self.relay_frame_queues.items():
            queue_sizes[room_id] = queue.qsize()
        
        return {
            'relay_app_set': self.relay_app is not None,
            'relay_streaming': self.relay_streaming,
            'relay_receiving_rooms': list(self.relay_receiving.keys()),
            'relay_room_id': self.relay_room_id,
            'relay_frame_queue_sizes': queue_sizes
        }

    def _start_auto_disconnect_thread(self):
        """启动自动断开检测线程"""
        if self.auto_disconnect_running:
            return
        
        self.auto_disconnect_running = True
        
        def auto_disconnect_thread():
            """自动断开检测线程函数"""
            while self.auto_disconnect_running:
                try:
                    # 每30秒检测一次
                    time.sleep(30)
                    
                    # 检查所有TCP流
                    with self.frame_lock:
                        tcp_streams_to_stop = []
                        for stream_key, frame_info in self.frames.items():
                            # 检查是否是TCP流（格式为 IP:端口）
                            if ':' in stream_key and stream_key in self.client_receiving and self.client_receiving[stream_key]:
                                # 检查是否活跃
                                if not frame_info.get("active", False):
                                    tcp_streams_to_stop.append(stream_key)
                                # 重置活跃状态
                                frame_info["active"] = False
                        
                        # 检查所有中继流
                        relay_rooms_to_stop = []
                        for room_id in self.relay_receiving:
                            if self.relay_receiving[room_id] and room_id in self.frames:
                                frame_info = self.frames[room_id]
                                if not frame_info.get("active", False):
                                    relay_rooms_to_stop.append(room_id)
                                # 重置活跃状态
                                frame_info["active"] = False
                    
                    # 停止不活跃的TCP流
                    for stream_key in tcp_streams_to_stop:
                        logging.info(f"[{self.name}] 检测到TCP流 {stream_key} 不活跃，自动停止")
                        self.stop_receiving_stream(stream_key)
                    
                    # 停止不活跃的中继流
                    for room_id in relay_rooms_to_stop:
                        logging.info(f"[{self.name}] 检测到中继流 {room_id} 不活跃，自动停止")
                        self.stop_relay_receiving(room_id)
                    
                except Exception as e:
                    logging.error(f"[{self.name}] 自动断开检测线程错误: {e}")
                    time.sleep(1)
        
        # 启动线程
        self.auto_disconnect_thread = threading.Thread(target=auto_disconnect_thread)
        self.auto_disconnect_thread.daemon = True
        self.auto_disconnect_thread.start()
        logging.info(f"[{self.name}] 自动断开检测线程已启动")
    
    def _reset(self):
        """重置应用状态（补充中继状态重置）"""
        self._cleanup()
        self.is_recording = False
        self.is_streaming = False
        self.is_saving_frames = False
        
        # 重置TCP客户端状态
        self.tcp_client_sockets = {}
        self.client_receiving = {}
        self.client_threads = {}
        self.client_display = False
        self.client_save_video = False
        
        # 重置中继状态
        self.relay_streaming = False
        self.relay_room_id = None
        self.relay_receiving = {}
        self.relay_frame_queues = {}
        
        # 重置帧存储
        self.frames = {}
        
        # 停止自动断开检测线程
        self.auto_disconnect_running = False
        if self.auto_disconnect_thread and self.auto_disconnect_thread.is_alive():
            self.auto_disconnect_thread.join(timeout=2.0)

        logging.info(f"[{self.name}] 应用已重置")

    def get_frame(self, stream_key):
        """获取指定流的当前帧
        
        Args:
            stream_key: 流的唯一标识（IP:端口或房间ID）
            
        Returns:
            当前帧（numpy数组），如果流不存在或没有帧则返回None
        """
        with self.frame_lock:
            if stream_key in self.frames:
                # 更新活跃状态
                self.frames[stream_key]["active"] = True
                self.frames[stream_key]["last_access"] = time.time()
                return self.frames[stream_key]["frame"]
            return None
    
    def get_status(self):
        """获取应用状态（重写父类方法）"""
        base_status = super().get_status()
        camera_info = self.get_camera_info()

        base_status.update({
            "camera_info": camera_info,
            "is_recording": self.is_recording,
            "is_streaming": self.is_streaming,
            "tcp_port": self.tcp_port,
            "save_directory": self.save_directory,
            "video_directory": self.video_directory,
            "codec": self.codec,
            "client_receiving": self.client_receiving,
            "client_display": self.client_display,
            "client_save_video": self.client_save_video,
            "relay_status": self.get_relay_status()
        })

        return base_status