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
                    'target'] == 'nvr' or msg_dict['target'] == 'p2p':
                    if msg_dict['msg'] == 'shutdown':
                        self.system.power = False
                    elif msg_dict["msg"] == 'who':
                        # 使用STP发送消息
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                self.stp_app.send_msg(target_addr, 'me')
                    elif msg_dict['msg'].startswith('nvr.stream.receive'):
                        # 接收流并保存
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到接收流指令')
                            # 解析命令参数
                            cmd_parts = shlex.split(msg_dict['msg'])
                            server_ip = None
                            server_port = None
                            filename = None
                            fps = None
                            
                            # 解析参数
                            i = 1
                            while i < len(cmd_parts):
                                if cmd_parts[i] == '--ip' and i + 1 < len(cmd_parts):
                                    server_ip = cmd_parts[i + 1]
                                    i += 2
                                elif cmd_parts[i] == '--port' and i + 1 < len(cmd_parts):
                                    try:
                                        server_port = int(cmd_parts[i + 1])
                                        i += 2
                                    except ValueError:
                                        i += 2
                                elif cmd_parts[i] == '--filename' and i + 1 < len(cmd_parts):
                                    filename = cmd_parts[i + 1]
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
                            if server_ip and server_port:
                                # 调用CameraApp的方法接收流
                                try:
                                    success = self.camera_app.receive_stream(
                                        server_ip=server_ip,
                                        server_port=server_port,
                                        save_to_file=True,
                                        filename=filename,
                                        fps=fps
                                    )
                                    logging.info(f'[{self.name}] 开始接收流: {server_ip}:{server_port}')
                                    # 回复成功消息
                                    if self.stp_app:
                                        target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                        if target_addr:
                                            self.stp_app.send_msg(target_addr, f'stream receiving started: {server_ip}:{server_port}')
                                except Exception as e:
                                    logging.error(f'[{self.name}] 接收流时出错: {e}')
                            else:
                                logging.error(f'[{self.name}] 接收流命令参数不完整，需要--ip和--port参数')
                    elif msg_dict['msg'] == 'nvr.stream.stop':
                        # 停止接收流
                        if self.camera_app:
                            logging.info(f'[{self.name}] 收到停止接收流指令')
                            # 调用CameraApp的方法停止接收流
                            try:
                                # 假设CameraApp有stop_receiving_stream方法
                                if hasattr(self.camera_app, 'stop_receiving_stream'):
                                    success = self.camera_app.stop_receiving_stream()
                                    logging.info(f'[{self.name}] 停止接收流成功')
                                    # 回复成功消息
                                    if self.stp_app:
                                        target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                        if target_addr:
                                            self.stp_app.send_msg(target_addr, 'stream receiving stopped')
                                else:
                                    logging.error(f'[{self.name}] CameraApp未实现stop_receiving_stream方法')
                            except Exception as e:
                                logging.error(f'[{self.name}] 停止接收流时出错: {e}')
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
                                    'result': None
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
                    else:
                        logging.error(f'[{self.name}] 未知指令: {msg_dict["msg"]}')
            except queue.Empty:
                continue

    def _reset(self):
        if self.stp_app:
            self.stp_app.unsubscribe_msg(self.name)
