import threading
import time
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.websockets import WebSocket, WebSocketDisconnect
import uvicorn
import cv2
import numpy as np
import queue
import uuid
import json

from System.core.base_app import BaseApp


class ClientFastAPI(BaseApp):
    def __init__(self, system):
        super().__init__(system, "ClientFastAPI", "1.0.0")
        self.app = FastAPI()
        self.config_cors()
        self.config_routes()
        self.stp_app = None
        self.camera_app = None
        self.server_thread = None
        self.host = "0.0.0.0"
        self.port = 5002
        # 流管理器，存储多个并发流
        self.streams = {}
        self.streams_lock = threading.RLock()
        # 全局流计数器
        self.stream_counter = 0
        # 消息队列，用于存储从STP应用接收到的消息
        self.msg_queue = queue.Queue(maxsize=1000)
        # WebSocket连接管理器
        self.ws_connections = set()
        self.ws_lock = threading.RLock()
    
    def config_cors(self):
        """配置CORS中间件"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 在生产环境中应该设置具体的域名
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def config_routes(self):
        """配置API路由"""
        @self.app.get("/api/camera/stream")
        async def camera_stream(server_ip: str, server_port: int):
            if not self.camera_app:
                raise HTTPException(status_code=500, detail="Camera app not initialized")
            # 生成唯一的流ID
            stream_id = str(uuid.uuid4())
            # 创建流队列
            frame_queue = queue.Queue(maxsize=10)
            # 创建流控制标志
            stop_event = threading.Event()
            # 启动流接收线程
            stream_thread = threading.Thread(
                target=self._stream_receiver,
                args=(stream_id, server_ip, server_port, frame_queue, stop_event)
            )
            stream_thread.daemon = True
            stream_thread.start()
            # 返回StreamingResponse
            return StreamingResponse(
                self._stream_generator(stream_id, frame_queue, stop_event),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )
        
        @self.app.get("/api/camera/relay_stream")
        async def camera_relay_stream(room_id: str):
            if not self.camera_app:
                raise HTTPException(status_code=500, detail="Camera app not initialized")
            # 生成唯一的流ID
            stream_id = str(uuid.uuid4())
            # 创建流队列
            frame_queue = queue.Queue(maxsize=10)
            # 创建流控制标志
            stop_event = threading.Event()
            # 启动中继流接收线程
            stream_thread = threading.Thread(
                target=self._relay_stream_receiver,
                args=(stream_id, room_id, frame_queue, stop_event)
            )
            stream_thread.daemon = True
            stream_thread.start()
            # 返回StreamingResponse
            return StreamingResponse(
                self._stream_generator(stream_id, frame_queue, stop_event),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )
        
        @self.app.get("/api/camera/capture")
        async def capture_photo():
            if not self.camera_app:
                raise HTTPException(status_code=500, detail="Camera app not initialized")
            try:
                filename = self.camera_app.capture_photo()
                return {"filename": filename}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/stp/send")
        async def send_stp_message(target_addr: str, message: str):
            if not self.stp_app:
                raise HTTPException(status_code=500, detail="STP app not initialized")
            try:
                success = self.stp_app.send_msg(target_addr, message)
                return {"success": success}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/stp/broadcast")
        async def broadcast_stp_message(message: str, target: str = "all"):
            if not self.stp_app:
                raise HTTPException(status_code=500, detail="STP app not initialized")
            try:
                success = self.stp_app.broadcast_msg(message, target)
                return {"success": success}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.websocket("/ws/topology")
        async def websocket_topology(websocket: WebSocket, forward_addr: str = None, forward_mac: str = None):
            await websocket.accept()
            try:
                while True:
                    # 接收前端消息
                    data = await websocket.receive_json()
                    # 检查是否需要刷新拓扑
                    if data.get("refresh"):
                        # 调用get_topology获取新的拓扑数据
                        if self.stp_app:
                            self.stp_app.get_topology(forward_addr=forward_addr, forward_mac=forward_mac)
                            logging.info(f"[ClientFastAPI] Refreshing topology with forward_addr={forward_addr}, forward_mac={forward_mac}")
                    
                    # 发送当前最新的拓扑数据
                    if self.stp_app:
                        topology = self.stp_app.core.topology if hasattr(self.stp_app, 'core') and hasattr(self.stp_app.core, 'topology') else {}
                        if topology:
                            # 获取时间戳最新的拓扑
                            latest_topology_id = max(topology.keys())
                            latest_topology = topology[latest_topology_id]
                            # 发送拓扑数据
                            await websocket.send_json({
                                "topology_id": latest_topology_id,
                                "topology": latest_topology
                            })
            except WebSocketDisconnect:
                logging.info("[ClientFastAPI] WebSocket disconnected")
            except Exception as e:
                logging.error(f"[ClientFastAPI] WebSocket error: {e}")
            finally:
                await websocket.close()
        
        @self.app.websocket("/ws/messages")
        async def websocket_messages(websocket: WebSocket):
            await websocket.accept()
            # 将连接添加到连接集合
            with self.ws_lock:
                self.ws_connections.add(websocket)
            try:
                # 发送欢迎消息
                await websocket.send_json({"type": "welcome", "message": "Connected to STP message stream"})
                # 保持连接
                while True:
                    # 等待前端消息（可选，用于心跳检测）
                    try:
                        await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
                    except asyncio.TimeoutError:
                        # 发送心跳消息
                        await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                logging.info("[ClientFastAPI] Message WebSocket disconnected")
            except Exception as e:
                logging.error(f"[ClientFastAPI] Message WebSocket error: {e}")
            finally:
                # 从连接集合中移除
                with self.ws_lock:
                    if websocket in self.ws_connections:
                        self.ws_connections.remove(websocket)
                await websocket.close()
        
        @self.app.get("/api/system/status")
        async def get_system_status():
            return self.system.get_status()
        
        @self.app.get("/api/stp/connections")
        async def get_stp_connections():
            if not self.stp_app or not hasattr(self.stp_app, 'core') or not hasattr(self.stp_app.core, 'tcp_connections'):
                raise HTTPException(status_code=500, detail="STP core not initialized")
            # 构建连接字典，包含所有tcp_connections的键及其MAC地址
            connections = {}
            for addr, conn_info in self.stp_app.core.tcp_connections.items():
                # 获取MAC地址，如果存在的话
                mac = conn_info.get('mac', 'Unknown')
                connections[addr] = mac
            return connections
        
        @self.app.get("/api/relay/rooms")
        async def get_relay_rooms():
            # 获取RelayApp实例
            relay_app = self.system.get_app("RelayApp")
            
            if not relay_app:
                raise HTTPException(status_code=500, detail="Relay app not initialized")
            
            try:
                # 调用list_rooms方法获取房间列表
                rooms = relay_app.list_rooms()
                return {"rooms": rooms}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
    
    def _stream_receiver(self, stream_id, server_ip, server_port, frame_queue, stop_event):
        """接收网络摄像头的TCP流并将帧放入队列
        
        Args:
            stream_id: 流ID
            server_ip: 服务器IP
            server_port: 服务器端口
            frame_queue: 帧队列
            stop_event: 停止事件
        """
        # 使用系统的CameraApp实例
        if not self.camera_app:
            logging.error("[ClientFastAPI] Camera app not initialized")
            return
        
        stream_key = f"{server_ip}:{server_port}"
        
        try:
            # 启动接收流
            success = self.camera_app.receive_stream(
                server_ip=server_ip,
                server_port=server_port,
                display=False,
                save_to_file=False
            )
            
            if success:
                # 持续将帧放入队列，直到收到停止事件
                while not stop_event.is_set():
                    # 使用get_frame方法获取帧，这会更新活跃状态
                    frame = self.camera_app.get_frame(stream_key)
                    if frame is not None:
                        # 如果队列已满，丢弃旧帧
                        if frame_queue.full():
                            try:
                                frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        try:
                            frame_queue.put(frame, block=False)
                        except queue.Full:
                            pass
                    # 检查停止事件，避免CPU占用过高
                    stop_event.wait(0.01)
        finally:
            # 清理资源
            self.camera_app.stop_receiving_stream(stream_key)
            logging.info(f"[ClientFastAPI] Stream {stream_id} receiver thread stopped")
    
    def _relay_stream_receiver(self, stream_id, room_id, frame_queue, stop_event):
        """接收网络摄像头的中继流并将帧放入队列
        
        Args:
            stream_id: 流ID
            room_id: 中继房间ID
            frame_queue: 帧队列
            stop_event: 停止事件
        """
        # 使用系统的CameraApp实例
        if not self.camera_app:
            logging.error("[ClientFastAPI] Camera app not initialized")
            return
        
        try:
            # 持续将帧放入队列，直到收到停止事件
            while not stop_event.is_set():
                # 使用get_frame方法获取帧，这会更新活跃状态
                frame = self.camera_app.get_frame(room_id)
                if frame is not None:
                    # 如果队列已满，丢弃旧帧
                    if frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    try:
                        frame_queue.put(frame, block=False)
                    except queue.Full:
                        pass
                # 检查停止事件，避免CPU占用过高
                stop_event.wait(0.01)
        finally:
            # 不需要清理资源，因为我们没有主动连接中继服务器
            logging.info(f"[ClientFastAPI] Relay Stream {stream_id} receiver thread stopped")
        
    def _stream_generator(self, stream_id, frame_queue, stop_event):
        """从队列中获取帧并生成MJPEG流
        
        Args:
            stream_id: 流ID
            frame_queue: 帧队列
            stop_event: 停止事件
        
        Yields:
            MJPEG格式的帧数据
        """
        try:
            while not stop_event.is_set():
                try:
                    # 从队列中获取帧
                    frame = frame_queue.get(timeout=1.0)
                    # 将帧转换为JPEG
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                except queue.Empty:
                    # 队列为空，继续循环
                    continue
        finally:
            # 客户端断开连接，设置停止事件
            stop_event.set()
            logging.info(f"[ClientFastAPI] Stream {stream_id} generator stopped, client disconnected")
    
    def _main(self, *args, **kwargs):
        """应用主循环"""
        # 获取STPApp和CameraApp实例
        self.stp_app = self.system.get_app("STPApp")
        self.camera_app = self.system.get_app("CameraApp")
        
        # 订阅STP应用的消息
        if self.stp_app:
            self.stp_app.subscribe_msg("ClientFastAPI", self.msg_queue)
            logging.info("[ClientFastAPI] 已订阅STP应用的消息")
        
        # 启动消息处理线程
        msg_thread = threading.Thread(target=self._process_messages)
        msg_thread.daemon = True
        msg_thread.start()
        
        # 启动FastAPI服务器
        def start_server():
            """在新线程中启动FastAPI服务器"""
            import asyncio
            config = uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
            # 在事件循环中运行协程
            asyncio.run(server.serve())
        
        # 在新线程中运行服务器
        self.server_thread = threading.Thread(target=start_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        logging.info(f"[ClientFastAPI] 服务器已启动，监听 {self.host}:{self.port}")
        
        # 保持应用运行
        while self.running:
            time.sleep(0.1)
    
    def _process_messages(self):
        """处理从STP应用接收到的消息"""
        while self.running:
            try:
                # 从队列中获取消息
                msg = self.msg_queue.get(timeout=1.0)
                # 广播消息给所有WebSocket连接
                self._broadcast_message(msg)
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"[ClientFastAPI] 处理消息时出错: {e}")
    
    def _broadcast_message(self, msg):
        """广播消息给所有WebSocket连接"""
        with self.ws_lock:
            # 转换消息为JSON可序列化格式
            try:
                msg_json = json.dumps(msg)
            except Exception as e:
                logging.error(f"[ClientFastAPI] 消息序列化失败: {e}")
                return
            
            # 广播消息
            for connection in list(self.ws_connections):
                try:
                    # 在非异步线程中使用事件循环发送消息
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(connection.send_json({"message": msg_json}))
                    loop.close()
                except Exception as e:
                    logging.error(f"[ClientFastAPI] 广播消息失败: {e}")
                    # 移除无效的连接
                    if connection in self.ws_connections:
                        self.ws_connections.remove(connection)
    
    def _reset(self):
        """重置应用"""
        self.streaming = False
        if self.server_thread and self.server_thread.is_alive():
            # 注意：uvicorn的服务器线程可能需要特殊处理来停止
            pass
        logging.info(f"[{self.name}] 应用已重置")
    
    def stop(self):
        """停止应用"""
        self.streaming = False
        super().stop()
