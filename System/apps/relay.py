"""
中继应用：负责通过公网服务器中转任意类型的数据包
支持视频流、文件等数据的中转
"""
import json
import logging
import socket
import threading
import queue
import time
import random
import string
from System.core.base_app import BaseApp


class RelayApp(BaseApp):
    """中继应用：内置客户端和服务器功能"""
    
    def __init__(self, system, server_mode=False, server_port=5004, server_host='0.0.0.0'):
        super().__init__(system, "RelayApp", "1.0")
        self.server_mode = server_mode  # 是否运行服务器模式
        self.server_port = server_port
        self.server_host = server_host
        
        # 服务器相关
        self.server_socket = None
        self.server_thread = None
        self.rooms = {}  # room_id -> {'connections': [conn1, conn2], 'created_at': timestamp}
        self.room_lock = threading.Lock()
        
        # 客户端相关
        self.client_connections = {}  # room_id -> connection
        self.client_receive_queue = queue.Queue()  # 接收到的数据队列
        self.client_receive_callbacks = {}  # room_id -> [回调函数列表]
        self.client_error_callbacks = {}  # room_id -> [回调函数列表]
        self.client_receive_threads = {}  # room_id -> 接收线程对象
        self.client_thread_running = {}  # room_id -> 线程运行状态
        
        # 连接管理
        self.connections = []  # 所有活跃连接
        self.running = False
        
        logging.info(f"[{self.name}] 初始化完成，服务器模式: {server_mode}")

    def _main(self):
        """应用主循环"""
        self.running = True
        
        # 如果处于服务器模式，启动服务器
        if self.server_mode:
            self._start_server()
        
        # 主循环，处理客户端接收队列
        while self.running:
            try:
                # 处理接收到的数据
                if not self.client_receive_queue.empty():
                    data = self.client_receive_queue.get_nowait()
                    self._handle_received_data(data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                logging.error(f"[{self.name}] 主循环错误: {e}")
                time.sleep(1)
    
    def _start_server(self):
        """启动中继服务器"""
        def server_thread():
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind((self.server_host, self.server_port))
                self.server_socket.listen(10)
                self.server_socket.settimeout(5.0)
                logging.info(f"[{self.name}] 中继服务器监听 {self.server_host}:{self.server_port}")
                
                while self.running:
                    try:
                        client_socket, client_address = self.server_socket.accept()
                        logging.info(f"[{self.name}] 新连接来自 {client_address}")
                        client_socket.settimeout(5.0)
                        
                        # 为新连接创建处理线程
                        thread = threading.Thread(
                            target=self._handle_client_connection,
                            args=(client_socket, client_address)
                        )
                        thread.daemon = True
                        thread.start()
                        
                        self.connections.append((client_socket, thread))
                        
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.running:
                            logging.error(f"[{self.name}] 接受连接错误: {e}")
                        
            except Exception as e:
                logging.error(f"[{self.name}] 服务器运行错误: {e}")
            finally:
                if self.server_socket:
                    self.server_socket.close()
                logging.info(f"[{self.name}] 服务器已停止")
        
        self.server_thread = threading.Thread(target=server_thread)
        self.server_thread.daemon = True
        self.server_thread.start()
    
    def _handle_client_connection(self, client_socket, client_address):
        """处理客户端连接"""
        try:
            # 接收初始消息以确定动作
            init_data = self._receive_json(client_socket)
            if not init_data:
                logging.warning(f"[{self.name}] 从 {client_address} 接收初始消息失败")
                client_socket.close()
                return
            
            action = init_data.get('action')
            room_id = init_data.get('room_id')
            
            if action == 'create_room':
                # 创建新房间
                room_id = self._generate_room_id()
                with self.room_lock:
                    self.rooms[room_id] = {
                        'connections': [client_socket],
                        'created_at': time.time(),
                        'addresses': [client_address]
                    }
                logging.info(f"[{self.name}] 为 {client_address} 创建房间 {room_id}")
                
                # 发送房间ID给客户端
                response = {'action': 'room_created', 'room_id': room_id}
                self._send_json(client_socket, response)
                
                # 等待第二个连接加入
                self._wait_for_peer(room_id, client_socket, client_address)
                
            elif action == 'join_room':
                # 加入现有房间
                if not room_id:
                    logging.warning(f"[{self.name}] {client_address} 尝试加入房间但未提供房间ID")
                    client_socket.close()
                    return
                
                with self.room_lock:
                    if room_id not in self.rooms:
                        response = {'action': 'error', 'message': '房间不存在'}
                        self._send_json(client_socket, response)
                        client_socket.close()
                        return
                    
                    room = self.rooms[room_id]
                    if len(room['connections']) >= 2:
                        response = {'action': 'error', 'message': '房间已满'}
                        self._send_json(client_socket, response)
                        client_socket.close()
                        return
                    
                    # 添加第二个连接
                    room['connections'].append(client_socket)
                    room['addresses'].append(client_address)
                
                logging.info(f"[{self.name}] {client_address} 加入房间 {room_id}")
                
                # 通知两个客户端可以开始通信
                response = {'action': 'peer_joined', 'room_id': room_id}
                self._send_json(client_socket, response)
                
                # 获取第一个连接的socket
                with self.room_lock:
                    peer_socket = self.rooms[room_id]['connections'][0]
                
                # 通知第一个客户端有对等端加入
                peer_response = {'action': 'peer_joined', 'room_id': room_id}
                self._send_json(peer_socket, peer_response)
                
                # 开始转发数据
                self._start_forwarding(room_id)
                
            else:
                logging.warning(f"[{self.name}] 未知动作: {action} from {client_address}")
                client_socket.close()
                
        except Exception as e:
            logging.error(f"[{self.name}] 处理客户端 {client_address} 时出错: {e}")
            client_socket.close()
    
    def _wait_for_peer(self, room_id, client_socket, client_address):
        """等待对等端加入房间"""
        timeout = 60  # 60秒超时
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.room_lock:
                room = self.rooms.get(room_id)
                if room and len(room['connections']) == 2:
                    # 对等端已加入
                    return
            
            # 检查连接是否仍然活跃
            try:
                client_socket.send(b'')
            except:
                logging.info(f"[{self.name}] 房间 {room_id} 创建者断开连接")
                with self.room_lock:
                    if room_id in self.rooms:
                        del self.rooms[room_id]
                return
            
            time.sleep(1)
        
        # 超时，清理房间
        logging.info(f"[{self.name}] 房间 {room_id} 等待对等端超时")
        with self.room_lock:
            if room_id in self.rooms:
                del self.rooms[room_id]
        
        # 通知客户端超时
        try:
            response = {'action': 'timeout', 'message': '等待对等端超时'}
            self._send_json(client_socket, response)
        except:
            pass
    
    def _start_forwarding(self, room_id):
        """开始转发房间内两个连接之间的数据"""
        def forward_data(source_socket, target_socket, source_addr, target_addr):
            try:
                # 设置超时时间
                source_socket.settimeout(60)  # 60秒超时
                target_socket.settimeout(60)  # 60秒超时
                
                while True:
                    try:
                        data = source_socket.recv(4096)
                        if not data:
                            logging.info(f"[{self.name}] 连接 {source_addr} 断开")
                            break
                        
                        # 发送数据，处理发送超时
                        total_sent = 0
                        data_len = len(data)
                        while total_sent < data_len:
                            try:
                                sent = target_socket.send(data[total_sent:])
                                if sent == 0:
                                    logging.warning(f"[{self.name}] 发送到 {target_addr} 失败")
                                    break
                                total_sent += sent
                            except socket.timeout:
                                logging.warning(f"[{self.name}] 发送到 {target_addr} 超时")
                                break
                        
                        if total_sent < data_len:
                            break
                            
                    except socket.timeout:
                        continue
                    except ConnectionResetError:
                        logging.info(f"[{self.name}] 连接 {source_addr} 被重置")
                        break
                    except BrokenPipeError:
                        logging.info(f"[{self.name}] 连接 {target_addr} 管道破裂")
                        break
                    except Exception as e:
                        logging.debug(f"[{self.name}] 从 {source_addr} 到 {target_addr} 转发数据错误: {e}")
                        break
            except Exception as e:
                logging.debug(f"[{self.name}] 从 {source_addr} 到 {target_addr} 转发数据结束: {e}")
            finally:
                try:
                    source_socket.close()
                except:
                    pass
                try:
                    target_socket.close()
                except:
                    pass
        
        with self.room_lock:
            room = self.rooms.get(room_id)
            if not room or len(room['connections']) != 2:
                return
            
            conn1, conn2 = room['connections']
            addr1, addr2 = room['addresses']
            
            # 创建两个转发线程
            thread1 = threading.Thread(
                target=forward_data,
                args=(conn1, conn2, addr1, addr2)
            )
            thread2 = threading.Thread(
                target=forward_data,
                args=(conn2, conn1, addr2, addr1)
            )
            
            thread1.daemon = True
            thread2.daemon = True
            thread1.start()
            thread2.start()
            
            logging.info(f"[{self.name}] 房间 {room_id} 开始转发数据")
            
            # 更新房间信息
            room['forwarding_threads'] = [thread1, thread2]
    
    def connect_to_server(self, server_ip, server_port, action='create_room', room_id=None):
        """连接到中继服务器
        
        Args:
            server_ip: 服务器IP地址
            server_port: 服务器端口
            action: 'create_room' 或 'join_room'
            room_id: 加入房间时需要提供的房间ID
        """
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5.0)
            client_socket.connect((server_ip, server_port))
            
            # 发送初始消息
            init_data = {'action': action}
            if room_id:
                init_data['room_id'] = room_id
            self._send_json(client_socket, init_data)
            # 接收服务器响应
            response = self._receive_json(client_socket)
            if not response:
                logging.error(f"[{self.name}] 连接服务器 {server_ip}:{server_port} 无响应")
                client_socket.close()
                return None
            
            if response.get('action') in ['room_created', 'peer_joined']:
                room_id = response.get('room_id')
                logging.info(f"[{self.name}] 成功连接服务器，房间ID: {room_id}")
                
                # 保存连接
                self.client_connections[room_id] = client_socket
                
                # 启动接收线程
                thread = threading.Thread(
                    target=self._client_receive_thread,
                    args=(client_socket, room_id)
                )
                thread.daemon = True
                thread.start()
                
                # 记录线程对象和运行状态
                self.client_receive_threads[room_id] = thread
                self.client_thread_running[room_id] = True
                
                return room_id
            else:
                logging.error(f"[{self.name}] 连接服务器失败: {response}")
                client_socket.close()
                return None
                
        except Exception as e:
            logging.error(f"[{self.name}] 连接服务器 {server_ip}:{server_port} 失败: {e}")
            return None
    
    def _client_receive_thread(self, client_socket, room_id):
        """客户端接收数据线程"""
        try:
            while self.running and self.client_thread_running.get(room_id, True):
                error_msg = ''
                try:
                    # 接收数据长度（4字节）
                    length_bytes = client_socket.recv(4)
                    if len(length_bytes) == 0:
                        error_msg = "连接断开（长度为0）"
                        logging.info(f"[{self.name}] {error_msg}")
                        # 调用错误回调
                        # 调用房间特定的回调函数
                        if room_id in self.client_error_callbacks:
                            for callback in self.client_error_callbacks[room_id]:
                                try:
                                    callback(room_id, error_msg)
                                except Exception as e:
                                    logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                        # 调用全局回调函数
                        if None in self.client_error_callbacks:
                            for callback in self.client_error_callbacks[None]:
                                try:
                                    callback(room_id, error_msg)
                                except Exception as e:
                                    logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                        break  # 退出循环
                    if len(length_bytes) != 4:
                        error_msg = f"连接断开（接收长度数据失败，长度: {len(length_bytes)}）"
                        logging.warning(f"[{self.name}] {error_msg}")
                        break  # 退出循环
                    
                    data_length = int.from_bytes(length_bytes, 'big')
                    
                    # 数据长度合理性检查
                    if data_length <= 0 or data_length > 10 * 1024 * 1024:  # 最大10MB
                        logging.warning(f"[{self.name}] 数据长度异常: {data_length}")
                        continue  # 跳过异常数据
                    
                    # 接收数据
                    data = b''
                    start_time = time.time()
                    timeout = 30  # 30秒超时
                    
                    while len(data) < data_length:
                        if time.time() - start_time > timeout:
                            logging.warning(f"[{self.name}] 接收数据超时")
                            break
                        
                        chunk = client_socket.recv(min(4096, data_length - len(data)))
                        if not chunk:
                            error_msg = "连接断开（接收数据块时）"
                            logging.warning(f"[{self.name}] {error_msg}")
                            # 调用错误回调
                            # 调用房间特定的回调函数
                            if room_id in self.client_error_callbacks:
                                for callback in self.client_error_callbacks[room_id]:
                                    try:
                                        callback(room_id, error_msg)
                                    except Exception as e:
                                        logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                            # 调用全局回调函数
                            if None in self.client_error_callbacks:
                                for callback in self.client_error_callbacks[None]:
                                    try:
                                        callback(room_id, error_msg)
                                    except Exception as e:
                                        logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                            break
                        data += chunk
                    
                    if len(data) != data_length:
                        logging.warning(f"[{self.name}] 数据接收不完整: {len(data)}/{data_length}")
                        continue  # 跳过不完整数据
                    
                    # 将数据放入接收队列
                    self.client_receive_queue.put({
                        'room_id': room_id,
                        'data': data,
                        'timestamp': time.time()
                    })
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    error_msg = f"接收数据错误: {e}"
                    logging.debug(f"[{self.name}] {error_msg}")
                    break
        except Exception as e:
            error_msg = f"客户端接收线程错误: {e}"
            logging.debug(f"[{self.name}] {error_msg}")
        finally:
            if error_msg != '':
                # 调用错误回调
                # 调用房间特定的回调函数
                if room_id in self.client_error_callbacks:
                    for callback in self.client_error_callbacks[room_id]:
                        try:
                            callback(room_id, error_msg)
                        except Exception as e:
                            logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                # 调用全局回调函数
                if None in self.client_error_callbacks:
                    for callback in self.client_error_callbacks[None]:
                        try:
                            callback(room_id, error_msg)
                        except Exception as e:
                            logging.error(f"[{self.name}] 错误回调执行错误: {e}")
                            print(callback)
                            raise e
            client_socket.close()
            if room_id in self.client_connections:
                del self.client_connections[room_id]
    
    def send_data(self, room_id, data):
        """发送数据到对等端
        
        Args:
            room_id: 房间ID
            data: 要发送的数据（bytes）
        """
        if room_id not in self.client_connections:
            logging.error(f"[{self.name}] 房间 {room_id} 不存在或已关闭")
            return False
        
        try:
            client_socket = self.client_connections[room_id]
            
            # 发送数据长度（4字节）
            length_bytes = len(data).to_bytes(4, 'big')
            client_socket.sendall(length_bytes)
            
            # 发送数据
            client_socket.sendall(data)
            return True
        except Exception as e:
            logging.error(f"[{self.name}] 发送数据到房间 {room_id} 失败: {e}")
            
            # 清理连接
            if room_id in self.client_connections:
                del self.client_connections[room_id]
            return False
    
    def register_receive_callback(self, callback, room_id=None):
        """注册数据接收回调函数
        
        Args:
            callback: 回调函数，接收参数 (room_id, data, timestamp)
            room_id: 房间ID，如果为None则注册为全局回调
        """
        if room_id not in self.client_receive_callbacks:
            self.client_receive_callbacks[room_id] = []
        
        # 检查回调函数是否已经注册
        if callback not in self.client_receive_callbacks[room_id]:
            self.client_receive_callbacks[room_id].append(callback)
    
    def register_error_callback(self, callback, room_id=None):
        """注册错误回调函数
        
        Args:
            callback: 回调函数，接收参数 (room_id, error_message)
            room_id: 房间ID，如果为None则注册为全局回调
        """
        if room_id not in self.client_error_callbacks:
            self.client_error_callbacks[room_id] = []
        
        # 检查回调函数是否已经注册
        if callback not in self.client_error_callbacks[room_id]:
            self.client_error_callbacks[room_id].append(callback)
    
    def _handle_received_data(self, data_item):
        """处理接收到的数据"""
        room_id = data_item['room_id']
        
        # 调用房间特定的回调函数
        if room_id in self.client_receive_callbacks:
            for callback in self.client_receive_callbacks[room_id]:
                try:
                    callback(room_id, data_item['data'], data_item['timestamp'])
                except Exception as e:
                    logging.error(f"[{self.name}] 回调函数执行错误: {e}")
        
        # 调用全局回调函数
        if None in self.client_receive_callbacks:
            for callback in self.client_receive_callbacks[None]:
                try:
                    callback(room_id, data_item['data'], data_item['timestamp'])
                except Exception as e:
                    logging.error(f"[{self.name}] 回调函数执行错误: {e}")
    
    def _generate_room_id(self):
        """生成唯一的房间ID"""
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(8))
    
    def _send_json(self, sock, data):
        """发送JSON数据"""
        try:
            json_str = json.dumps(data)
            json_bytes = json_str.encode('utf-8')
            length_bytes = len(json_bytes).to_bytes(4, 'big')
            sock.send(length_bytes)
            sock.send(json_bytes)
        except Exception as e:
            logging.error(f"[{self.name}] 发送JSON数据失败: {e}")
            raise
    
    def _receive_json(self, sock, timeout=5):
        """接收JSON数据"""
        try:
            sock.settimeout(timeout)
            length_bytes = sock.recv(4)
            if len(length_bytes) == 0:
                logging.info(f"[{self.name}] 连接断开（长度为0）")
                return None
            if len(length_bytes) != 4:
                return None
            
            data_length = int.from_bytes(length_bytes, 'big')
            json_bytes = b''
            while len(json_bytes) < data_length:
                chunk = sock.recv(min(4096, data_length - len(json_bytes)))
                if not chunk:
                    return None
                json_bytes += chunk
            
            json_str = json_bytes.decode('utf-8')
            return json.loads(json_str)
        except socket.timeout:
            logging.warning(f"[{self.name}] 接收JSON数据超时")
            return None
        except Exception as e:
            logging.error(f"[{self.name}] 接收JSON数据失败: {e}")
            return None
    
    def get_room_info(self, room_id):
        """获取房间信息
        
        Args:
            room_id: 房间ID
            
        Returns:
            房间信息字典，如果房间不存在则返回None
        """
        if self.server_mode:
            # 服务器模式：返回服务器上的房间信息
            with self.room_lock:
                room = self.rooms.get(room_id)
                if room:
                    return {
                        'room_id': room_id,
                        'connections_count': len(room['connections']),
                        'created_at': room['created_at'],
                        'addresses': room['addresses']
                    }
                return None
        else:
            # 客户端模式：返回客户端连接的房间信息
            if room_id in self.client_connections:
                return {
                    'room_id': room_id,
                    'status': 'connected',
                    'connection': str(self.client_connections[room_id])
                }
            return None
    
    def list_rooms(self):
        """列出所有房间
        
        Returns:
            房间ID列表
        """
        if self.server_mode:
            # 服务器模式：返回服务器上的所有房间
            with self.room_lock:
                return list(self.rooms.keys())
        else:
            # 客户端模式：返回客户端连接的所有房间
            return list(self.client_connections.keys())
    
    def stop_client_thread(self, room_id):
        """停止特定房间的接收线程
        
        Args:
            room_id: 房间ID
        """
        # 设置线程运行状态为False
        if room_id in self.client_thread_running:
            self.client_thread_running[room_id] = False
        
        # 检查当前线程是否是要停止的线程，如果不是，则等待线程结束
        if room_id in self.client_receive_threads:
            thread = self.client_receive_threads[room_id]
            if thread != threading.current_thread() and thread.is_alive():
                try:
                    thread.join(timeout=2.0)
                except Exception as e:
                    logging.debug(f"[{self.name}] 等待线程结束时出错: {e}")
        
        # 清理资源
        if room_id in self.client_connections:
            try:
                self.client_connections[room_id].close()
            except:
                pass
            del self.client_connections[room_id]
        
        if room_id in self.client_receive_threads:
            del self.client_receive_threads[room_id]
        
        if room_id in self.client_thread_running:
            del self.client_thread_running[room_id]
        
        # 清理回调函数
        if room_id in self.client_receive_callbacks:
            del self.client_receive_callbacks[room_id]
        
        if room_id in self.client_error_callbacks:
            del self.client_error_callbacks[room_id]
        
        logging.info(f"[{self.name}] 已停止房间 {room_id} 的接收线程")
    
    def _reset(self):
        """清理资源"""
        self.running = False
        
        # 关闭所有连接
        for conn, _ in self.connections:
            try:
                conn.close()
            except:
                pass
        
        for room_id, conn in list(self.client_connections.items()):
            try:
                conn.close()
            except:
                pass
        
        self.connections.clear()
        self.client_connections.clear()
        self.rooms.clear()
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        logging.info(f"[{self.name}] 资源已清理")