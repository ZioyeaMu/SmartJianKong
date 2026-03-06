import logging
import os
import queue
import sys
import time
import shlex

import System.system
from System.core.base_app import BaseApp


class MsgHandleApp(BaseApp):
    def __init__(self, system):
        super().__init__(system, "MsgHandleApp", '1.0')
        self.msg_queue = queue.Queue()

    def _main(self):
        self.stp_app = self.system.get_app("STPApp")
        self.camera_app = self.system.get_app("CameraApp")
        
        if self.stp_app:
            logging.info(f'[{self.name}] 检测到已安装STP应用')
        else:
            logging.warning(f'[{self.name}] 未检测到STP应用！')

        if self.camera_app:
            logging.info(f'[{self.name}] 检测到已安装CameraApp')
        else:
            logging.warning(f'[{self.name}] 未检测到CameraApp！')

        if self.stp_app:
            # 订阅消息，使用应用名作为订阅者ID
            self.stp_app.subscribe_msg(self.name, self.msg_queue)

        while self.running:
            try:
                self.system: System.system.System

                msg_dict = self.msg_queue.get(timeout=1)
                if msg_dict['target'] == self.system.device_name or msg_dict['target'] == 'all' or msg_dict[
                    'target'] == 'monitor' or msg_dict['target'] == 'p2p':
                    if msg_dict['msg'] == 'shutdown':
                        self.system.power = False
                    elif msg_dict["msg"] == 'who':
                        # 使用STP发送消息
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                self.stp_app.send_msg(target_addr, 'me')
                    elif msg_dict['msg'] == 'camera.capture':
                        # 拍照
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到拍照指令')
                            # 调用CameraApp的方法拍照
                            try:
                                filename = self.camera_app.capture_photo()
                                logging.info(f'[{self.name}] 拍照成功，文件保存为: {filename}')
                                # 回复成功消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, f'photo captured: {filename}')
                            except Exception as e:
                                logging.error(f'[{self.name}] 拍照时出错: {e}')
                    elif msg_dict['msg'] == 'camera.record.start':
                        # 开始录制视频
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到开始录制视频指令')
                            # 调用CameraApp的方法开始录制视频
                            try:
                                filename = self.camera_app.start_recording()
                                logging.info(f'[{self.name}] 开始录制视频，文件保存为: {filename}')
                                # 回复成功消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, f'recording started: {filename}')
                            except Exception as e:
                                logging.error(f'[{self.name}] 开始录制视频时出错: {e}')
                    elif msg_dict['msg'] == 'camera.record.stop':
                        # 停止录制视频
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到停止录制视频指令')
                            # 调用CameraApp的方法停止录制视频
                            try:
                                filename = self.camera_app.stop_recording()
                                logging.info(f'[{self.name}] 停止录制视频，文件保存为: {filename}')
                                # 回复成功消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, f'recording stopped: {filename}')
                            except Exception as e:
                                logging.error(f'[{self.name}] 停止录制视频时出错: {e}')
                    elif msg_dict['msg'] == 'camera.stream.start':
                        # 启动流服务器
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到启动流服务器指令')
                            # 调用CameraApp的方法启动流服务器
                            try:
                                self.camera_app.start_streaming()
                                logging.info(f'[{self.name}] 流服务器已启动')
                                # 回复成功消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, 'stream started')
                            except Exception as e:
                                logging.error(f'[{self.name}] 启动流服务器时出错: {e}')
                    elif msg_dict['msg'] == 'camera.stream.stop':
                        # 关闭流服务器
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到关闭流服务器指令')
                            # 调用CameraApp的方法关闭流服务器
                            try:
                                self.camera_app.stop_streaming()
                                logging.info(f'[{self.name}] 流服务器已关闭')
                                # 回复成功消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, 'stream stopped')
                            except Exception as e:
                                logging.error(f'[{self.name}] 关闭流服务器时出错: {e}')
                    elif msg_dict['msg'].startswith('camera.resolution.set'):
                        # 设置相机分辨率
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到设置分辨率指令: {msg_dict["msg"]}')
                            # 解析命令参数
                            cmd_parts = shlex.split(msg_dict['msg'])
                            width = None
                            height = None
                            fps = None
                            
                            # 解析参数
                            i = 1
                            while i < len(cmd_parts):
                                if cmd_parts[i] == '--width' and i + 1 < len(cmd_parts):
                                    try:
                                        width = int(cmd_parts[i + 1])
                                        i += 2
                                    except ValueError:
                                        i += 2
                                elif cmd_parts[i] == '--height' and i + 1 < len(cmd_parts):
                                    try:
                                        height = int(cmd_parts[i + 1])
                                        i += 2
                                    except ValueError:
                                        i += 2
                                elif cmd_parts[i] == '--fps' and i + 1 < len(cmd_parts):
                                    try:
                                        fps = int(cmd_parts[i + 1])
                                        i += 2
                                    except ValueError:
                                        i += 2
                                else:
                                    i += 1
                            
                            # 验证参数
                            if width is not None and height is not None:
                                # 调用CameraApp的方法设置分辨率
                                try:
                                    success = self.camera_app.set_resolution(width, height, fps)
                                    if success:
                                        logging.info(f'[{self.name}] 分辨率设置成功')
                                        # 回复成功消息
                                        if self.stp_app:
                                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                            if target_addr:
                                                if fps:
                                                    self.stp_app.send_msg(target_addr, f'resolution set to {width}x{height} @ {fps}fps')
                                                else:
                                                    self.stp_app.send_msg(target_addr, f'resolution set to {width}x{height}')
                                    else:
                                        # 回复错误消息
                                        if self.stp_app:
                                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                            if target_addr:
                                                self.stp_app.send_msg(target_addr, f'error: resolution set failed')
                                        logging.error(f'[{self.name}] 分辨率设置失败')
                                except Exception as e:
                                    # 回复错误消息
                                    if self.stp_app:
                                        target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                        if target_addr:
                                            self.stp_app.send_msg(target_addr, f'error: {e}')
                                    logging.error(f'[{self.name}] 设置分辨率时出错: {e}')
                            else:
                                # 回复错误消息
                                if self.stp_app:
                                    target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                    if target_addr:
                                        self.stp_app.send_msg(target_addr, f'error: resolution set command incomplete, need --width and --height parameters')
                                logging.error(f'[{self.name}] 分辨率设置命令参数不完整，需要--width和--height参数')
                    elif msg_dict['msg'].startswith('eval '):
                        # 直接执行命令
                        logging.info(f'[{self.name}] 收到执行命令指令: {msg_dict["msg"]}')
                        # 解析命令参数
                        cmd_str = msg_dict['msg'][5:].strip()  # 截取 'eval ' 后面的部分
                        result = None
                        error = None
                        
                        try:
                            import threading
                            
                            # 定义执行函数
                            def eval_func():
                                nonlocal result
                                # 准备eval的局部变量
                                eval_locals = {
                                    'system': self.system,
                                    'self': self
                                }
                                # 直接执行命令
                                result = eval(cmd_str, {}, eval_locals)
                            
                            # 创建线程
                            thread = threading.Thread(target=eval_func)
                            # 启动线程
                            thread.start()
                            # 等待线程执行完成，最多等待10秒
                            thread.join(timeout=10)
                            
                            # 检查线程是否仍在运行
                            if thread.is_alive():
                                error = '命令执行超时（超过10秒）'
                                logging.error(f'[{self.name}] {error}')
                            else:
                                logging.info(f'[{self.name}] 命令执行成功: {cmd_str}')
                        except Exception as e:
                            error = f'执行命令时出错: {str(e)}'
                            logging.error(f'[{self.name}] {error}')
                        
                        # 回复结果
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                if error:
                                    self.stp_app.send_msg(target_addr, f'eval_Error:\n{error}')
                                else:
                                    self.stp_app.send_msg(target_addr, f'eval_Result:\n{result}')
                    elif msg_dict['msg'].startswith('exec '):
                        # 执行用户输入的一段代码
                        logging.info(f'[{self.name}] 收到执行代码指令: {msg_dict["msg"]}')
                        # 解析命令参数
                        code_str = msg_dict['msg'][5:].strip()  # 截取 'exec ' 后面的部分
                        result = None
                        error = None
                        
                        try:
                            import threading
                            
                            # 定义执行函数
                            def exec_func():
                                nonlocal result
                                # 准备exec的局部变量
                                exec_locals = {
                                    'system': self.system,
                                    'self': self,
                                    'result': '代码执行成功'
                                }
                                # 执行代码
                                exec(code_str, {}, exec_locals)
                                result = exec_locals.get('result', '代码执行成功')
                            
                            # 创建线程
                            thread = threading.Thread(target=exec_func)
                            # 启动线程
                            thread.start()
                            # 等待线程执行完成，最多等待10秒
                            thread.join(timeout=10)
                            
                            # 检查线程是否仍在运行
                            if thread.is_alive():
                                error = '代码执行超时（超过10秒）'
                                logging.error(f'[{self.name}] {error}')
                            else:
                                logging.info(f'[{self.name}] 代码执行成功')
                        except Exception as e:
                            error = f'执行代码时出错: {str(e)}'
                            logging.error(f'[{self.name}] {error}')
                        
                        # 回复结果
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                if error:
                                    self.stp_app.send_msg(target_addr, f'exec_Error:\n{error}')
                                else:
                                    self.stp_app.send_msg(target_addr, f'exec_Result:\n{result}')
                    elif msg_dict['msg'].startswith('sysrun '):
                        # 使用子进程执行系统命令
                        logging.info(f'[{self.name}] 收到系统命令执行指令: {msg_dict["msg"]}')
                        # 解析命令参数
                        cmd_str = msg_dict['msg'][7:].strip()  # 截取 'sysrun ' 后面的部分
                        result = None
                        error = None
                        
                        try:
                            import subprocess
                            # 执行系统命令
                            process = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=30)
                            # 构建结果
                            result = f'STDOUT:\n{process.stdout}STDERR:\n{process.stderr}RETCODE: {process.returncode}'
                            logging.info(f'[{self.name}] 系统命令执行成功: {cmd_str}')
                        except Exception as e:
                            error = f'执行系统命令时出错: {str(e)}'
                            logging.error(f'[{self.name}] {error}')
                        
                        # 回复结果
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                if error:
                                    self.stp_app.send_msg(target_addr, f'sysrun_Error:\n{error}')
                                else:
                                    self.stp_app.send_msg(target_addr, f'sysrun_Result:\n{result}')
                    elif msg_dict['msg'].startswith('relay_data.connect '):
                        # 处理中继连接请求
                        # 解析服务器地址和端口
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 3:
                            server_ip = parts[1]
                            server_port = int(parts[2])
                            # 获取RelayApp实例
                            relay_app = self.system.get_app("RelayApp")
                            if relay_app:
                                room_id = relay_app.connect_to_server(server_ip, server_port, action='create_room')
                                print(room_id)
                                if room_id:
                                    # 广播房间号给客户端（包含服务器地址和端口）
                                    if self.stp_app:
                                        target = msg_dict.get('user', None)
                                        if target:
                                            self.stp_app.broadcast_msg(f'relay_data.room {server_ip} {server_port} {room_id}', target=target)
                                else:
                                    logging.error(f'[{self.name}] 连接中继服务器失败')
                            else:
                                logging.warning(f'[{self.name}] RelayApp未安装')
                        else:
                            logging.error(f'[{self.name}] relay_data.connect 命令格式错误')
                    elif msg_dict['msg'].startswith('camera.start_relay_streaming '):
                        # 处理启动中继流命令
                        logging.info(f'[{self.name}] 收到启动中继流指令: {msg_dict["msg"]}')
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 3:
                            server_ip = parts[1]
                            server_port = int(parts[2])
                            # 获取RelayApp实例
                            relay_app = self.system.get_app("RelayApp")
                            if relay_app:
                                room_id = relay_app.connect_to_server(server_ip, server_port, action='create_room')
                                if room_id:
                                    logging.info(f'[{self.name}] 已连接到中继服务器，房间ID: {room_id}')
                                    # 广播房间号给客户端（包含服务器地址和端口）
                                    if self.stp_app:
                                        target = msg_dict.get('user', None)
                                        if target:
                                            self.stp_app.broadcast_msg(f'camera.relay_room {server_ip} {server_port} {room_id}', target=target)
                                    # 设置RelayApp到CameraApp并启动中继流
                                    if self.camera_app:
                                        self.camera_app.set_relay_app(relay_app)
                                        self.camera_app.start_relay_streaming(room_id)
                                        logging.info(f'[{self.name}] 已启动中继视频流')
                                else:
                                    logging.error(f'[{self.name}] 连接中继服务器失败')
                            else:
                                logging.warning(f'[{self.name}] RelayApp未安装')
                        else:
                            logging.error(f'[{self.name}] camera.start_relay_streaming 命令格式错误')
                    elif msg_dict['msg'] == 'camera.stop_relay_streaming':
                        # 处理停止中继流命令
                        logging.info(f'[{self.name}] 收到停止中继流指令: {msg_dict["msg"]}')
                        # 获取RelayApp实例
                        relay_app = self.system.get_app("RelayApp")
                        if relay_app:
                            # 停止CameraApp的中继流
                            if self.camera_app:
                                self.camera_app.stop_relay_streaming()
                                logging.info(f'[{self.name}] 已停止中继视频流')
                            # 可以在这里添加清理逻辑
                        else:
                            logging.warning(f'[{self.name}] RelayApp未安装')
                    elif msg_dict['msg'].startswith('relay_data.room '):
                        # 处理房间号消息
                        logging.info(f'[{self.name}] 收到房间号指令: {msg_dict["msg"]}')
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 2:
                            room_id = parts[1]
                            # 获取RelayApp实例
                            relay_app = self.system.get_app("RelayApp")
                            if relay_app:
                                # 这里可以触发客户端加入房间的逻辑
                                # 实际客户端可能在另一个设备上，所以这里可能只是记录房间号
                                logging.info(f'[{self.name}] 房间号: {room_id}')
                                # 客户端可能需要自动加入房间，但这里我们只是记录
                                # 实际加入逻辑可能在客户端消息处理器中
                            else:
                                logging.warning(f'[{self.name}] RelayApp未安装')
                        else:
                            logging.error(f'[{self.name}] relay_data.room 命令格式错误')
                    elif msg_dict['msg'].startswith('relay_data.joined'):
                        # 处理客户端加入成功的消息
                        logging.info(f'[{self.name}] 客户端已成功加入中继房间')
                        # 可以在这里添加额外的逻辑，比如确认连接成功
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 2:
                            room_id = parts[1]
                            logging.info(f'[{self.name}] 客户端加入房间: {room_id}')
                    else:
                        logging.error(f'[{self.name}] 未知指令: {msg_dict["msg"]}')
            except queue.Empty:
                continue

    def _reset(self):
        if self.stp_app:
            self.stp_app.unsubscribe_msg(self.name)
