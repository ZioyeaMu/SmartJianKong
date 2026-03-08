import threading
import time
import logging
import re
from System.core.base_app import BaseApp
import json
import socket
import random
import hashlib
import string
import ping3
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from ruamel.yaml import YAML

# 日志配置
logger = logging.getLogger(__name__)

# 加载配置
yaml = YAML()
yaml.preserve_quotes = True  # 保留引号
yaml.indent(mapping=2, sequence=4, offset=2)  # 缩进设置

# 配置文件路径
config_file = './System/AppData/STPApp/STP_config.yaml'
# 默认配置文件路径
default_config_file = './System/apps/STP/STP_config.yaml'

try:
    # 尝试从工作目录读取配置文件
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.load(f)
except FileNotFoundError:
    # 如果工作目录中找不到配置文件，尝试从安装目录复制默认配置文件
    import os
    if os.path.exists(default_config_file):
        # 确保工作目录存在
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        # 复制默认配置文件到工作目录
        with open(default_config_file, 'r', encoding='utf-8') as src:
            default_config = yaml.load(src)
        with open(config_file, 'w', encoding='utf-8') as dst:
            yaml.dump(default_config, dst)
        # 使用默认配置
        config = default_config
    else:
        # 如果默认配置文件也找不到，报错
        raise FileNotFoundError(f"配置文件不存在：{config_file} 和 {default_config_file}")

# =====包和协议类型=====
class HeartBeat:
    """心跳协议"""

    def __init__(self):
        pass


class Msg:
    """常规消息"""
    def __init__(self, msg):
        self.msg = msg


class BPDU:
    """BPDU协议：桥协议数据单元"""

    def __init__(self, root_mac, root_distance, age):
        self.root_mac = root_mac
        self.root_distance = root_distance
        self.age = age


class BPDU_Control:
    """BPDU控制包协议：辅助功能，让对方不向自己发送数据包"""

    def __init__(self, block_me=False):
        self.block_me = block_me


class Broadcast:
    """广播包协议：将某条消息广播到全网络"""

    def __init__(self, data):
        self.data = data


class ConnectInit:
    """连接握手协议：辅助断开同一设备的重复连接"""

    def __init__(self, type, port):
        self.type = type  # STP, FORWARD
        self.port = port


class Hash_Verify:
    """哈希校验协议：连接阶段校验双方文件完整性"""

    def __init__(self, challenge=None, value=None):
        self.challenge = challenge
        self.value = value
        if bool(challenge) == bool(value):
            raise ValueError('挑战字符串和响应值必须异或')


class Forward:
    """中继协议：用一台公网设备辅助两个设备通讯"""

    def __init__(self, source_mac, target_mac, data):
        self.source_mac = source_mac
        self.target_mac = target_mac
        self.data = data


class Topology:
    """拓扑包：传输自己的端口状态，辅助构建拓扑图"""

    def __init__(self, source_mac, mac_role, id):
        self.source_mac = source_mac
        self.mac_role = mac_role
        self.id = id


class Connect_Control:
    """连接控制包协议：辅助功能，例：传输完一段数据后让对方关闭与自己的连接"""

    def __init__(self, action, **kwargs):  # action:CLOSE/REDIRECT
        self.action = action
        for key, value in kwargs.items():
            setattr(self, key, value)


class FileTransferInit:
    """文件传输初始化协议"""
    def __init__(self, filename, file_size, chunk_size=4096, file_id=None):
        self.filename = filename
        self.file_size = file_size
        self.chunk_size = chunk_size
        self.file_id = file_id or f"{time.time()}_{random.randint(1000, 9999)}"


class FileTransferControl:
    """文件传输控制协议"""
    def __init__(self, action, **kwargs):  # action: START, PAUSE, RESUME, CANCEL, ACCEPT, REJECT
        self.action = action
        for key, value in kwargs.items():
            setattr(self, key, value)


class FileChunk:
    """文件数据块"""
    def __init__(self, file_id, chunk_id, data, is_last=False, checksum=None):
        self.file_id = file_id
        self.chunk_id = chunk_id
        self.data = data
        self.is_last = is_last
        self.checksum = checksum or hashlib.md5(data).hexdigest()


class FileChunkAck:
    """文件块确认"""
    def __init__(self, file_id, chunk_id, received=True, next_expected=None):
        self.file_id = file_id
        self.chunk_id = chunk_id
        self.received = received
        self.next_expected = next_expected  # 用于流控


# =====广播协议细分=====
class BForward:
    """中继广播协议：让目标设备知道应该通过那个设备中继"""

    def __init__(self, source_addr, forward_addr, target_addr):
        # todo:等待实现
        pass


class BTopology:
    """拓扑广播协议（拓扑发现协议）：让所有设备向指定设备发送拓扑包"""

    def __init__(self, source_mac, id, source_port=False, forward_addr=False, forward_mac=False):
        self.source_mac = source_mac
        self.source_port = source_port
        self.id = id
        self.forward_addr = forward_addr
        self.forward_mac = forward_mac
        if bool(forward_mac) != bool(forward_addr):
            raise ValueError("参数forward_mac与forward_addr不对等")
        if (forward_addr or forward_mac) and source_port:
            raise ValueError("不可作为转发设备同时被转发")


# =====标准数据包=====
class DataPacket:
    """标准数据包"""

    def __init__(self, source_addr, source_mac, data):
        self.source_addr = source_addr
        self.source_mac = source_mac
        self.data = data


# 协议类映射
PROTOCOL_CLASSES = {
    BPDU.__name__: BPDU,
    BPDU_Control.__name__: BPDU_Control,
    Broadcast.__name__: Broadcast,
    ConnectInit.__name__: ConnectInit,
    Forward.__name__: Forward,
    BForward.__name__: BForward,
    BTopology.__name__: BTopology,
    Topology.__name__: Topology,
    DataPacket.__name__: DataPacket,
    Connect_Control.__name__: Connect_Control,
    HeartBeat.__name__: HeartBeat,
    Hash_Verify.__name__: Hash_Verify,
    Msg.__name__: Msg
}


class Port:
    ROOT_PORT = 0  # 根端口
    DESIGNATED_PORT = 1  # 指定端口
    BLOCKING_PORT = 2  # 阻塞端口
    DISABLE_PORT = 3  # 端口禁用


