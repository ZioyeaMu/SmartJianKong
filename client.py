import argparse
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'System')))
from System.system import System, app_initializer


# 使用装饰器包装应用注册代码
@app_initializer
def register_apps(self):
    from System.apps.testapp import TestApp
    from System.apps.client_MsgHandle import MsgHandleApp
    from System.apps.camera import CameraApp
    from System.apps.STP import STPApp
    from System.apps.client_fastapi import ClientFastAPI
    from System.apps.client_web import ClientWebApp

    # 安装应用2步骤：
    ta = TestApp(self)  # 1.实例化
    self.app_list.append(ta)  # 2.添加到清单
    self.install_app(
        app=ta,
        autostartup=False,
        startup_args=('args1', 'args2'),
        startup_kwargs={'kwargs1': 'kwargs1', 'kwargs2': 'kwargs2'}
    )   # 3.安装
    # 系统启动后会按照设定与否自动启动安装的应用
    # 应用清单的作用：相当于应用商店，告诉系统有这些软件可用

    mha = MsgHandleApp(self)
    self.app_list.append(mha)
    self.install_app(mha, autostartup=True)

    ca = CameraApp(self)
    self.app_list.append(ca)
    self.install_app(ca, autostartup=False)

    sa = STPApp(self, hash_verification=False)
    self.app_list.append(sa)
    self.install_app(sa, autostartup=True)

    # 安装中继应用（客户端模式）
    from System.apps.relay import RelayApp
    ra = RelayApp(self, server_mode=False, server_port=12345)
    self.app_list.append(ra)
    self.install_app(ra, autostartup=True)

    cfa = ClientFastAPI(self)
    self.app_list.append(cfa)
    self.install_app(cfa, autostartup=True)

    cwa = ClientWebApp(self)
    self.app_list.append(cwa)
    self.install_app(cwa, autostartup=True)


if __name__ == '__main__':
    # 创建系统实例，装饰器会自动执行应用注册
    system = System(enable_repl=True)
    system.run()

