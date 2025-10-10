# System/apps/cloud_VideoStreamServer.py
import multiprocessing
import threading
import time
import logging
import cv2
import numpy as np
import flask
import requests
from System.core.base_app import BaseApp
from flask import Response
import queue
import copy


# 在子进程中运行Flask服务器的函数
def run_flask_server(port, image_url, stop_event, enlighten_input_queue, enlighten_output_queue):
    """在子进程中运行Flask服务器"""
    app = flask.Flask(__name__)

    # 共享队列 - 只用于YOLO检测
    processed_frame_queue = queue.Queue(maxsize=10)  # 处理后的图像队列，专门给YOLO使用

    # 共享最新帧数据 - 用于测试页面显示（不消耗队列）
    latest_frames = {
        'original': None,
        'enhanced': None,
        'output': None
    }
    frames_lock = threading.Lock()  # 保护最新帧数据的锁
    enlighten_running = True

    def image_acquisition_thread():
        """图像获取线程 - 不断获取图像"""
        while not stop_event.is_set():
            try:
                # 获取最新图片
                response = requests.get(image_url, stream=True, timeout=5)
                if response.status_code == 200:
                    # 获取图片二进制数据
                    frame_data = response.content

                    # 转换为OpenCV格式
                    img_array = np.frombuffer(frame_data, np.uint8)
                    original_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                    if original_img is None:
                        logging.warning("[VideoStreamServer] 图像解码失败")
                        continue

                    # 处理增强图像
                    enhanced_img = original_img
                    if enlighten_running:
                        try:
                            # 通过队列向主进程请求图像增强
                            task_id = str(time.time())
                            enlighten_input_queue.put((task_id, original_img))

                            # 等待结果（带超时）
                            start_time = time.time()
                            while time.time() - start_time < 5.0:  # 5秒超时
                                if not enlighten_output_queue.empty():
                                    result_id, result_img, error = enlighten_output_queue.get_nowait()
                                    if result_id == task_id:
                                        if error is None and result_img is not None:
                                            enhanced_img = result_img
                                        else:
                                            logging.error(f"[VideoStreamServer] 图像增强失败: {error}")
                                        break
                                time.sleep(0.01)
                            else:
                                logging.warning("[VideoStreamServer] 图像增强超时，使用原图")

                        except Exception as e:
                            logging.error(f"[VideoStreamServer] 图像增强通信失败: {e}")
                            enhanced_img = original_img

                    # 更新最新帧数据（用于测试页面）
                    with frames_lock:
                        latest_frames['original'] = original_img.copy()
                        latest_frames['enhanced'] = enhanced_img.copy()
                        latest_frames['output'] = enhanced_img.copy() if enlighten_running else original_img.copy()

                    # 只将输出帧放入队列（给YOLO使用）
                    if not processed_frame_queue.full():
                        output_img = enhanced_img if enlighten_running else original_img
                        processed_frame_queue.put(output_img)

                else:
                    logging.error(f"[VideoStreamServer] 获取图片失败，状态码: {response.status_code}")

            except Exception as e:
                logging.error(f"[VideoStreamServer] 获取图像时发生错误: {str(e)}")

            # 控制帧率（每秒10帧）
            time.sleep(0.1)

    # 启动图像获取线程
    acquisition_thread = threading.Thread(target=image_acquisition_thread)
    acquisition_thread.daemon = True
    acquisition_thread.start()

    def generate_frames_from_queue():
        """从队列生成视频帧 - 专门给YOLO使用"""
        while not stop_event.is_set():
            try:
                # 从队列获取帧（这会消耗队列）
                frame = processed_frame_queue.get(timeout=1.0)

                # 编码为JPEG
                _, encoded_img = cv2.imencode('.jpg', frame)
                frame_data = encoded_img.tobytes()

                # 以MJPEG帧格式输出
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"[VideoStreamServer] 生成队列帧时发生错误: {str(e)}")
                break

    def generate_frame_from_latest(mode='output'):
        """从最新帧数据生成单帧 - 用于测试页面（不消耗队列）"""
        while not stop_event.is_set():
            try:
                with frames_lock:
                    if latest_frames[mode] is not None:
                        frame = latest_frames[mode].copy()
                    else:
                        # 如果没有帧数据，生成一个黑色占位图像
                        frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(frame, "No Frame", (200, 240),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                # 编码为JPEG
                _, encoded_img = cv2.imencode('.jpg', frame)
                frame_data = encoded_img.tobytes()

                # 以MJPEG帧格式输出
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

                # 控制帧率
                time.sleep(0.1)

            except Exception as e:
                logging.error(f"[VideoStreamServer] 生成最新帧时发生错误: {str(e)}")
                break

    @app.route('/video_feed')
    def video_feed():
        """YOLO检测使用的视频流 - 消耗队列"""
        return Response(
            generate_frames_from_queue(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/video_feed_original')
    def video_feed_original():
        """测试页面原始图像视频流 - 不消耗队列"""
        return Response(
            generate_frame_from_latest(mode='original'),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/video_feed_enhance')
    def video_feed_enhance():
        """测试页面增强图像视频流 - 不消耗队列"""
        return Response(
            generate_frame_from_latest(mode='enhanced'),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/video_feed_output')
    def video_feed_output():
        """测试页面输出图像视频流 - 不消耗队列"""
        return Response(
            generate_frame_from_latest(mode='output'),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/set_enlighten/<status>')
    def set_enlighten(status):
        nonlocal enlighten_running
        enlighten_running = (status.lower() == 'true')
        return f"Enlighten状态已设置为: {enlighten_running}"

    @app.route('/status')
    def status():
        """返回服务器状态信息"""
        with frames_lock:
            has_frames = all(frame is not None for frame in latest_frames.values())

        return {
            'enlighten_running': enlighten_running,
            'processed_queue_size': processed_frame_queue.qsize(),
            'enlighten_input_queue_size': enlighten_input_queue.qsize() if hasattr(enlighten_input_queue,
                                                                                   'qsize') else 'N/A',
            'enlighten_output_queue_size': enlighten_output_queue.qsize() if hasattr(enlighten_output_queue,
                                                                                     'qsize') else 'N/A',
            'has_latest_frames': has_frames
        }

    @app.route('/')
    def index():
        """主页 - 测试页面使用不消耗队列的视频流"""
        current_status = status()
        enlighten_status = "已启用" if current_status['enlighten_running'] else "未启用"

        return f"""
        <html>
          <head>
            <title>图片视频流测试页面</title>
            <style>
                .container {{ display: flex; flex-direction: column; align-items: center; }}
                .row {{ display: flex; justify-content: space-around; width: 100%; margin-bottom: 20px; }}
                .stream-box {{ display: flex; flex-direction: column; align-items: center; margin: 10px; }}
                .stream-title {{ font-weight: bold; margin-bottom: 5px; }}
                .status-info {{ 
                    margin: 10px 0; 
                    padding: 10px; 
                    border-radius: 5px; 
                    background-color: #f0f0f0;
                    text-align: left;
                }}
                .warning {{ color: orange; font-weight: bold; }}
            </style>
            <script>
                function updateStatus() {{
                    fetch('/status')
                        .then(response => response.json())
                        .then(data => {{
                            const enlightenStatusText = data.enlighten_running ? "已启用" : "未启用";
                            const switchUrl = '/set_enlighten/' + (!data.enlighten_running).toString().toLowerCase();
                            const hasFramesWarning = data.has_latest_frames ? '' : '<p class="warning">⚠️ 等待第一帧数据...</p>';

                            document.getElementById('status-info').innerHTML = `
                                <p>Enlighten状态: {enlighten_status} (<a href="${{switchUrl}}">切换</a>)</p>
                                <p>YOLO队列大小: ${{data.processed_queue_size}}</p>
                                <p>增强输入队列: ${{data.enlighten_input_queue_size}}</p>
                                <p>增强输出队列: ${{data.enlighten_output_queue_size}}</p>
                                ${{hasFramesWarning}}
                                <p><small>注: 测试页面使用独立帧数据，不影响YOLO检测</small></p>
                            `;
                        }})
                        .catch(error => {{
                            console.error('获取状态失败:', error);
                            document.getElementById('status-info').innerHTML = '<p>状态获取失败</p>';
                        }});
                }}

                // 页面加载后立即更新状态，然后每2秒更新一次
                document.addEventListener('DOMContentLoaded', function() {{
                    updateStatus();
                    setInterval(updateStatus, 2000);
                }});
            </script>
          </head>
          <body>
            <div class="container">
              <h1>动态图片视频流测试页面</h1>
              <div class="status-info" id="status-info">
                <p>加载中...</p>
              </div>
              <p>当前源URL: <code>{image_url}</code></p>

              <div class="row">
                <div class="stream-box">
                  <div class="stream-title">原始图像</div>
                  <img src="/video_feed_original" width="320" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzIwIiBoZWlnaHQ9IjI0MCI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iZ3JheSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0id2hpdGUiPk5vIEltYWdlPC90ZXh0Pjwvc3ZnPg=='">
                </div>
                <div class="stream-box">
                  <div class="stream-title">增强图像</div>
                  <img src="/video_feed_enhance" width="320" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzIwIiBoZWlnaHQ9IjI0MCI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iZ3JheSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0id2hpdGUiPk5vIEltYWdlPC90ZXh0Pjwvc3ZnPg=='">
                </div>
              </div>

              <div class="row">
                <div class="stream-box">
                  <div class="stream-title">输出图像 (传递给YOLO)</div>
                  <img src="/video_feed_output" width="640" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjQwIiBoZWlnaHQ9IjQ4MCI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iZ3JheSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0id2hpdGUiPk5vIEltYWdlPC90ZXh0Pjwvc3ZnPg=='">
                </div>
              </div>

              <div style="margin-top: 20px; padding: 10px; background: #e0f7fa; border-radius: 5px;">
                <h3>说明</h3>
                <ul>
                  <li>测试页面使用独立的帧数据，不会消耗YOLO检测队列</li>
                  <li>三个图像流保持同步，来自同一时刻的帧</li>
                  <li>YOLO检测使用专用的 <code>/video_feed</code> 接口</li>
                  <li>页面自动刷新状态，显示队列使用情况</li>
                </ul>
              </div>
            </div>
          </body>
        </html>
        """

    # 运行服务器
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)


class VideoStreamServerApp(BaseApp):
    """视频流服务器应用"""

    def __init__(self, system, port=5000):
        super().__init__(system, "VideoStreamServerApp", "3.0.0")  # 版本升级
        self.port = port
        self.running = False
        self.image_url = None
        self.server_process = None
        self.stop_event = multiprocessing.Event()

        # 与EnlightenApp通信的队列
        self.enlighten_input_queue = multiprocessing.Queue()
        self.enlighten_output_queue = multiprocessing.Queue()

        # 处理Enlighten响应的线程
        self.enlighten_handler_thread = None

    def _main(self, image_url=None):
        """应用主循环"""
        if image_url:
            self.image_url = image_url
        if self.image_url is None:
            logging.error(f"[{self.name}] 未设置图像URL，无法启动服务器")
            return

        self.enlighten_app = self.system.get_app("EnlightenApp")

        if self.enlighten_app is None:
            logging.warning(f'[{self.name}] 警告：无法获取Enlighten图像增强模块实例！')

        # 启动Enlighten响应处理线程
        self.enlighten_handler_thread = threading.Thread(target=self._handle_enlighten_responses)
        self.enlighten_handler_thread.daemon = True
        self.enlighten_handler_thread.start()

        self.running = True
        self.server_process = multiprocessing.Process(
            target=run_flask_server,
            args=(self.port, self.image_url, self.stop_event,
                  self.enlighten_input_queue, self.enlighten_output_queue)
        )
        self.server_process.start()

        # 处理Enlighten请求的主循环
        try:
            while self.running:
                # 检查子进程状态
                if self.server_process and not self.server_process.is_alive():
                    logging.warning(f"[{self.name}] 子进程崩溃，尝试重启")
                    self._restart_server()

                # 处理来自子进程的Enlighten请求
                self._process_enlighten_requests()

                time.sleep(0.01)

        except Exception as e:
            logging.error(f"[{self.name}] 主循环错误: {e}")
        finally:
            self._cleanup()

    def _process_enlighten_requests(self):
        """处理来自子进程的Enlighten增强请求"""
        try:
            # 批量处理多个请求，提高效率
            processed_count = 0
            max_batch_size = 5

            while not self.enlighten_input_queue.empty() and processed_count < max_batch_size:
                task_id, image = self.enlighten_input_queue.get_nowait()


                if self.enlighten_app and self.enlighten_app.running:
                    try:
                        # 同步调用EnlightenApp
                        enhanced_image = self.enlighten_app.enhance_image_sync(image, timeout=3.0)
                        self.enlighten_output_queue.put((task_id, enhanced_image, None))
                    except Exception as e:
                        logging.error(f"[{self.name}] Enlighten处理失败: {e}")
                        self.enlighten_output_queue.put((task_id, None, str(e)))
                else:
                    self.enlighten_output_queue.put((task_id, None, "EnlightenApp不可用"))

                processed_count += 1

        except Exception as e:
            logging.error(f"[{self.name}] 处理Enlighten请求时出错: {e}")

    def _handle_enlighten_responses(self):
        """处理Enlighten响应（防止队列堵塞）"""
        while self.running:
            try:
                # 定期清空输出队列，避免堆积
                if self.enlighten_output_queue.qsize() > 20:
                    logging.warning(
                        f"[{self.name}] Enlighten输出队列堆积 ({self.enlighten_output_queue.qsize()})，清空中...")
                    keep_count = 5
                    temp_results = []
                    while not self.enlighten_output_queue.empty() and len(temp_results) < keep_count:
                        try:
                            result = self.enlighten_output_queue.get_nowait()
                            temp_results.append(result)
                        except:
                            break

                    while not self.enlighten_output_queue.empty():
                        try:
                            self.enlighten_output_queue.get_nowait()
                        except:
                            break

                    for result in temp_results:
                        self.enlighten_output_queue.put(result)

                    logging.info(f"[{self.name}] 已清理Enlighten输出队列，保留{len(temp_results)}个最新结果")

                time.sleep(2)
            except Exception as e:
                logging.error(f"[{self.name}] Enlighten响应处理错误: {e}")
                time.sleep(1)

    def _restart_server(self):
        """重启服务器子进程"""
        self._stop_server()

        while not self.enlighten_input_queue.empty():
            try:
                self.enlighten_input_queue.get_nowait()
            except:
                pass

        self.stop_event.clear()
        self.server_process = multiprocessing.Process(
            target=run_flask_server,
            args=(self.port, self.image_url, self.stop_event,
                  self.enlighten_input_queue, self.enlighten_output_queue)
        )
        self.server_process.start()
        logging.info(f"[{self.name}] 服务器子进程已重启")

    def _stop_server(self):
        """停止服务器子进程"""
        if self.server_process and self.server_process.is_alive():
            self.stop_event.set()
            self.server_process.join(timeout=5.0)
            if self.server_process.is_alive():
                self.server_process.terminate()
                self.server_process.join(timeout=2.0)
                if self.server_process.is_alive():
                    self.server_process.kill()

    def _cleanup(self):
        """清理资源"""
        self._stop_server()
        if self.server_process:
            self.server_process.close()
        self.server_process = None
        self.stop_event.clear()

    def _reset(self):
        """重置应用"""
        self._cleanup()
        self.image_url = None

    def set_image_url(self, image_url):
        """设置图像源URL"""
        self.image_url = image_url

    def get_status(self):
        """获取应用状态"""
        status = super().get_status()
        status.update({
            "image_url": self.image_url,
            "server_process_alive": self.server_process.is_alive() if self.server_process else False,
            "enlighten_input_queue_size": self.enlighten_input_queue.qsize() if hasattr(self.enlighten_input_queue,
                                                                                        'qsize') else 'N/A',
            "enlighten_output_queue_size": self.enlighten_output_queue.qsize() if hasattr(self.enlighten_output_queue,
                                                                                          'qsize') else 'N/A'
        })
        return status