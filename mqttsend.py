import socket
import threading
import time


def connTCP():
    global tcp_client_socket
    # 创建socket
    tcp_client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # IP 和端口
    server_ip = 'bemfa.com'
    server_port = 8344
    try:
        # 连接服务器
        tcp_client_socket.connect((server_ip, server_port))
        # 发送订阅指令
        substr = 'cmd=1&uid=865c32af7d4c73322601d512f8b45b14&topic=test1\r\n'
        tcp_client_socket.send(substr.encode("utf-8"))
    except:
        time.sleep(2)
        connTCP()


def Ping():
    # 发送心跳
    try:
        keeplive = 'ping\r\n'
        tcp_client_socket.send(keeplive.encode("utf-8"))
    except:
        time.sleep(2)
        connTCP()
    # 开启定时，30秒发送一次心跳
    t = threading.Timer(30, Ping)
    t.start()


def Send():
    data = {
        "user": "test1",
        "time": time.time(),
        "msg": "shutdown"
    }
    try:
        keeplive = 'cmd=2&uid=865c32af7d4c73322601d512f8b45b14&topic=test1/set&msg=' + str(data)
        tcp_client_socket.send(keeplive.encode("utf-8"))
    except:
        time.sleep(2)
        connTCP()
    t = threading.Timer(5, Send)
    t.start()


def input_thread():
    while True:
        user_input = input("请输入消息内容: ")
        data = {
            "user": "test1",
            "time": time.time(),
            "msg": user_input,
            "target": "all"
        }
        try:
            msg = 'cmd=2&uid=865c32af7d4c73322601d512f8b45b14&topic=test1/set&msg=' + str(data)
            tcp_client_socket.send(msg.encode("utf-8"))
        except Exception as e:
            print(f"发送失败: {e}")
            time.sleep(2)
            connTCP()


if __name__ == "__main__":
    connTCP()
    Ping()
    # Send()

    # 启动一个新的线程来处理用户输入
    input_thread = threading.Thread(target=input_thread)
    input_thread.daemon = True
    input_thread.start()

    # 主线程保持运行
    while True:
        time.sleep(1)
