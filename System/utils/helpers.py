import os
import uuid
import base64

def get_mac():
    """获取设备MAC地址的base64编码"""
    mac = uuid.getnode()
    mac_hex = '%012x' % mac
    mac_bytes = bytes.fromhex(mac_hex)
    base64_bytes = base64.b64encode(mac_bytes)
    base64_string = base64_bytes.decode('utf-8')
    six_char_string = base64_string[:6].replace('+', 'A').replace('/', 'B')
    return six_char_string

def clear_terminal():
    """跨平台清空终端"""
    os.system('cls' if os.name == 'nt' else 'clear')

