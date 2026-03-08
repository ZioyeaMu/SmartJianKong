import logging
import os
import queue
import sys
import time

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
                            cmd_parts = msg_dict['msg'].split(' ')
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
                    elif msg_dict['msg'].startswith('cmd'):
                        # 直接执行命令
                        logging.info(f'[{self.name}] 收到执行命令指令: {msg_dict["msg"]}')
                        # 解析命令参数
                        cmd_parts = msg_dict['msg'].split(' ')
                        function_str = None
                        var_str = None
                        args_str = None
                        kwargs_str = None
                        
                        # 解析参数
                        i = 1
                        while i < len(cmd_parts):
                            if cmd_parts[i] == '--function' and i + 1 < len(cmd_parts):
                                function_str = cmd_parts[i + 1]
                                i += 2
                            elif cmd_parts[i] == '--var' and i + 1 < len(cmd_parts):
                                var_str = cmd_parts[i + 1]
                                i += 2
                            elif cmd_parts[i] == '--args' and i + 1 < len(cmd_parts):
                                args_str = cmd_parts[i + 1]
                                i += 2
                            elif cmd_parts[i] == '--kwargs' and i + 1 < len(cmd_parts):
                                kwargs_str = cmd_parts[i + 1]
                                i += 2
                            else:
                                i += 1
                        
                        # 执行命令
                        result = None
                        error = None
                        
                        try:
                            # 准备eval的局部变量
                            eval_locals = {
                                'system': self.system,
                                'self': self
                            }
                            
                            # 处理函数调用
                            if function_str:
                                # 解析args
                                args = []
                                if args_str:
                                    args = [eval(arg.strip(), {}, eval_locals) for arg in args_str.split(',')]
                                
                                # 解析kwargs
                                kwargs = {}
                                if kwargs_str:
                                    for item in kwargs_str.split(','):
                                        if '=' in item:
                                            key, value = item.split('=', 1)
                                            kwargs[key.strip()] = eval(value.strip(), {}, eval_locals)
                                
                                # 执行函数
                                func = eval(function_str, {}, eval_locals)
                                result = func(*args, **kwargs)
                                logging.info(f'[{self.name}] 函数执行成功: {function_str}')
                            
                            # 处理变量获取
                            elif var_str:
                                result = eval(var_str, {}, eval_locals)
                                logging.info(f'[{self.name}] 变量获取成功: {var_str}')
                            else:
                                error = '未指定--function或--var参数'
                                logging.error(f'[{self.name}] {error}')
                        except Exception as e:
                            error = f'执行命令时出错: {str(e)}'
                            logging.error(f'[{self.name}] {error}')
                        
                        # 回复结果
                        if self.stp_app:
                            target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                            if target_addr:
                                if error:
                                    self.stp_app.send_msg(target_addr, f'Error: {error}')
                                else:
                                    self.stp_app.send_msg(target_addr, f'Result: {result}')
                    elif msg_dict['msg'].startswith('camera.relay_room '):
                        # 处理相机中继房间消息，加入房间并接收监控流
                        logging.info(f'[{self.name}] 收到相机中继房间指令: {msg_dict["msg"]}')
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 4:
                            server_ip = parts[1]
                            server_port = int(parts[2])
                            room_id = parts[3]
                            # 获取RelayApp实例
                            relay_app = self.system.get_app("RelayApp")
                            if relay_app:
                                # 连接到中继服务器并加入房间
                                joined_room_id = relay_app.connect_to_server(server_ip, server_port, action='join_room', room_id=room_id)
                                if joined_room_id:
                                    logging.info(f'[{self.name}] 已加入中继房间: {joined_room_id}')
                                    # 启动接收监控流
                                    if self.camera_app:
                                        self.camera_app.set_relay_app(relay_app)
                                        self.camera_app.start_relay_receiving(joined_room_id)
                                        logging.info(f'[{self.name}] 已开始接收中继监控流')
                                    # 回复成功消息
                                    if self.stp_app:
                                        target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                        if target_addr:
                                            self.stp_app.send_msg(target_addr, f'relay_data.joined {joined_room_id}')
                                else:
                                    logging.error(f'[{self.name}] 加入中继房间失败')
                            else:
                                logging.warning(f'[{self.name}] RelayApp未安装')
                        else:
                            logging.error(f'[{self.name}] camera.relay_room 命令格式错误，需要: camera.relay_room <server_ip> <server_port> <room_id>')
                    elif msg_dict['msg'].startswith('relay_data.room '):
                        # 处理房间号消息，加入中继房间
                        logging.info(f'[{self.name}] 收到房间号指令: {msg_dict["msg"]}')
                        parts = msg_dict['msg'].split()
                        if len(parts) >= 4:
                            server_ip = parts[1]
                            server_port = int(parts[2])
                            room_id = parts[3]
                            # 获取RelayApp实例
                            relay_app = self.system.get_app("RelayApp")
                            if relay_app:
                                # 连接到中继服务器并加入房间
                                joined_room_id = relay_app.connect_to_server(server_ip, server_port, action='join_room', room_id=room_id)
                                if joined_room_id:
                                    logging.info(f'[{self.name}] 已加入中继房间: {joined_room_id}')
                                    # 可以回复成功消息
                                    if self.stp_app:
                                        target_addr = self.stp_app.core.arp.get(msg_dict.get('source_mac', None), None)
                                        if target_addr:
                                            self.stp_app.send_msg(target_addr, f'relay_data.joined {joined_room_id}')
                                else:
                                    logging.error(f'[{self.name}] 加入中继房间失败')
                            else:
                                logging.warning(f'[{self.name}] RelayApp未安装')
                        else:
                            logging.error(f'[{self.name}] relay_data.room 命令格式错误，需要: relay_data.room <server_ip> <server_port> <room_id>')
                    else:
                        logging.error(f'[{self.name}] 未知指令: {msg_dict["msg"]}')
            except queue.Empty:
                continue

    def _reset(self):
        if self.stp_app:
            self.stp_app.unsubscribe_msg(self.name)
