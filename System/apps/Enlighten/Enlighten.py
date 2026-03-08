# System/apps/EnlightenApp.py
import multiprocessing
import logging
import threading
import time
import cv2
import numpy as np
from System.core.base_app import BaseApp


# 在子进程中运行Enlighten模型的函数
def enlighten_worker(input_queue, output_queue, stop_event, model_path=None):
    """Enlighten模型工作进程"""
    try:
        # 动态导入，避免在主进程中加载
        from enlighten_inference import EnlightenOnnxModel

        # 初始化模型
        model = EnlightenOnnxModel(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        if model.graph.get_providers() != ["CUDAExecutionProvider", "CPUExecutionProvider"]:
            logging.warning(
                f"[EnlightenWorker] Enlighten设备初始化出错，性能可能会受到影响！当前可用设备：{model.graph.get_providers()}")

        logging.info("[EnlightenWorker] Enlighten模型加载完成")

        while not stop_event.is_set():
            try:
                # 非阻塞获取输入
                if input_queue.empty():
                    time.sleep(0.01)  # 短暂休眠避免空转
                    continue

                # 获取待处理图像
                task_id, image_data = input_queue.get(timeout=1.0)

                if image_data is None:  # 停止信号
                    break

                # 处理图像
                try:
                    enhanced_image = model.predict(image_data)

                    # 返回处理结果
                    output_queue.put((task_id, enhanced_image, None))

                except Exception as e:
                    logging.error(f"[EnlightenWorker] 图像处理失败: {e}")
                    output_queue.put((task_id, None, str(e)))

            except Exception as e:
                if not stop_event.is_set():
                    logging.error(f"[EnlightenWorker] 工作循环错误: {e}")
                continue

    except Exception as e:
        logging.error(f"[EnlightenWorker] 进程启动失败: {e}")
    finally:
        logging.info("[EnlightenWorker] 进程结束")
        # 清理资源
        if 'model' in locals():
            del model


class EnlightenApp(BaseApp):
    """Enlighten图像增强应用"""

    def __init__(self, system):
        super().__init__(system, "EnlightenApp", "1.9.7")

        # 进程管理
        self.worker_process = None
        self.stop_event = multiprocessing.Event()

        # 通信队列
        self.input_queue = multiprocessing.Queue(maxsize=10)  # 限制队列大小避免内存溢出
        self.output_queue = multiprocessing.Queue(maxsize=10)

        # 任务管理
        self.task_counter = 0
        self.pending_tasks = {}  # {task_id: (callback, timestamp)}
        self.max_pending_time = 30  # 最大等待时间(秒)

        # 状态
        self.model_loaded = False

    def _main(self):
        """主循环 - 管理工作进程和处理结果"""
        # 启动工作进程
        self.worker_process = multiprocessing.Process(
            target=enlighten_worker,
            args=(self.input_queue, self.output_queue, self.stop_event)
        )
        self.worker_process.daemon = True
        self.worker_process.start()

        logging.info(f"[{self.name}] Enlighten工作进程已启动")

        # 清理过期任务的线程
        cleanup_thread = threading.Thread(target=self._cleanup_worker)
        cleanup_thread.daemon = True
        cleanup_thread.start()

        try:
            while self.running:
                # 处理输出结果
                self._process_outputs()

                # 检查工作进程状态
                if not self.worker_process.is_alive():
                    logging.warning(f"[{self.name}] 工作进程异常退出，尝试重启")
                    self._restart_worker()

                time.sleep(0.01)  # 降低CPU占用

        except Exception as e:
            logging.error(f"[{self.name}] 主循环错误: {e}")
        finally:
            self._cleanup()

    def _cleanup_worker(self):
        """清理过期任务的线程"""
        while self.running:
            try:
                current_time = time.time()
                expired_tasks = []

                # 使用线程安全的方式访问共享数据
                # 这里不需要额外的锁，因为主循环和清理线程都在主进程中运行
                task_items = list(self.pending_tasks.items())

                # 查找过期任务
                for task_id, (callback, timestamp) in task_items:
                    if current_time - timestamp > self.max_pending_time:
                        expired_tasks.append(task_id)

                # 移除过期任务
                for task_id in expired_tasks:
                    if task_id in self.pending_tasks:
                        del self.pending_tasks[task_id]
                        logging.warning(f"[{self.name}] 任务 {task_id} 已过期")

                time.sleep(5)  # 每5秒检查一次
            except Exception as e:
                logging.error(f"[{self.name}] 清理线程错误: {e}")
                time.sleep(1)

    def _process_outputs(self):
        """处理工作进程的输出"""
        try:
            while not self.output_queue.empty():
                task_id, result, error = self.output_queue.get_nowait()

                if task_id in self.pending_tasks:
                    callback, _ = self.pending_tasks[task_id]

                    if callback:
                        try:
                            callback(result, error)
                        except Exception as e:
                            logging.error(f"[{self.name}] 回调函数执行失败: {e}")

                    # 移除已完成的任务
                    del self.pending_tasks[task_id]

        except Exception as e:
            logging.error(f"[{self.name}] 处理输出时出错: {e}")

    def _restart_worker(self):
        """重启工作进程"""
        self._stop_worker()

        # 清空队列
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except:
                pass

        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except:
                pass

        # 重新启动
        self.stop_event.clear()
        self.worker_process = multiprocessing.Process(
            target=enlighten_worker,
            args=(self.input_queue, self.output_queue, self.stop_event)
        )
        self.worker_process.daemon = True
        self.worker_process.start()

        logging.info(f"[{self.name}] 工作进程已重启")

    def _stop_worker(self):
        """停止工作进程"""
        if self.worker_process and self.worker_process.is_alive():
            # 发送停止信号
            self.stop_event.set()

            # 等待进程结束
            self.worker_process.join(timeout=5.0)

            if self.worker_process.is_alive():
                self.worker_process.terminate()
                self.worker_process.join(timeout=2.0)

                if self.worker_process.is_alive():
                    self.worker_process.kill()

    def enhance_image(self, image, callback=None):
        """
        增强图像

        Args:
            image: 输入图像(numpy array)
            callback: 回调函数，格式: callback(enhanced_image, error)

        Returns:
            task_id: 任务ID，用于跟踪任务状态
        """
        if not self.running:
            raise RuntimeError("EnlightenApp未运行")

        if not isinstance(image, np.ndarray):
            raise ValueError("输入必须是numpy数组")

        # 生成任务ID
        self.task_counter += 1
        task_id = self.task_counter

        # 添加到待处理队列
        self.pending_tasks[task_id] = (callback, time.time())

        try:
            # 发送到工作进程
            self.input_queue.put((task_id, image), timeout=1.0)
            return task_id

        except Exception as e:
            # 移除失败的任务
            if task_id in self.pending_tasks:
                del self.pending_tasks[task_id]
            raise RuntimeError(f"无法提交任务: {e}")

    def enhance_image_sync(self, image, timeout=10.0):
        """
        同步增强图像

        Args:
            image: 输入图像
            timeout: 超时时间(秒)

        Returns:
            enhanced_image: 增强后的图像
        """
        result_container = {'result': None, 'error': None, 'completed': False}

        def callback(result, error):
            result_container['result'] = result
            result_container['error'] = error
            result_container['completed'] = True

        task_id = self.enhance_image(image, callback)

        # 等待结果
        start_time = time.time()
        while not result_container['completed']:
            if time.time() - start_time > timeout:
                # 移除超时任务
                if task_id in self.pending_tasks:
                    del self.pending_tasks[task_id]
                raise TimeoutError("图像增强超时")
            time.sleep(0.01)

        # 处理结果
        if result_container['error']:
            raise RuntimeError(f"图像增强失败: {result_container['error']}")

        return result_container['result']

    def get_pending_task_count(self):
        """获取待处理任务数量"""
        return len(self.pending_tasks)

    def _cleanup(self):
        """清理资源"""
        self._stop_worker()

        # 清空队列
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except:
                pass

        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except:
                pass

        # 清空待处理任务
        self.pending_tasks.clear()

        logging.info(f"[{self.name}] 资源清理完成")

    def _reset(self):
        """重置应用"""
        self._cleanup()
        self.task_counter = 0
        self.model_loaded = False

    def get_status(self):
        """获取应用状态"""
        status = super().get_status()
        status.update({
            "model_loaded": self.model_loaded,
            "pending_tasks": len(self.pending_tasks),
            "worker_alive": self.worker_process.is_alive() if self.worker_process else False
        })
        return status