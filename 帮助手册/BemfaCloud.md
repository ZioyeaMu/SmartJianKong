# 巴法云类（BemfaCloud）

该类用于实现与巴法云服务器通信的功能

## 成员变量

### server_ip 

TCP连接需要连接到的网址

### server_port

网址对应的端口

### uid

巴法云中用户的私钥

### msg_topic

巴法云中需要订阅的消息主题（TCP设备云）

### img_topic

巴法云中需要订阅的**图片**主题（图存储）

### device_name

本设备的名称（用于区分不同设备收发的消息）

### reconnect_timeout

当巴法云出错后重连间隔时间（秒）

### heartbeat_thread

【无需修改】此成员变量用来存储每隔一段时间自动执行的心跳线程

### retry = 0

【无需修改】此成员变量用来存储系统重连的次数

### is_connected

【无需修改】此成员变量用来存储当前的巴法云连接状态

### socket

【无需修改】此成员变量用来存储TCP客户端类

### heart_run_event

【无需修改】此成员变量用来控制心跳线程的开启或关闭

## 功能函数

### 初始化（\__init__）

#### 参数列表

【可选】uid：用户的巴法云私钥，默认为test（无效私钥）

【可选】msg_topic：巴法云TCP设备云主题，默认为test1

【可选】img_topic：巴法云图存储主题，默认为test

【可选】device_name=：本设备的昵称，默认为空

#### 功能描述

初始化成员变量，为成员变量赋值

### 建立TCP连接（connect）

#### 功能描述

与巴法云服务器建立TCP连接

### 重新连接（reconnect）

#### 功能描述

尝试重新与巴法云服务器建立TCP连接直至成功

### 订阅主题（send_subscribe_command）

#### 功能描述

订阅指定（msg_topic）主题

### 启动心跳线程（start_heartbeat_thread）

#### 功能描述

启动一个新的心跳进程，或者重启该心跳进程（通过设置事件控制（heart_run_event.set()））

### 心跳线程主函数（send_heartbeat_loop）

#### 功能描述

心跳线程将会执行这个函数内的代码

### 发送心跳（send_heartbeat）

#### 功能描述

向巴法云发送一次心跳

### 上传图片（upload_image）

#### 参数列表

【必选】image_path：要上传的图片路径

#### 功能描述

向巴法云图存储指定的主题（img_topic）上传一张图片

### 推送消息（send）

#### 参数列表

【必选】msg：要推送的消息

#### 功能描述

向巴法云TCP设备云指定的主题（msg_topic）推送一条消息