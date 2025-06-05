import socket
import threading
import time
import json
import torch
import cv2
from PIL import Image
import os
# 导入
from torchvision import transforms


class TcpClient:
    def __init__(self, model_path=None):
        self.tcp_client_socket = None
        self.lock = threading.Lock()
        self.running = True
        self.model = None

        # 加载 YOLOv5 分类模型（兼容 v5.x 旧版本）
        self.load_model(model_path)

        # 巴法云配置
        self.server_ip = "bemfa.com"  # 巴法云服务器地址
        self.server_port = 8344  # 巴法云 TCP 端口
        self.uid = "865c32af7d4c73322601d512f8b45b14"  # 巴法云 UID
        self.topic = "test1"  # w的巴法云主题
        print("执行连接测试...")
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.connect((self.server_ip, self.server_port))
            test_socket.send(f"cmd=1&uid={self.uid}&topic={self.topic}\r\n".encode("utf-8"))
            response = test_socket.recv(1024)
            print(f"连接测试响应: {response.decode('utf-8')}")
            test_socket.close()
        except Exception as e:
            print(f"连接测试失败: {e}")

    def load_model(self, model_path):
        """加载 YOLOv5 分类模型（兼容 v7.x+ 版本）"""
        try:
            if model_path and os.path.exists(model_path):
                self.model = torch.hub.load(
                    "ultralytics/yolov5",
                    "custom",
                    path=model_path,
                    trust_repo=True
                )
                print(f"成功加载自定义分类模型: {model_path}")
            else:
                self.model = torch.hub.load(
                    "ultralytics/yolov5",
                    "yolov5s-cls",  # 分类模型
                    pretrained=True,
                    trust_repo=True
                )
                print("加载预训练分类模型")

            self.model.eval()
            print(f"模型类别: {self.model.names}")
            print(f"输入尺寸: 224x224")

        except Exception as e:
            print(f"模型加载失败: {e}")
            self.running = False

    def detect_image(self, image_path):
        """更新后的分类模型检测逻辑"""
        try:
            # 读取图像并转换为张量
            img = Image.open(image_path).convert('RGB')

            # 预处理图像
            img = img.resize((224, 224))  # 调整尺寸
            img_tensor = transforms.ToTensor()(img).unsqueeze(0)  # 转换为张量并添加批次维度

            # 执行推理
            with torch.no_grad():
                results = self.model(img_tensor)

            # 解析结果
            pred = torch.nn.functional.softmax(results, dim=1)
            cls_idx = pred.argmax().item()
            confidence = pred.max().item()
            class_name = self.model.names[cls_idx]

            return [{
                "class": class_name,
                "confidence": round(confidence, 2),
                "model_type": "classification",
                "input_size": 224
            }]

        except Exception as e:
            print(f"检测失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def connect_server(self):
        """连接巴法云服务器并订阅主题"""
        while self.running:
            try:
                self.tcp_client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tcp_client_socket.settimeout(10)
                self.tcp_client_socket.connect((self.server_ip, self.server_port))

                # 发送订阅指令
                subscribe_cmd = f"cmd=1&uid={self.uid}&topic={self.topic}\r\n"
                self.tcp_client_socket.send(subscribe_cmd.encode("utf-8"))
                print("成功连接到巴法云服务器")
                return True

            except Exception as e:
                print(f"连接失败: {e}，5秒后重试")
                self.close_connection()
                time.sleep(5)
        return False

    def close_connection(self):
        """安全关闭连接"""
        with self.lock:
            if self.tcp_client_socket:
                try:
                    self.tcp_client_socket.shutdown(socket.SHUT_RDWR)
                    self.tcp_client_socket.close()
                except:
                    pass
                self.tcp_client_socket = None

    def send_heartbeat(self):
        """定时发送心跳包（30秒间隔）"""
        while self.running:
            try:
                if self.tcp_client_socket:
                    self.tcp_client_socket.send("ping\r\n".encode("utf-8"))
                time.sleep(30)
            except:
                self.connect_server()

    def send_results(self, results):
        if not results:
            return

        # 构造消息体 - 简化格式
        data = {
            "class": results[0]["class"],
            "confidence": results[0]["confidence"],
            "time": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # 使用巴法云推荐格式
        msg = f"cmd=2&uid={self.uid}&topic={self.topic}&msg={json.dumps(data)}\r\n"
        print(f"准备发送的消息: {msg}")  # 调试输出

        try:
            with self.lock:
                if self.tcp_client_socket:
                    self.tcp_client_socket.send(msg.encode("utf-8"))
                    print(f"已发送分类结果: {data}")

                    # 接收并打印服务器响应
                    response = self.tcp_client_socket.recv(1024)
                    if response:
                        print(f"服务器响应: {response.decode('utf-8')}")
                    else:
                        print("未收到服务器响应")
        except Exception as e:
            print(f"发送失败: {e}，尝试重连")
            self.connect_server()

    def handle_input(self):
        """处理用户输入（图片路径/摄像头/退出）"""
        while self.running:
            user_input = input("请输入图片路径 (或 'camera' 打开摄像头, 'exit' 退出): ").strip()

            if user_input.lower() == "exit":
                self.running = False
                break
            elif user_input.lower() == "camera":
                self.handle_camera()
            else:
                if os.path.exists(user_input):
                    results = self.detect_image(user_input)
                    if results:
                        self.send_results(results)
                else:
                    print(f"错误：文件不存在 {user_input}")

    def handle_camera(self):
        print("打开摄像头... 按 'q' 退出")
        cap = cv2.VideoCapture(0)

        # 创建转换器
        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
        ])

        while self.running:
            ret, frame = cap.read()
            if not ret:
                print("无法获取摄像头画面")
                break

            try:
                # 直接处理帧数据 - 不再使用临时文件
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(frame_rgb)

                # 预处理图像
                img_tensor = transform(img_pil).unsqueeze(0)

                # 执行推理
                with torch.no_grad():
                    results = self.model(img_tensor)

                # 解析结果
                pred = torch.nn.functional.softmax(results, dim=1)
                cls_idx = pred.argmax().item()
                confidence = pred.max().item()
                class_name = self.model.names[cls_idx]

                result_data = [{
                    "class": class_name,
                    "confidence": round(confidence, 2),
                    "model_type": "classification",
                    "input_size": 224
                }]
                self.send_results(result_data)

                # 在画面上显示结果
                cv2.putText(frame, f"{class_name} {confidence:.2f}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            except Exception as e:
                print(f"摄像头检测失败: {e}")

            cv2.imshow("Camera Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break


if __name__ == "__main__":
    MODEL_PATH = r"D:\PPYTHON\PyProjects\SmartJianKong\yolov5_master\our_models\traffic_exp122\weights\best.pt"  # 我的模型路径
    # MODEL_PATH = None  #

    client = TcpClient(model_path=MODEL_PATH)

    if not client.model:
        print("模型加载失败，程序退出")
        exit(1)

    # 启动连接线程
    connect_thread = threading.Thread(target=client.connect_server)
    connect_thread.daemon = True
    connect_thread.start()

    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=client.send_heartbeat)
    heartbeat_thread.daemon = True
    heartbeat_thread.start()

    # 启动用户输入线程
    input_thread = threading.Thread(target=client.handle_input)
    input_thread.daemon = True
    input_thread.start()

    # 主线程保持运行
    try:
        while client.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    finally:
        client.running = False
        client.close_connection()
        print("程序已退出")