class STPCore:
    def __init__(self, listen_port, real=False, stp_app=None, hash_verification=True):
        self.mac = self.get_mac() if real else self.generate_random_mac()
        self.ip = self.get_default_ip() if real else "127.0.0.1"
        self.listen_port = str(listen_port)
        self.stp_app = stp_app  # STPApp实例，用于消息发布
        self.auto_reconnect_list = {}
        self.tcp_connections = {}  # 保存TCP连接 {target_addr: {'socket':,'stage':,'connect_time':,'connect_type':}}
        self.server_socket = None  # 监听socket
        self.arp = {}  # {mac:addr}
        self.root_mac = self.mac
        self.root_distance = 0
        self.root_port = None
        self.root_port_mac = None
        self.age = 0
        self.direct_connections = []
        self.port_roles = {}
        self.msg_buffer = []
        self.recv_buffers = {}
        self.buffer_lock = threading.Lock()
        self.shutdown_flag = False  # 关闭标志
        self.thread = threading.Thread(target=self.main)
        self.thread.daemon = True  # 设置为守护线程
        self.topology = {}  # 拓扑图储存
        self.delay_time = 0.001  # 系统休眠时间，防止CPU空转消耗资源
        self.scheduled_jobs = {}  # 定时任务列表{定时函数:(间隔, 上次执行时间)}
        self.connection_attempts = {}  # 连接尝试历史 {addr: {'count': int, 'last_attempt': float}}
        self.hash_verification = hash_verification  # 哈希校验开关，默认为True

    def add_scheduled_job(self, interval, job_func):
        """定时执行某任务"""
        if job_func not in self.scheduled_jobs:
            self.scheduled_jobs[job_func] = (interval, time.time())
        else:
            logger.warning(f'[{self.ip}:{self.listen_port}] 无法重复创建定时任务。')

    def remove_scheduled_job(self, job_func):
        """解除定时任务"""
        if job_func in self.scheduled_jobs:
            del self.scheduled_jobs[job_func]
        else:
            logger.error(f'[{self.ip}:{self.listen_port}] 无法取消不存在的定时任务。')

    def scheduled_job(self):
        for job_func, (interval, last_time) in self.scheduled_jobs.items():
            if time.time() - last_time >= interval:
                job_func()
                self.scheduled_jobs[job_func] = (interval, time.time())

    def send_BPDU(self, targets=None, force=False):
        BPDU_pack = BPDU(self.root_mac, self.root_distance, self.age)
        if targets is None:
            for ip, role in list(self.port_roles.items()):
                if role == Port.DESIGNATED_PORT:
                    self.send_msg(ip, BPDU_pack, priority=0)
        else:
            for target in targets:
                if target in self.port_roles:
                    if self.port_roles[target] == Port.DESIGNATED_PORT or force:
                        self.send_msg(target, BPDU_pack, priority=0)
                    else:
                        logger.warning(f"[{self.ip}:{self.listen_port}] 尝试向非指定端口发送BPDU包。行动:忽略。")
                else:
                    logger.warning(f"[{self.ip}:{self.listen_port}] 尝试向不存在的端口发送BPDU包。行动:忽略。")

    def send_Forward(self, target_mac, forward_addr, data):
        self.send_msg(forward_addr, Forward(self.mac, target_mac, data))

    def get_Topology(self, forward_addr=False, forward_mac=False):
        # 新建一个空的拓扑字典，键为当前时间戳
        topology_id = time.time() * 1000
        self.topology[topology_id] = {}
        
        # todo:潜在问题：设备连接自己(forward_addr等于自己)
        if forward_addr and forward_mac:
            if forward_addr not in self.tcp_connections:
                ip, port = forward_addr.split(':')
                self.connect_net(ip, port, connect_type='FORWARD', idle_timeout=config['topology_forward_idle_timeout'])
        if not (bool(forward_mac) or bool(forward_addr)):
            self.broadcast(BTopology(self.mac, topology_id, source_port=self.listen_port))
        else:
            self.broadcast(BTopology(self.mac, topology_id, forward_addr=forward_addr, forward_mac=forward_mac))

    def send_msg(self, target_addr, data, custom=False, sock=None, force=False, priority=config['default_msg_priority']):
        """通过TCP连接发送消息"""

        def Encoder(data):
            # 如果是对象，获取其属性和协议类型
            if hasattr(data, '__dict__'):
                inn_data = {'Protocol': type(data).__name__}
                for k, v in data.__dict__.items():
                    if not k.startswith('_'):  # 跳过私有属性
                        inn_data[k] = Encoder(v)
                return inn_data
            elif isinstance(data, dict):
                # 如果是字典，递归处理值
                return {k: Encoder(v) for k, v in data.items()}
            elif isinstance(data, list):
                # 如果是列表，递归处理每个元素
                return [Encoder(item) for item in data]
            else:
                # 基本类型直接返回
                return data

        try:
            # 检查target_addr是否为MAC地址
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if re.match(mac_pattern, target_addr):
                # 查找MAC地址对应的IP地址
                mac_ip = None
                for mac, ip in self.arp.items():
                    if mac.lower() == target_addr.lower():
                        mac_ip = ip
                        break
                if mac_ip:
                    logger.info(f"[{self.ip}:{self.listen_port}] 将MAC地址 {target_addr} 转换为IP地址 {mac_ip}")
                    target_addr = mac_ip
                else:
                    logger.error(f"[{self.ip}:{self.listen_port}] 未找到MAC地址 {target_addr} 对应的IP地址")
                    return False

            # 检查是否已连接到目标
            if target_addr not in self.tcp_connections and not custom:
                logger.error(f"[{self.ip}:{self.listen_port}] 未连接到 {target_addr}，无法发送消息")
                return False

            # 获取对应的socket连接
            if custom:
                if sock is None:
                    logger.error(
                        f"[{self.ip}:{self.listen_port}] 无法发送消息，自定义参数需要传入socket实例。(这是一个代码bug)")
                    return False
            else:
                sock = self.tcp_connections[target_addr]['socket']

            # 创建数据包
            packet = DataPacket(
                source_addr=None,
                source_mac=self.mac,
                data=Encoder(data)
            )
            # 序列化为JSON字符串
            packet_dict = {
                'source_addr': packet.source_addr,
                'source_mac': packet.source_mac,
                'data': packet.data
            }
            try:
                json_str = json.dumps(packet_dict, ensure_ascii=False)
            except Exception as e:
                logger.error(f"[{self.ip}:{self.listen_port}] JSON序列化失败: {e}")
                return False

            # 添加消息分隔符 \r\n
            message = json_str + '\r\n'
            data_bytes = message.encode('utf-8')
            now_send = False

            if force or custom:
                for attempt in range(config['send_msg_retry_count']):
                    try:
                        sock.sendall(str(priority).encode() + b'\n\r' + data_bytes)
                        break
                    except OSError as e:
                        if attempt >= config['send_msg_retry_count'] - 1:
                            logger.error(f"[{self.ip}:{self.listen_port}] 消息发送失败。行动:丢弃消息。")
                now_send = True
            else:
                self.tcp_connections[target_addr]['send_buffer'][priority] += data_bytes

            if type(data).__name__ != 'HeartBeat':
                # 发送有效消息，标记为活跃
                self.tcp_connections[target_addr]['last_active'] = time.time()

            # 调试信息
            if type(data).__name__ != "BPDU" and type(data).__name__ != 'HeartBeat':
                logger.debug(
                    f"[{self.ip}:{self.listen_port}] 发送 {type(data).__name__} 到 {target_addr if not custom else sock.getpeername()}({'强制' if now_send else '缓存'})")
            return True

        except (socket.error, ConnectionError) as e:
            logger.error(f"[{self.ip}:{self.listen_port}] 发送消息到 {target_addr} 失败: {e}")
            # 连接可能已断开，清理连接
            (target_ip, target_port) = target_addr.split(':')
            self.disconnect_net(target_ip, target_port, result='消息发送失败。')
            return False
        except Exception as e:
            logger.error(f"[{self.ip}:{self.listen_port}] 发送消息时发生错误: {e}")
            return False

    def broadcast(self, msg):
        if isinstance(msg, DataPacket):
            msg: DataPacket
            for ip, role in list(self.port_roles.items()):
                if (role == Port.DESIGNATED_PORT or role == Port.ROOT_PORT) and ip != msg.source_addr:
                    self.send_msg(ip, msg.data, priority=1)
        else:
            for ip, role in list(self.port_roles.items()):
                if role == Port.DESIGNATED_PORT or role == Port.ROOT_PORT:
                    self.send_msg(ip, Broadcast(msg), priority=1)

    def connect_net(self, ip, port, connect_type='STP', max_retries=config['connect_retry_count'], auto_reconnect=False,
                    idle_timeout=config['default_idle_timeout']):
        """连接到指定IP的设备"""
        addr = f"{ip}:{port}"
        
        # 检查连接频率
        current_time = time.time()
        time_window = config['connection_time_window']  # 时间窗口（秒）
        max_attempts = config['connection_max_attempts']  # 最大尝试次数
        
        if addr in self.connection_attempts:
            attempt_info = self.connection_attempts[addr]
            time_since_last = current_time - attempt_info['last_attempt']
            
            # 如果在时间窗口内尝试次数过多，拒绝连接
            if time_since_last < time_window and attempt_info['count'] >= max_attempts:
                logger.warning(f"[{self.ip}:{self.listen_port}] 短时间内连接 {addr} 过于频繁，拒绝连接。")
                return False
            
            # 如果超过时间窗口，重置计数
            elif time_since_last >= time_window:
                attempt_info['count'] = 1
                attempt_info['last_attempt'] = current_time
            
            # 否则增加计数
            else:
                attempt_info['count'] += 1
                attempt_info['last_attempt'] = current_time
        else:
            # 初始化连接尝试记录
            self.connection_attempts[addr] = {
                'count': 1,
                'last_attempt': current_time
            }
        
        for attempt in range(max_retries + 1):
            try:
                if addr in self.tcp_connections:
                    logger.warning(f"[{self.ip}:{self.listen_port}] 尝试重复连接: {ip}:{port}。行动:忽略。")
                    return False
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((ip, int(port)))

                # 设置为非阻塞模式
                sock.setblocking(False)

                # 根据hash_verification参数决定连接的初始stage
                if not self.hash_verification:
                    # 跳过哈希校验，直接进入stage 1
                    self.tcp_connections[f"{ip}:{port}"] = {
                        'socket': sock,
                        'stage': 1,
                        'connect_time': time.time(),
                        'connect_type': connect_type,
                        'send_buffer': [b'', b'', b'', b'', b''],
                        'heartbeat_time': time.time(),
                        'idle_timeout': idle_timeout,
                        'last_active': time.time()
                    }
                    
                    if auto_reconnect:
                        self.auto_reconnect_list[(ip, str(port))] = connect_type
                        logger.info(f"[{self.ip}:{self.listen_port}] 已连接到 {ip}:{port}。自动连接已启用。")
                    else:
                        logger.info(f"[{self.ip}:{self.listen_port}] 已连接到 {ip}:{port}。")
                    
                    # 直接发送ConnectInit消息
                    self.send_msg(f"{ip}:{port}", ConnectInit(connect_type, self.listen_port), force=True)
                else:
                    # 需要哈希校验，进入stage 0
                    self.tcp_connections[f"{ip}:{port}"] = {
                        'socket': sock,
                        'stage': 0,
                        'connect_time': time.time(),
                        'connect_type': connect_type,
                        'send_buffer': [b'', b'', b'', b'', b''],
                        'heartbeat_time': time.time(),
                        'idle_timeout': idle_timeout,
                        'last_active': time.time()
                    }
                    
                    if auto_reconnect:
                        self.auto_reconnect_list[(ip, str(port))] = connect_type
                        logger.info(f"[{self.ip}:{self.listen_port}] 已连接到 {ip}:{port}。自动连接已启用。")
                    else:
                        logger.info(f"[{self.ip}:{self.listen_port}] 已连接到 {ip}:{port}。")

                return True
            except ConnectionRefusedError:
                if attempt < max_retries:
                    delay = 0.5 * (attempt + 1) + round(random.uniform(0, 0.5), 2)
                    logger.warning(
                        f"[{self.ip}:{self.listen_port}] 连接被拒绝，重试 {attempt + 1}/{max_retries} ，退避: {delay} 秒")
                    time.sleep(delay)  # 指数随机退避
                    continue
                else:
                    logger.error(f"[{self.ip}:{self.listen_port}] 连接被拒绝，已达到最大重试次数")
                    return False
            except Exception as e:
                logger.error(f"[{self.ip}:{self.listen_port}] 连接失败 {ip}:{port}。原因: {e}")
                return False

    def disconnect_all(self):
        """断开所有网络连接"""
        addrs_to_disconnect = list(self.tcp_connections.keys())
        for addr in addrs_to_disconnect:
            # 将 "ip:port" 格式的字符串拆分为 ip 和 port
            ip, port = addr.split(':')
            self.disconnect_net(ip, port, result='应用关闭。', cancel_reconnect=True)
        logger.info(f"[{self.ip}:{self.listen_port}] 已断开所有连接")

    def disconnect_net(self, ip, port, result='', level='info', cancel_reconnect=False):
        """断开与指定IP的连接"""
        if f'{ip}:{port}' in self.tcp_connections:
            try:
                # todo: 优化：判断是否主动断开
                if result != '':
                    self.send_msg(f'{ip}:{port}', Msg(result), force=True)
                # 关闭对应的TCP连接
                sock = self.tcp_connections[f"{ip}:{port}"]['socket']
                sock.close()
                del self.tcp_connections[f"{ip}:{port}"]
                if sock in self.recv_buffers:
                    del self.recv_buffers[sock]
                if f"{ip}:{port}" in self.port_roles:
                    del self.port_roles[f"{ip}:{port}"]
                # 清理ARP表
                mac_to_remove = None
                for mac, addr in self.arp.items():
                    if addr == f"{ip}:{port}":
                        mac_to_remove = mac
                        break
                if mac_to_remove:
                    del self.arp[mac_to_remove]

                log_method = getattr(logger, level, logger.info)
                if cancel_reconnect:
                    if (ip, str(port)) in self.auto_reconnect_list:
                        del self.auto_reconnect_list[(ip, str(port))]
                        log_method(
                            f"[{self.ip}:{self.listen_port}] 已断开与 {ip}:{port} 的连接。原因: {result} 。并已取消自动重连。")
                    else:
                        log_method(
                            f"[{self.ip}:{self.listen_port}] 已断开与 {ip}:{port} 的连接。原因: {result} 。但因找不到，无法取消自动重连。")
                else:
                    if (ip, str(port)) in self.auto_reconnect_list:
                        log_method(
                            f"[{self.ip}:{self.listen_port}] 已断开与 {ip}:{port} 的连接。原因: {result} 。系统正在重新连接。")
                        if not self.connect_net(ip, port, connect_type=self.auto_reconnect_list[(ip, str(port))],
                                                auto_reconnect=True):
                            logger.error(f"[{self.ip}:{self.listen_port}] 自动连接失败，系统稍后会再次尝试重新连接。")
                    else:
                        log_method(f"[{self.ip}:{self.listen_port}] 已断开与 {ip}:{port} 的连接。原因: {result} 。")
                return True
            except Exception as e:
                logger.error(f"[{self.ip}:{self.listen_port}] 关闭连接时出错: {e}")
        else:
            logger.warning(f"[{self.ip}:{self.listen_port}] 未连接到 {ip}，无法断开")
            return False

    def auto_reconnect(self, ip, port, connect_type='STP'):
        self.auto_reconnect_list[(ip, str(port))] = connect_type
        logger.info(f'[{self.ip}:{self.listen_port}] 已为 {ip}:{port} 配置类型为 {connect_type} 的自动重连。')

    def cancel_reconnect(self, ip, port):
        if (ip, str(port)) in self.auto_reconnect_list:
            del self.auto_reconnect_list[(ip, str(port))]
            logger.info(f'[{self.ip}:{self.listen_port}] 已关闭 {ip}:{port} 的自动重连。')
        else:
            logger.warning(f'[{self.ip}:{self.listen_port}] 找不到 {ip}:{port} 的自动重连。')

    def setRoot_port(self, addr):
        if addr not in self.tcp_connections:
            raise ValueError('网络连接不存在此IP！')
        self.port_roles[addr] = Port.ROOT_PORT

    def des_port(self, addr):
        if addr not in self.tcp_connections:
            raise ValueError('网络连接不存在此IP！')
        self.port_roles[addr] = Port.DESIGNATED_PORT

    def block_port(self, addr):
        if addr not in self.tcp_connections:
            raise ValueError('网络连接不存在此IP！')
        if self.port_roles[addr] == Port.ROOT_PORT:
            logger.warning(f"[{self.ip}:{self.listen_port}] 尝试阻塞根端口 {addr}。行动:忽略。")
            return  # ❌ 绝不阻塞根端口
        else:
            self.port_roles[addr] = Port.BLOCKING_PORT

    def resetRootBridge(self):
        self.root_mac = self.mac
        self.root_distance = 0
        self.root_port = None
        self.msg_buffer.clear()
        # todo:是否需要重置port_roles？
        for addr in self.tcp_connections.keys():
            self.port_roles[addr] = Port.DESIGNATED_PORT

    def start_listening(self, max_retries=3):
        """启动TCP服务器，支持端口重试和资源清理"""
        for attempt in range(max_retries):
            try:
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                self.server_socket.bind(('0.0.0.0', int(self.listen_port)))
                self.server_socket.listen(5)
                self.server_socket.setblocking(False)

                logger.info(f"[{self.ip}:{self.listen_port}] 监听端口: {self.listen_port}")
                return True

            except socket.error as e:
                # 清理当前失败的socket
                if self.server_socket:
                    try:
                        self.server_socket.close()
                    except:
                        pass
                    self.server_socket = None

                global create_port
                self.listen_port += 1
                create_port += 1
                logger.warning(f"端口监听失败，尝试端口 {self.listen_port}")
                continue

            except Exception as e:
                # 清理资源
                if self.server_socket:
                    try:
                        self.server_socket.close()
                    except:
                        pass
                    self.server_socket = None

                logger.critical(f"[{self.ip}:{self.listen_port}] 监听失败: {e}")
                return False

        # 所有重试都失败
        logger.critical(f"[{self.ip}] 监听最终失败，尝试了 {max_retries} 次")
        return False

    def start(self):
        """启动设备线程"""
        if not self.thread.is_alive():
            self.thread.start()
        else:
            logger.warning(f"[{self.ip}:{self.listen_port}] 设备已启动过。")

    def shutdown(self):
        """关闭设备（进程退出）"""
        logger.info(f"[{self.ip}:{self.listen_port}] 正在关闭设备 ...")
        self.shutdown_flag = True

        # 断开所有连接
        self.disconnect_all()

        # 等待线程结束
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            if self.thread.is_alive():
                logger.warning(f"[{self.ip}:{self.listen_port}] 设备线程未能正常结束!")

        # todo:考虑：在真实的网络环境中，是否还需要设备列表？
        # 从网络和设备列表中移除
        try:
            # 从设备列表中移除
            global devices
            if self in devices:
                devices.remove(self)

        except Exception as e:
            logger.error(f"[{self.ip}:{self.listen_port}] 移除设备时出错: {e}")

        logger.info(f"[{self.ip}:{self.listen_port}] 设备 已关闭")

    def generate_random_mac(self):
        """
        生成随机的MAC地址 (XX:XX:XX:XX:XX:XX 格式)
        :return:
            str: 随机MAC地址字符串
        """
        # 生成6个随机的十六进制字节
        mac_bytes = [random.randint(0x00, 0xFF) for _ in range(6)]

        # 格式化为标准的MAC地址格式
        mac = ':'.join(f'{byte:02x}' for byte in mac_bytes)

        return mac

    def get_mac(self):
        """
        获取系统第一个真实MAC地址

        :return:
            str: 真实MAC地址字符串
        """
        import uuid
        return ":".join([f"{(uuid.getnode() >> (8 * i)) & 0xff:02x}" for i in range(5, -1, -1)])

    def generate_random_ip(self):
        """
        生成随机的IPv4地址

        :return:
            str: 随机IP地址字符串
        """
        # 生成4个0-255之间的随机数
        ip_parts = [str(random.randint(0, 255)) for _ in range(4)]

        # 用点连接
        ip = '.'.join(ip_parts)

        return ip

    def get_default_ip(self):
        """
        返回本机对外连接的源 IP

        :return:
            str: 本机IP字符串
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 8.8.8.8 只是用来让内核选路由，不会真正发数据
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]

    def get_available_ip(self):
        """
        获取本机所有可用IP

        :return:
            dict: 所有网卡IP字典
        """
        import psutil

        def get_net_info():
            info = {}
            for iface, addrs in psutil.net_if_addrs().items():
                mac = ipv4 = None
                for snic in addrs:
                    if snic.family == psutil.AF_LINK:  # MAC
                        mac = snic.address
                    elif snic.family == socket.AF_INET:  # IPv4
                        ipv4 = snic.address
                if mac or ipv4:  # 至少有一个才记录
                    info[iface] = {'mac': mac, 'ipv4': ipv4}
            return info

        net_info = get_net_info()

        # 修复：使用一个条件同时检查是否为None和是否以特定前缀开头
        def is_valid_ip(ip_info):
            ip = ip_info.get('ipv4')
            return ip is not None and not ip.startswith('169.254') and not ip.startswith('127.0.0.1')

        net_info = {name: d for name, d in net_info.items() if is_valid_ip(d)}

        return net_info

    def mac_to_int(self, mac_str):
        """将MAC地址字符串转换为整数"""
        # 移除冒号，然后作为16进制数转换为整数
        return int(mac_str.replace(':', ''), 16)

    def process_network_io(self):
        # 接受新的TCP连接
        if self.server_socket:
            try:
                client_socket, client_address = self.server_socket.accept()
                client_socket.setblocking(False)

                addr_str = f"{client_address[0]}:{client_address[1]}"

                # 根据hash_verification参数决定是否进行哈希校验
                if self.hash_verification:
                    challenge_str = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
                    hash_value = self.hash_file(__file__, challenge_str)

                    # 将新连接加入待处理列表
                    self.tcp_connections[addr_str] = {
                        'socket': client_socket,
                        'stage': 0,
                        'connect_time': time.time(),
                        'connect_type': None,
                        'send_buffer': [b'', b'', b'', b'', b''],
                        'heartbeat_time': time.time(),
                        'idle_timeout': 7200,
                        'last_active': time.time(),
                        'hash_value': hash_value
                    }

                    logger.info(f"[{self.ip}:{self.listen_port}] 接受新连接: {client_address}")
                    self.send_msg(addr_str, Hash_Verify(challenge=challenge_str), force=True, priority=0)
                else:
                    # 跳过哈希校验，直接进入stage 1
                    self.tcp_connections[addr_str] = {
                        'socket': client_socket,
                        'stage': 1,
                        'connect_time': time.time(),
                        'connect_type': None,
                        'send_buffer': [b'', b'', b'', b'', b''],
                        'heartbeat_time': time.time(),
                        'idle_timeout': 7200,
                        'last_active': time.time()
                    }

                    logger.info(f"[{self.ip}:{self.listen_port}] 接受新连接: {client_address} (跳过哈希校验)")
                    # 直接发送ConnectInit消息
                    self.send_msg(addr_str, ConnectInit('STP', self.listen_port), force=True, priority=0)
            except BlockingIOError:
                # 没有新连接
                pass
            except Exception as e:
                logger.warning(f"[{self.ip}:{self.listen_port}] 接受连接错误: {e}")

        # 接收所有连接的数据
        disconnected_sockets = []

        for addr, conn_info in list(self.tcp_connections.items()):
            try:
                # 潜在问题：如果网络卡得消息头接收都不完整
                sock = conn_info['socket']
                # 非阻塞接收
                data = sock.recv(4096)

                if data:
                    # 将数据添加到该socket的缓冲区
                    if sock not in self.recv_buffers:
                        self.recv_buffers[sock] = [b'', b'', b'', b'', b'']
                    split = data.split(b'\n\r')
                    for i in range(len(split)):
                        if i == 0:
                            continue
                        else:
                            priority = int(split[i-1][-1:].decode())
                        if i == len(split) - 1:
                            self.recv_buffers[sock][priority] += split[i]
                        else:
                            self.recv_buffers[sock][priority] += split[i][:-1]

                    # 处理缓冲区中的完整消息
                    self.process_recv_buffer(sock, addr)
                elif data == b'':
                    # 连接已关闭
                    disconnected_sockets.append((addr, sock, '连接已关闭。', 'warning'))

            except BlockingIOError:
                # 没有数据可读，继续处理下一个socket
                continue
            except ConnectionResetError:
                disconnected_sockets.append((addr, sock, '连接被重置。', 'warning'))
            except ConnectionAbortedError:
                disconnected_sockets.append((addr, sock, '连接被终止。', 'warning'))
            except Exception as e:
                logger.error(f"[{self.ip}:{self.listen_port}] 接收数据错误 ({addr}): {e}")

        # 清理断开的连接
        for addr, sock, result, level in disconnected_sockets:
            (ip, port) = addr.split(':')
            self.disconnect_net(ip, port, result=result, level=level)

    def process_recv_buffer(self, sock, addr):
        """处理接收缓冲区中的完整消息"""
        if sock not in self.recv_buffers:
            return

        for priority in range(len(self.recv_buffers[sock])):
            buffer = self.recv_buffers[sock][priority]
            # 在二进制数据中查找 \r\n
            while b'\r\n' in buffer:
                pos = buffer.find(b'\r\n')

                # 提取一个完整消息（不包括 \r\n）
                message_bytes = buffer[:pos]
                buffer = buffer[pos + 2:]  # 跳过 \r\n
                try:
                    # 解码为JSON字符串
                    json_str = message_bytes.decode('utf-8')

                    # 解析JSON
                    packet_dict = json.loads(json_str)

                    sock: socket.socket
                    packet_dict['source_addr'] = addr

                    # 重建DataPacket对象
                    packet = self.reconstruct_packet(packet_dict)

                    if packet:
                        # 将消息添加到msg_buffer
                        with self.buffer_lock:
                            self.msg_buffer.append(packet)

                        # if type(packet.data) != BPDU:
                        #     logger.debug(f"[{self.ip}:{self.listen_port}] 收到 {type(packet.data).__name__} 来自 {addr}")

                        if type(packet.data) != HeartBeat:
                            # 收到有效消息，标记为活跃
                            self.tcp_connections[addr]['last_active'] = time.time()

                except UnicodeDecodeError as e:
                    logger.debug(f"[{self.ip}:{self.listen_port}] 解码失败: {e}")
                except json.JSONDecodeError as e:
                    logger.debug(f"[{self.ip}:{self.listen_port}] JSON解析失败: {e}。\n原始数据: {message_bytes[:100]}")
                except Exception as e:
                    logger.debug(f"[{self.ip}:{self.listen_port}] 处理消息失败: {e}")
            # 更新缓冲区
            self.recv_buffers[sock][priority] = buffer

    def reconstruct_packet(self, packet_dict):
        """从字典重建DataPacket对象 - 使用递归Decoder优化"""

        def Decoder(data):
            # 获取协议类型
            if 'Protocol' not in data:
                return data

            protocol = data.pop('Protocol')

            # 如果协议类型不在映射中，返回原始数据
            if protocol not in PROTOCOL_CLASSES:
                logger.warning(f"未知协议类型: {protocol}")
                return data

            # 递归处理所有属性
            processed_kwargs = {}
            for key, value in data.items():
                if isinstance(value, dict):
                    # 如果是字典，递归处理
                    processed_kwargs[key] = Decoder(value)
                elif isinstance(value, list):
                    # 如果是列表，递归处理列表中的每个元素
                    processed_kwargs[key] = [
                        Decoder(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    # 基本类型直接保留
                    processed_kwargs[key] = value

            try:
                # 使用解包参数创建对象
                return PROTOCOL_CLASSES[protocol](**processed_kwargs)
            except TypeError as e:
                logger.error(f"创建协议对象 {protocol} 失败: {e}")
                logger.error(f"参数: {processed_kwargs}")
                # 返回原始数据以便调试
                data['Protocol'] = protocol
                return data

        try:
            source_addr = packet_dict.get('source_addr')
            source_mac = packet_dict.get('source_mac')
            data_dict = packet_dict.get('data', {})

            # 使用Decoder递归重建数据对象
            data_obj = Decoder(data_dict)

            # 如果Decoder返回的是字典（例如未知协议），则保持原样
            if isinstance(data_obj, dict):
                # 尝试创建通用的DataPacket对象
                return DataPacket(
                    source_addr=source_addr,
                    source_mac=source_mac,
                    data=data_obj
                )
            else:
                # 创建DataPacket对象
                return DataPacket(
                    source_addr=source_addr,
                    source_mac=source_mac,
                    data=data_obj
                )

        except KeyError as e:
            logger.error(f"{self.ip}:{self.listen_port} 消息缺少字段: {e}")
            return None
        except Exception as e:
            logger.error(f"{self.ip}:{self.listen_port} 重建包失败: {e}\n原消息: {packet_dict}")
            return None

    def draw_topology(self, topology_id=None):
        """绘制基于拓扑包的拓扑图

        参数:
            topology_id: 拓扑包ID，如果为None则使用最新的拓扑
        """
        # 延迟导入，避免未安装matplotlib时程序无法启动
        try:
            import matplotlib.pyplot as plt
            import networkx as nx
            from matplotlib.animation import FuncAnimation
            # 设置中文字体（Windows系统）
            plt.rcParams['font.sans-serif'] = ['SimHei']  # 黑体
            plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
        except ImportError as e:
            logger.error(f"绘图库未安装: {e}")
            logger.info("请运行: pip install matplotlib networkx")
            return

        # 准备拓扑数据，包括本设备的数据
        if not hasattr(self, 'topology') or not self.topology:
            logger.warning("没有可用的拓扑数据")
            return

        if topology_id is None:
            # 使用最新的拓扑ID
            topology_id = max(self.topology.keys()) if self.topology else None

        if topology_id not in self.topology:
            logger.warning(f"拓扑ID {topology_id} 不存在")
            return

        # 获取拓扑数据
        topology_data = self.topology[topology_id]

        # 添加本设备的拓扑信息
        if self.mac not in topology_data:
            # 构建本设备的端口角色字典（基于MAC地址）
            my_mac_roles = {}
            for addr, role in self.port_roles.items():
                if addr in self.tcp_connections and 'mac' in self.tcp_connections[addr]:
                    neighbor_mac = self.tcp_connections[addr]['mac']
                    my_mac_roles[neighbor_mac] = role
            if my_mac_roles:  # 只有在有连接时才添加
                topology_data[self.mac] = my_mac_roles

        if not topology_data:
            logger.warning(f"拓扑ID {topology_id} 数据为空")
            return

        # 创建图形窗口
        fig, ax = plt.subplots(figsize=(12, 8))
        fig.canvas.manager.set_window_title(f'设备 {self.mac[:8]} 拓扑图')

        # 颜色定义
        colors = {
            'root_bridge': 'gold',  # 根桥（金色）
            'received_device': 'lightblue',  # 已收到拓扑包的设备
            'missing_device': 'lightgray',  # 未收到拓扑包的设备
        }

        # 边样式定义 - 按照您的要求修改
        edge_styles = {
            'both_root': ('solid', 2, 'orange'),  # 橙色的实线,lw=2
            'both_designated': ('solid', 2, 'red'),  # 红色的实线,lw=2
            'peer_ports': ('solid', 2, 'green'),  # 绿色实线,lw=2
            'root_only': ('dashed', 2, 'orange'),  # 橙色的虚线,lw=2
            'designated_only': ('dashed', 1, 'yellow'),  # 黄色的虚线,lw=1
            'blocked': ('dashed', 1, 'gray'),  # 灰色的虚线,lw=1
            'unknown': ('solid', 2, 'gray')  # 灰色的实线,lw=2
        }

        # 辅助函数：格式化MAC地址显示（只显示前5个字符）
        def format_mac(mac_str):
            """格式化MAC地址，只显示前5个字符"""
            # 移除冒号，取前5个字符
            clean_mac = mac_str.replace(':', '')
            short_mac = clean_mac[:5]
            # 格式化为xx:xx形式
            if len(short_mac) >= 4:
                return f"{short_mac[:2]}:{short_mac[2:4]}"
            else:
                return short_mac

        # MAC地址到坐标的映射
        def mac_to_position(mac_str):
            """将MAC地址转换为固定位置坐标"""
            import math
            # 移除冒号，转换为数字
            mac_clean = mac_str.replace(':', '')

            # 使用不同的部分计算坐标
            try:
                if len(mac_clean) >= 6:
                    x_seed = int(mac_clean[:6], 16)
                    y_seed = int(mac_clean[6:] if len(mac_clean) > 6 else mac_clean, 16)
                else:
                    x_seed = int(mac_clean, 16)
                    y_seed = int(mac_clean, 16)

                # 使用三角函数产生分散的坐标
                x = (math.sin(x_seed * 0.01) + 1) * 0.4 + 0.1
                y = (math.cos(y_seed * 0.01) + 1) * 0.4 + 0.1

                return (x, y)
            except:
                # 如果转换失败，使用随机位置
                return (random.random() * 0.8 + 0.1, random.random() * 0.8 + 0.1)

        # 确定边的类型
        def determine_edge_type(role1, role2):
            """根据两个端口的角色确定边的类型"""
            # 角色映射：0=根端口，1=指定端口，2=阻塞端口
            if role1 == 0 and role2 == 0:
                return 'both_root'  # 双向根端口（理论上不应该发生）
            elif role1 == 1 and role2 == 1:
                return 'both_designated'  # 双向指定端口（可能导致环路）
            elif (role1 == 0 and role2 == 1) or (role1 == 1 and role2 == 0):
                return 'peer_ports'  # 对等端口（正常通信）
            elif (role1 == 0 and role2 == 2) or (role1 == 2 and role2 == 0):
                return 'root_only'  # 单向根端口
            elif (role1 == 1 and role2 == 2) or (role1 == 2 and role2 == 1):
                return 'designated_only'  # 单向指定端口
            elif role1 == 2 and role2 == 2:
                return 'blocked'  # 双向阻塞
            else:
                return 'unknown'  # 未知类型

        # 获取所有设备
        all_devices = set()
        for source_mac, neighbors in topology_data.items():
            all_devices.add(source_mac)
            all_devices.update(neighbors.keys())

        # 生成设备位置
        device_positions = {mac: mac_to_position(mac) for mac in all_devices}

        # 创建图
        G = nx.Graph()

        # 确定根桥
        root_bridge_mac = None
        for device_mac in all_devices:
            if device_mac == self.root_mac:
                root_bridge_mac = device_mac
                break

        # 添加节点
        for device in all_devices:
            # 判断设备是否提供了拓扑数据
            has_data = device in topology_data

            # 确定是否为根桥
            is_root_bridge = (device == root_bridge_mac)

            G.add_node(device,
                       label=format_mac(device),  # 显示格式化后的MAC
                       has_data=has_data,
                       is_root_bridge=is_root_bridge)

        # 收集所有边及其类型
        edges_info = []

        # 第一次遍历：根据拓扑数据添加边
        for source_mac, neighbors in topology_data.items():
            for neighbor_mac, role_source_to_neighbor in neighbors.items():
                # 检查反向连接是否存在
                if neighbor_mac in topology_data and source_mac in topology_data[neighbor_mac]:
                    role_neighbor_to_source = topology_data[neighbor_mac][source_mac]
                    edge_type = determine_edge_type(role_source_to_neighbor, role_neighbor_to_source)
                else:
                    # 只有单向信息
                    edge_type = 'unknown'

                edges_info.append({
                    'source': source_mac,
                    'target': neighbor_mac,
                    'type': edge_type,
                    'role1': role_source_to_neighbor,
                    'role2': topology_data[neighbor_mac].get(source_mac, 2) if neighbor_mac in topology_data else 2
                })

                # 添加边到图
                if not G.has_edge(source_mac, neighbor_mac):
                    G.add_edge(source_mac, neighbor_mac,
                               type=edge_type,
                               role1=role_source_to_neighbor,
                               role2=topology_data[neighbor_mac].get(source_mac,
                                                                     2) if neighbor_mac in topology_data else 2)

        # 绘制函数
        def draw_topology_frame():
            """绘制拓扑图的一帧"""
            ax.clear()

            # 绘制节点
            node_colors = []
            node_sizes = []
            labels = {}

            for node in G.nodes():
                node_data = G.nodes[node]

                # 确定节点颜色
                if node_data['is_root_bridge']:
                    node_colors.append(colors['root_bridge'])  # 根桥用金色
                    node_sizes.append(1200)  # 根桥节点更大
                elif node_data['has_data']:
                    node_colors.append(colors['received_device'])
                    node_sizes.append(800)
                else:
                    node_colors.append(colors['missing_device'])
                    node_sizes.append(800)

                labels[node] = node_data['label']

            nx.draw_networkx_nodes(G, device_positions,
                                   node_color=node_colors,
                                   node_size=node_sizes,
                                   alpha=0.8,
                                   ax=ax)

            # 绘制节点标签
            nx.draw_networkx_labels(G, device_positions, labels,
                                    font_size=9,
                                    ax=ax)

            # 按边类型分组绘制边
            edge_groups = {edge_type: [] for edge_type in edge_styles.keys()}

            for u, v, edge_data in G.edges(data=True):
                edge_type = edge_data.get('type', 'unknown')
                if edge_type in edge_groups:
                    edge_groups[edge_type].append((u, v))

            # 绘制各种类型的边
            for edge_type, edges in edge_groups.items():
                if edges:
                    style, width, color = edge_styles[edge_type]
                    nx.draw_networkx_edges(G, device_positions,
                                           edgelist=edges,
                                           style=style,
                                           width=width,
                                           edge_color=color,
                                           alpha=0.7,
                                           ax=ax)

            # 添加图例
            from matplotlib.patches import Patch
            from matplotlib.lines import Line2D

            legend_elements = [
                Patch(facecolor=colors['root_bridge'], label='根桥'),
                Patch(facecolor=colors['received_device'], label='已收到拓扑包的设备'),
                Patch(facecolor=colors['missing_device'], label='未收到拓扑包的设备'),
                Line2D([0], [0], color='green', linewidth=2, linestyle='solid', label='对等端口（正常通信）'),
                Line2D([0], [0], color='orange', linewidth=2, linestyle='solid', label='双向根端口'),
                Line2D([0], [0], color='orange', linewidth=2, linestyle='dashed', label='单向根端口'),
                Line2D([0], [0], color='red', linewidth=2, linestyle='solid', label='双向指定端口'),
                Line2D([0], [0], color='yellow', linewidth=1, linestyle='dashed', label='单向指定端口'),
                Line2D([0], [0], color='gray', linewidth=1, linestyle='dashed', label='阻塞端口'),
                Line2D([0], [0], color='gray', linewidth=2, linestyle='solid', label='未知连接')
            ]

            ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.05, 1))

            # 添加标题和信息
            title = f"设备 {format_mac(self.mac)} 拓扑图 (ID: {topology_id})"
            if self.root_mac == self.mac:
                title += " [根桥]"

            ax.set_title(title, fontsize=14)

            # 添加统计信息
            stats_text = f"设备总数: {len(all_devices)}\n"
            stats_text += f"已收到拓扑包: {len(topology_data)}\n"
            stats_text += f"连接总数: {len(edges_info)}\n"

            # 统计各种边类型
            edge_counts = {}
            for edge_info in edges_info:
                edge_type = edge_info['type']
                edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1

            stats_text += "\n连接类型统计:\n"
            for edge_type, count in edge_counts.items():
                # 将英文类型转换为中文描述
                edge_type_descriptions = {
                    'both_root': '双向根端口',
                    'both_designated': '双向指定端口',
                    'peer_ports': '对等端口',
                    'root_only': '单向根端口',
                    'designated_only': '单向指定端口',
                    'blocked': '阻塞端口',
                    'unknown': '未知连接'
                }
                chinese_desc = edge_type_descriptions.get(edge_type, edge_type)
                stats_text += f"  {chinese_desc}: {count}\n"

            ax.text(1.05, 0.5, stats_text, transform=ax.transAxes, fontsize=9,
                    verticalalignment='center', bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

            ax.set_xlim(-0.1, 1.2)
            ax.set_ylim(-0.1, 1.2)
            ax.axis('off')
            plt.tight_layout()

        # 初始绘制
        draw_topology_frame()

        # 创建动画更新函数
        def update(frame):
            """动画更新函数"""
            # 检查是否有新的拓扑数据
            current_topology_id = max(self.topology.keys()) if self.topology else topology_id

            nonlocal topology_data
            if current_topology_id in self.topology:
                topology_data = self.topology[current_topology_id]

                # 添加本设备的拓扑信息（如果还没有）
                if self.mac not in topology_data:
                    # 构建本设备的端口角色字典（基于MAC地址）
                    my_mac_roles = {}
                    for addr, role in self.port_roles.items():
                        if addr in self.tcp_connections and 'mac' in self.tcp_connections[addr]:
                            neighbor_mac = self.tcp_connections[addr]['mac']
                            my_mac_roles[neighbor_mac] = role
                    if my_mac_roles:  # 只有在有连接时才添加
                        topology_data[self.mac] = my_mac_roles

                # 更新设备集合
                all_devices.clear()
                for source_mac, neighbors in topology_data.items():
                    all_devices.add(source_mac)
                    all_devices.update(neighbors.keys())

                # 更新设备位置
                for device in all_devices:
                    if device not in device_positions:
                        device_positions[device] = mac_to_position(device)

                # 清空并重建图
                G.clear()

                # 确定根桥
                root_bridge_mac = None
                for device_mac in all_devices:
                    if device_mac == self.root_mac:
                        root_bridge_mac = device_mac
                        break

                # 添加节点
                for device in all_devices:
                    has_data = device in topology_data
                    is_root_bridge = (device == root_bridge_mac)
                    G.add_node(device,
                               label=format_mac(device),
                               has_data=has_data,
                               is_root_bridge=is_root_bridge)

                # 添加边
                edges_info.clear()
                for source_mac, neighbors in topology_data.items():
                    for neighbor_mac, role_source_to_neighbor in neighbors.items():
                        if neighbor_mac in topology_data and source_mac in topology_data[neighbor_mac]:
                            role_neighbor_to_source = topology_data[neighbor_mac][source_mac]
                            edge_type = determine_edge_type(role_source_to_neighbor, role_neighbor_to_source)
                        else:
                            edge_type = 'unknown'

                        edges_info.append({
                            'source': source_mac,
                            'target': neighbor_mac,
                            'type': edge_type
                        })

                        if not G.has_edge(source_mac, neighbor_mac):
                            G.add_edge(source_mac, neighbor_mac, type=edge_type)

            # 重新绘制
            draw_topology_frame()

            # 更新标题中的拓扑ID
            current_topology_id = max(self.topology.keys()) if self.topology else topology_id
            ax.set_title(f"设备 {format_mac(self.mac)} 拓扑图 (ID: {current_topology_id})", fontsize=14)

        # 创建动画
        ani = FuncAnimation(fig, update, interval=2000, cache_frame_data=False)

        # 显示图形
        plt.tight_layout()
        plt.show()

        return ani

    def hash_file(self, file_path, challenge_string):
        """
        获取文件哈希值
        """
        hash_obj = hashlib.sha256()

        # 先添加挑战字符串
        hash_obj.update(challenge_string.encode('utf-8'))

        # 分块读取文件并更新哈希
        with open(file_path, 'rb') as f:
            # 使用固定大小的块（例如64KB）
            for chunk in iter(lambda: f.read(65536), b''):
                hash_obj.update(chunk)

        return hash_obj.hexdigest()

    def auto_connect(self):
        def scan_ip(ip):
            try:
                for i in range(10):
                    response = ping3.ping(str(ip), timeout=1, unit='ms')
                    if response is not None and response is not False:
                        print(f"{ip} 在线，延时：{i * 1000 + response:.1f} ms，")
                        return str(ip)
            except Exception as e:
                print(e)
                pass
            return None

        def scan_network(network):
            online_hosts = []
            # 解析网段，如 "192.168.1.0/24"
            network_obj = ipaddress.ip_network(network, strict=False)

            with ThreadPoolExecutor(max_workers=config['scan_threads']) as executor:
                futures = {executor.submit(scan_ip, ip): ip for ip in network_obj.hosts()}

                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        online_hosts.append(result)

            return online_hosts

        primary_server = config['network']['primary_server']
        success = 0
        failed = []
        if len(primary_server) > 0:
            for dict in primary_server:
                ip = dict["ip"]
                port = str(dict["port"])
                print(f'正在尝试连接主服务器 {ip}:{port}...')
                if self.connect_net(ip, port, auto_reconnect=True):
                    success += 1
                    dict['failed'] = 0
                else:
                    if 'failed' in dict:
                        dict['failed'] += 1
                    else:
                        dict['failed'] = 1
                    if dict['failed'] >= config['primary_max_retries']:
                        failed.append(dict)
            if len(failed) > 0:
                for value in failed:
                    config['network']['primary_server'].remove(value)
                print(f'由于多次无法连接，已移除以下主服务器：{failed}')
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f)


            if success <= 0:
                print(f'无法连接到主服务器，系统正在扫描局域网设备。')
            else:
                return
        else:
            print(f'没有主服务器，系统正在扫描局域网设备。')

        all_ip = self.get_available_ip()
        online_hosts = []
        for k, v in all_ip.items():
            print(f'正在扫描 {k} 上 {v["ipv4"]} 中的所有设备...')
            online_hosts += scan_network(v['ipv4']+'/24')
        print("扫描完成！在线设备:", online_hosts)

        success = 0
        for ip in online_hosts:
            print(f'正在尝试连接局域网设备 {ip}:{self.listen_port}...')
            if self.connect_net(ip, config['listen_port'], auto_reconnect=True):
                success += 1

        if success - len(all_ip) <= 0:
            if len(config['network']['secondary_server']) > 0:
                dict = random.choice(config['network']['secondary_server'])
                ip = dict['ip']
                port = dict['port']
                print(f'无法在局域网中找到设备，系统将尝试连接备用服务器： {ip}:{port} 。')
                self.connect_net(ip, port, auto_reconnect=True)

            else:
                print(f'无法在局域网中找到设备且没有备用服务器，系统将不会连接任何网络。')

    def main(self):
        def schedule_send_BPDU():
            self.send_BPDU()

        def schedule_send_HeartBeat():
            for addr in self.tcp_connections.keys():
                self.send_msg(addr, HeartBeat(), priority=0)

        def schedule_auto_reconnect():
            for ip, port in self.auto_reconnect_list.keys():
                addr = f'{ip}:{port}'
                if addr not in self.tcp_connections:
                    logger.info(f"[{self.ip}:{self.listen_port}] 系统正在重新连接 {addr} 。")
                    if not self.connect_net(ip, port, connect_type=self.auto_reconnect_list[(ip, str(port))],
                                            auto_reconnect=True):
                        logger.error(f"[{self.ip}:{self.listen_port}] 自动连接失败，系统稍后会再次尝试重新连接。")
                    # 防止同时连接大量设备阻塞程序运行，从而导致消息未能及时处理
                    return

        def schedule_optimize_connection():
            for k, v in self.tcp_connections.items():
                ip, port = k.split(':')
                if int(port) == config['listen_port'] and v['connect_type'] == 'STP':
                    if 'stable_count' not in v:
                        v['stable_count'] = 0
                    else:
                        v['stable_count'] += 1
                    if v['stable_count'] >= config['stable_connection_count']:
                        d = {'ip': k.split(':')[0], 'port': k.split(':')[1]}
                        if d not in config['network']['primary_server']:
                            config['network']['primary_server'].append(d)
                            with open(config_file, 'w', encoding='utf-8') as f:
                                yaml.dump(config, f)
                            logger.info(f"{self.ip}:{self.listen_port} 已记录稳定连接: {k}")

        def schedule_cleanup_connection_attempts():
            """清理过期的连接尝试记录"""
            current_time = time.time()
            cleanup_window = config['connection_cleanup_window']  # 清理窗口（秒）
            
            expired_addrs = []
            
            for addr, info in self.connection_attempts.items():
                time_since_last = current_time - info['last_attempt']
                if time_since_last >= cleanup_window:
                    expired_addrs.append(addr)
            
            for addr in expired_addrs:
                del self.connection_attempts[addr]
                logger.debug(f"[{self.ip}:{self.listen_port}] 清理过期的连接尝试记录: {addr}")
        
        def schedule_cleanup_topology_data():
            """清理超出存储数量的拓扑数据"""
            max_entries = config.get('topology_max_entries', 10)  # 默认保留10个拓扑数据
            
            # 检查拓扑数据数量是否超过限制
            if len(self.topology) > max_entries:
                # 按拓扑ID排序（ID是时间戳，越小越旧）
                sorted_topology_ids = sorted(self.topology.keys())
                # 计算需要删除的数量
                delete_count = len(self.topology) - max_entries
                # 删除最旧的拓扑数据
                for i in range(delete_count):
                    if sorted_topology_ids[i] in self.topology:
                        del self.topology[sorted_topology_ids[i]]
                        logger.debug(f"[{self.ip}:{self.listen_port}] 清理旧拓扑数据，ID: {sorted_topology_ids[i]}")
                logger.info(f"[{self.ip}:{self.listen_port}] 拓扑数据清理完成，当前数量: {len(self.topology)}")

        
        root_time = config['root_timeout']
        if not self.start_listening():
            logger.critical(f"[{self.ip}:{self.listen_port}] 设备启动失败，无法监听端口")
            return
        self.add_scheduled_job(config['auto_send_BPDU_interval'], schedule_send_BPDU)
        self.add_scheduled_job(config['heartbeat_interval'], schedule_send_HeartBeat)
        self.add_scheduled_job(config['auto_reconnect_interval'], schedule_auto_reconnect)
        self.add_scheduled_job(config['optimize_connection_interval'], schedule_optimize_connection)
        self.add_scheduled_job(config['connection_cleanup_interval'], schedule_cleanup_connection_attempts)
        self.add_scheduled_job(config.get('topology_cleanup_interval', 60), schedule_cleanup_topology_data)

        while not self.shutdown_flag:
            # 处理定时任务
            self.scheduled_job()
            # 处理网络I/O
            self.process_network_io()

            # time_to_BPDU -= self.delay_time
            root_time -= self.delay_time
            msg = None

            # 检查BPDU是否超时
            if root_time <= 0:
                if self.root_mac != self.mac:
                    logger.warning(f"{self.ip}:{self.listen_port} BPDU超时事件: 根端口:{self.root_port}")
                    if self.root_port is not None and self.root_distance == 1:
                        self.age += 1
                    self.resetRootBridge()
                    root_time = config['root_timeout']

            disconnect_addrs = []
            for addr, conn_info in self.tcp_connections.items():
                # 断开超时未初始化的连接
                if conn_info['stage'] != 2:
                    if time.time() - conn_info['connect_time'] >= config['connect_init_timeout']:
                        disconnect_addrs.append((addr, '超时未初始化。'))

                # 断开超时未发送心跳的连接
                elif time.time() - conn_info['heartbeat_time'] >= config['heartbeat_timeout']:
                    disconnect_addrs.append((addr, '心脏骤停。'))

                # 断开空闲的连接
                elif time.time() - conn_info['last_active'] >= conn_info['idle_timeout']:
                    disconnect_addrs.append((addr, '空闲过久。'))

                # 发送缓冲区消息
                else:
                    # 发送消息
                    for priority in range(5):
                        data = conn_info['send_buffer'][priority]
                        if len(data) > 0:
                            data = str(priority).encode() + b'\n\r' + data
                            for attempt in range(config['send_msg_retry_count']):
                                try:
                                    if priority <= 2:
                                        # 高优先级消息 (0-2) 使用 sendall
                                        conn_info['socket'].sendall(data)
                                        conn_info['send_buffer'][priority] = b''
                                    else:
                                        # 低优先级消息 (3-4) 使用 send，允许部分发送
                                        sent = conn_info['socket'].send(data)
                                        if sent > 0:
                                            # 减去已发送的字节
                                            conn_info['send_buffer'][priority] = data[sent:]
                                    break
                                except OSError as e:
                                    if attempt >= config['send_msg_retry_count'] - 1:
                                        logger.error(f"[{self.ip}:{self.listen_port}] 消息发送失败。行动:跳过。")
                                        break

            if len(disconnect_addrs) > 0:
                for addr, result in disconnect_addrs:
                    ip, port = addr.split(':')
                    self.disconnect_net(ip, port, result=result, level='warning')
            with self.buffer_lock:
                if len(self.msg_buffer):
                    msg = self.msg_buffer.pop(0)
            if msg is not None:
                msg: DataPacket

                def verify_connection():
                    if msg.source_addr not in self.tcp_connections:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 不存在的连接消息: {msg.data} ,该连接( {msg.source_addr} )可能已经断开。行动:忽略。")
                        return False
                    else:
                        return True

                if isinstance(msg.data, ConnectInit):
                    msg.data: ConnectInit
                    if not verify_connection():
                        continue
                    if self.tcp_connections[msg.source_addr]['stage'] == 1:
                        # ARP检查
                        if msg.source_mac == self.mac:
                            (target_ip, target_port) = msg.source_addr.split(':')
                            if (target_ip, self.listen_port) in self.auto_reconnect_list:
                                self.cancel_reconnect(target_ip, str(self.listen_port))
                            self.disconnect_net(target_ip, target_port, result='检测到自身连接！', level='warning')
                            continue
                        elif msg.source_mac not in self.arp:
                            self.tcp_connections[msg.source_addr]['mac'] = msg.source_mac
                            self.arp[msg.source_mac] = msg.source_addr
                        elif msg.source_addr != self.arp[msg.source_mac]:  # 同设备但地址不同
                            (target_ip, target_port) = msg.source_addr.split(':')
                            self.disconnect_net(target_ip, target_port, result=f'已存在同MAC连接: {msg.source_mac} 。',
                                                level='warning')
                            continue

                        # 协议检查
                        init_success = False
                        if msg.data.type == 'STP':
                            init_success = True
                            self.port_roles[msg.source_addr] = Port.BLOCKING_PORT

                            # 连接首次发送BPDU
                            self.send_msg(msg.source_addr, ConnectInit('STP', self.listen_port), force=True, priority=0)
                            self.send_BPDU(targets=[msg.source_addr], force=True)
                        elif msg.data.type == 'FORWARD':  # (如果是xxx协议)
                            init_success = True

                            self.send_msg(msg.source_addr, ConnectInit('FORWARD', self.listen_port), force=True, priority=0)
                        else:
                            logger.warning(
                                f"[{self.ip}:{self.listen_port}] IP: {msg.source_addr}, MAC: {msg.source_mac} 未知初始化协议: {msg.data.type} 。")

                        if init_success:
                            self.tcp_connections[msg.source_addr]['stage'] = 2
                            self.tcp_connections[msg.source_addr]['connect_type'] = msg.data.type
                            logger.info(
                                f"[{self.ip}:{self.listen_port}] IP: {msg.source_addr}, MAC: {msg.source_mac} 初始化协议: {msg.data.type} 。")
                        else:
                            logger.warning(
                                f"[{self.ip}:{self.listen_port}] IP: {msg.source_addr}, MAC: {msg.source_mac} 初始化失败。")
                    elif self.tcp_connections[msg.source_addr]['stage'] == 2:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 地址: {msg.source_addr} 尝试重新初始化。行动:忽略。")
                    elif self.tcp_connections[msg.source_addr]['stage'] == 0:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 地址: {msg.source_addr} 未经哈希验证尝试初始化。行动:忽略。")
                elif isinstance(msg.data, BPDU):
                    if not verify_connection():
                        continue
                    if msg.source_addr in self.port_roles:
                        msg.data: BPDU

                        def changeRoot():
                            nonlocal root_time
                            if self.root_port is not None:
                                self.port_roles[self.root_port] = Port.BLOCKING_PORT
                            self.root_mac = msg.data.root_mac
                            self.root_port = msg.source_addr
                            self.root_distance = msg.data.root_distance + 1
                            root_time = config['root_timeout']
                            self.setRoot_port(self.root_port)
                            # self.port_roles[self.root_port] = Port.ROOT_PORT

                        if msg.data.root_mac == self.root_mac:
                            if msg.data.root_distance + 1 > self.root_distance:
                                if msg.data.root_distance != self.root_distance:
                                    self.des_port(msg.source_addr)
                                else:
                                    # self.send_BPDU(targets=[msg.source_ip], force=True)
                                    self.send_msg(msg.source_addr, BPDU_Control(block_me=True), priority=1)
                                    self.block_port(msg.source_addr)
                            elif msg.data.root_distance + 1 < self.root_distance:
                                changeRoot()
                            elif msg.data.root_distance + 1 == self.root_distance:
                                if self.root_port is not None and msg.source_mac == self.root_port_mac:  # 上级设备发来BPDU，重置倒计时
                                    root_time = config['root_timeout']
                                elif self.mac_to_int(msg.source_mac) < self.mac_to_int(
                                        self.root_port_mac if self.root_port_mac else "ff:ff:ff:ff:ff:ff"):  # 端口ID更优，改变根
                                    changeRoot()
                                else:
                                    self.send_msg(msg.source_addr, BPDU_Control(block_me=True), priority=1)
                                    self.block_port(msg.source_addr)
                        elif self.mac_to_int(msg.data.root_mac) < self.mac_to_int(self.root_mac):
                            changeRoot()
                        else:
                            if self.port_roles[msg.source_addr] == Port.ROOT_PORT:  # 根端口失效，有可能是根桥故障
                                if msg.data.age > self.age:
                                    self.age = msg.data.age
                                self.resetRootBridge()
                                root_time = config['root_timeout']
                            else:
                                if msg.data.age <= self.age:
                                    self.des_port(msg.source_addr)
                                else:
                                    self.age = msg.data.age
                                    self.resetRootBridge()
                                    root_time = config['root_timeout']
                                    pass
                    else:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 收到未初始化STP的地址: {msg.source_addr} 的BPDU。行动:忽略。")
                elif isinstance(msg.data, Msg):
                    msg.data: Msg
                    print(f"[{self.ip}:{self.listen_port}] [{msg.source_addr}]: {msg.data.msg}")
                    # 调用 STPApp 的 process_msg 方法处理消息
                    if self.stp_app:
                        # 检查 msg.data.msg 是否是字典
                        if isinstance(msg.data.msg, dict):
                            msg_dict = msg.data.msg
                        else:
                            # 兼容旧格式
                            msg_dict = {
                                'source': msg.source_addr,
                                'source_mac': msg.source_mac,
                                'msg': msg.data.msg,
                                'target': 'all',
                                'user': msg.source_mac
                            }
                        self.stp_app.process_msg(msg_dict)
                elif isinstance(msg.data, Broadcast):
                    if not verify_connection():
                        continue
                    if msg.source_addr in self.port_roles:
                        if self.port_roles[msg.source_addr] == Port.DESIGNATED_PORT or self.port_roles[
                            msg.source_addr] == Port.ROOT_PORT:
                            msg.data: Broadcast
                            global msg_count
                            msg_count += 1
                            if type(msg.data.data) == BTopology:
                                msg.data.data: BTopology
                                if (not (
                                        bool(msg.data.data.forward_addr) or bool(msg.data.data.forward_mac))) and bool(
                                    msg.data.data.source_port):
                                    source_addr = f'{msg.source_addr.split(":")[0]}:{msg.data.data.source_port}'
                                    msg.data.data.forward_addr = source_addr
                                    msg.data.data.forward_mac = msg.source_mac
                                    msg.data.data.source_port = False

                            self.broadcast(msg)
                            if type(msg.data.data).__name__ in PROTOCOL_CLASSES:
                                wrap = DataPacket(source_addr=msg.source_addr, source_mac=msg.source_mac,
                                                  data=msg.data.data)
                                with self.buffer_lock:
                                    self.msg_buffer.append(wrap)
                            logger.info(
                                f"[{self.ip}:{self.listen_port}] 收到广播消息 {msg.data.data} ,来自 {msg.source_mac}")
                        else:
                            global msg_drop
                            msg_drop += 1
                            logger.warning(
                                f"[{self.ip}:{self.listen_port}] 阻塞端口收到广播消息 {msg.data.data} ,来自 {msg.source_mac} 。行动:忽略。")
                    else:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 收到未初始化STP的地址: {msg.source_addr} 的广播。行动:忽略。")
                elif isinstance(msg.data, BPDU_Control):
                    if not verify_connection():
                        continue
                    if msg.source_addr in self.port_roles:
                        msg.data: BPDU_Control
                        if msg.data.block_me:
                            self.block_port(msg.source_addr)
                            logger.info(
                                f"[{self.ip}:{self.listen_port}] 收到 {msg.source_addr} 的BPDU控制协议。行动:阻塞。")
                    else:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 收到未初始化STP的地址: {msg.source_addr} 的BPDU控制协议。行动:忽略。")
                elif isinstance(msg.data, Forward):
                    msg.data: Forward
                    if msg.data.target_mac == self.mac:
                        logger.info(
                            f"[{self.ip}:{self.listen_port}] 收到中转消息 {msg.data.data} ,来自 {msg.source_mac} 。行动:读取。")
                        if type(msg.data.data).__name__ in PROTOCOL_CLASSES:
                            wrap = DataPacket(source_addr=msg.source_addr, source_mac=msg.source_mac,
                                              data=msg.data.data)
                            with self.buffer_lock:
                                self.msg_buffer.append(wrap)
                    elif msg.data.target_mac in self.arp:
                        logger.info(
                            f"[{self.ip}:{self.listen_port}] 收到中转消息 {msg.data.data} ,来自 {msg.source_mac} 。行动:转发。")
                        target_addr = self.arp[msg.data.target_mac]
                        self.send_msg(target_addr, msg.data, priority=1)
                    else:
                        logger.error(
                            f"[{self.ip}:{self.listen_port}] 无法中转来自 {msg.source_mac} 的消息 {msg.data.data} 。原因:找不到连接。")
                elif isinstance(msg.data, BTopology):
                    msg.data: BTopology
                    if msg.data.forward_addr:
                        msg.data.forward_addr: str
                        ip, port = msg.data.forward_addr.split(':')
                        mac_role = {}
                        for addr, role in self.port_roles.items():
                            if addr in self.tcp_connections:
                                mac_role[self.tcp_connections[addr]['mac']] = role
                            else:
                                logger.warning(
                                    f"[{self.ip}:{self.listen_port}] 找不到 {addr} 对应的 mac 地址。(这是一个代码bug)")
                        if msg.data.forward_mac in self.arp:
                            self.send_msg(self.arp[msg.data.forward_mac], Forward(self.mac, msg.data.source_mac,
                                                                                  Topology(self.mac, mac_role,
                                                                                           msg.data.id)), priority=1)
                        elif msg.data.forward_mac == self.mac:
                            if msg.data.source_mac in self.arp:
                                self.send_msg(self.arp[msg.data.source_mac], Topology(self.mac, mac_role, msg.data.id), priority=2)
                            else:
                                logger.error(f"[{self.ip}:{self.listen_port}] 无法发送拓扑包。原因:找不到连接。")
                        else:
                            if self.connect_net(ip, port, connect_type='FORWARD',
                                                idle_timeout=config['topology_response_idle_timeout']):
                                self.send_msg(msg.data.forward_addr, Forward(self.mac, msg.data.source_mac,
                                                                             Topology(self.mac, mac_role, msg.data.id)), priority=1)
                                self.send_msg(msg.data.forward_addr, Connect_Control('CLOSE'), priority=1)
                elif isinstance(msg.data, Topology):
                    msg.data: Topology
                    if msg.data.id not in self.topology:
                        self.topology[msg.data.id] = {}
                    self.topology[msg.data.id][msg.data.source_mac] = msg.data.mac_role
                    logger.info(f"[{self.ip}:{self.listen_port}] 收到 {msg.data.source_mac} 拓扑数据包。")
                elif isinstance(msg.data, Connect_Control):
                    msg.data: Connect_Control
                    action = msg.data.action
                    if action == 'CLOSE':
                        ip, port = msg.source_addr.split(':')
                        self.disconnect_net(ip, port, result=f'{msg.source_addr} 的关闭连接控制协议。')

                    else:
                        logger.warning(
                            f"[{self.ip}:{self.listen_port}] 收到 {msg.source_addr} 未知的连接控制协议: {msg.data.action}。行动:忽略。")

                elif isinstance(msg.data, HeartBeat):
                    msg.data: HeartBeat
                    if not verify_connection():
                        continue
                    self.tcp_connections[msg.source_addr]['heartbeat_time'] = time.time()
                elif isinstance(msg.data, Hash_Verify):
                    msg.data: Hash_Verify
                    if not verify_connection():
                        continue
                    if msg.data.challenge is not None:
                        hash_value = self.hash_file(__file__, msg.data.challenge)
                        self.send_msg(msg.source_addr, Hash_Verify(value=hash_value), force=True, priority=0)
                        self.tcp_connections[msg.source_addr]['stage'] = 1
                        self.send_msg(msg.source_addr, ConnectInit(self.tcp_connections[msg.source_addr]['connect_type'], self.listen_port), force=True, priority=0)
                    else:
                        if msg.data.value == self.tcp_connections[msg.source_addr]['hash_value']:
                            self.tcp_connections[msg.source_addr]['stage'] = 1
                            del self.tcp_connections[msg.source_addr]['hash_value']
                        else:
                            ip, port = msg.source_addr.split(':')
                            self.disconnect_net(ip, port, result='文件完整性校验失败。', level='warning')
                else:
                    logger.warning(f"[{self.ip}:{self.listen_port}] 收到未知协议消息 {msg.data} ,来自 {msg.source_mac}")

            delay_time = 0.1 / max(len(self.msg_buffer), 1)
            delay_time = max(config['system_sleep_time_min'], delay_time)
            delay_time = min(delay_time, config['system_sleep_time_max'])
            self.delay_time = delay_time
            time.sleep(self.delay_time)


class STPApp(BaseApp):
    def __init__(self, system, hash_verification=True):
        super().__init__(system, "STPApp", "1.0.0")
        self.core = None
        self.create_port = config['listen_port']
        self.msg_count = 0
        self.msg_drop = 0
        self.cores = []
        self.hash_verification = hash_verification  # 哈希校验开关，默认为True
        
        # 消息订阅者字典，每个元素应该为队列类型
        self.msg_subscriptions = {}
        # 用于保护订阅者字典的锁
        self.subscriptions_lock = threading.RLock()

    def _main(self, *args, **kwargs):
        # 全局变量映射
        global create_port, msg_count, msg_drop, devices
        create_port = self.create_port
        msg_count = self.msg_count
        msg_drop = self.msg_drop
        cores = self.cores

        # 创建核心并启动
        self.core = STPCore(self.create_port, real=True, stp_app=self, hash_verification=self.hash_verification)
        self.core.start()
        self.core.auto_connect()

        # 保持应用运行
        while self.running:
            time.sleep(0.1)

    def _reset(self):
        # 清理资源
        if self.core:
            self.core.shutdown()
        logger.info(f"[{self.name}] 应用已重置")

    def get_core(self):
        """获取核心实例"""
        return self.core
    
    def send_msg(self, target_addr, msg):
        """发送消息
        :param target_addr: 目标地址
        :param msg: 消息内容
        """
        if not self.core:
            logger.error(f"[{self.name}] 核心未初始化，无法发送消息")
            return False
        
        # 构造消息字典
        msg_dict = {
            'source': f"{self.core.ip}:{self.core.listen_port}",
            'source_mac': self.core.mac,
            'msg': msg,
            'target': 'p2p',
            'user': self.system.device_name
        }
        
        # 创建Msg对象并发送
        from .STP import Msg
        try:
            return self.core.send_msg(target_addr, Msg(msg_dict))
        except Exception as e:
            logger.error(f"[{self.name}] 发送消息时出错: {e}")
            return False
    
    def broadcast_msg(self, msg, target="all"):
        """广播消息
        :param msg: 消息内容
        :param target: 目标设备名，默认为"all"
        """
        if not self.core:
            logger.error(f"[{self.name}] 核心未初始化，无法广播消息")
            return False
        
        # 构造消息字典
        msg_dict = {
            'source': f"{self.core.ip}:{self.core.listen_port}",
            'source_mac': self.core.mac,
            'msg': msg,
            'target': target,
            'user': self.system.device_name
        }

        from .STP import Msg
        self.core.broadcast(Msg(msg_dict))
        return True
    
    def get_topology(self, forward_addr=False, forward_mac=False):
        """获取拓扑图
        :param forward_addr: 转发地址
        :param forward_mac: 转发MAC地址
        :return: 拓扑图数据
        """
        if not self.core:
            logger.error(f"[{self.name}] 核心未初始化，无法获取拓扑")
            return None
        
        self.core.get_Topology(forward_addr=forward_addr, forward_mac=forward_mac)
        # 返回当前最新的拓扑数据
        return self.core.topology
    
    def subscribe_msg(self, subscriber, buffer):
        """订阅消息
        :param subscriber: 订阅者唯一标识符
        :param buffer: 消息队列
        """
        with self.subscriptions_lock:
            self.msg_subscriptions[subscriber] = buffer
            logger.info(f"[{self.name}] 订阅者 {subscriber} 已订阅消息")
    
    def unsubscribe_msg(self, subscriber):
        """取消订阅消息
        :param subscriber: 订阅者唯一标识符
        """
        with self.subscriptions_lock:
            if subscriber in self.msg_subscriptions:
                del self.msg_subscriptions[subscriber]
                logger.info(f"[{self.name}] 订阅者 {subscriber} 已取消订阅")
            else:
                logger.warning(f"[{self.name}] 尝试取消不存在的订阅者: {subscriber}")
    
    def publish_msg(self, data):
        """发布消息到所有订阅者
        :param data: 要发布的消息数据
        """
        with self.subscriptions_lock:
            for subscriber, buffer in self.msg_subscriptions.items():
                try:
                    # 深拷贝数据以避免修改影响其他订阅者
                    import copy
                    data_copy = copy.deepcopy(data)
                    buffer.put(data_copy)
                except Exception as e:
                    logger.error(f"[{self.name}] 向订阅者 {subscriber} 发布消息时出错: {e}")
    
    def process_msg(self, msg_dict):
        """处理收到的消息
        :param msg_dict: 消息字典
        """
        self.publish_msg(msg_dict)


# 全局变量
create_port = config['listen_port']
msg_count = 0
msg_drop = 0
devices = []
device = None
