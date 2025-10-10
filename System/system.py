import sys
import types
import uuid
import base64
import os
import logging
import time
# from utils.helpers import get_mac
from System.utils.helpers import *
from core.base_app import BaseApp
import traceback

# 存储通过装饰器注册的应用初始化函数
APP_INITIALIZATION_FUNCTIONS = []


def app_initializer(func):
    """应用初始化装饰器"""
    APP_INITIALIZATION_FUNCTIONS.append(func)
    return func


class System:
    """系统主类"""

    def __init__(self, *args, **kwargs):
        try:
            self.config = kwargs
            self.device_name = get_mac()
            self.power = True
            self.run_time = None

            # 应用清单和字典
            self.app_list = []
            self.app_dict = {}

            # 自动启动应用，三元组(应用, *args, **kwargs)
            self.app_autostartup = []

            self.config['log_dir'] = kwargs.get('log_dir', './logs/')
            if not os.path.exists(self.config['log_dir']):
                os.makedirs(self.config['log_dir'])
            logging.basicConfig(
                # filename=os.path.join(
                #     self.log_dir,
                #     time.strftime('%Y-%m-%d-%H-%M-%S', time.localtime()) + '.txt'
                # ),  # 日志文件
                level=logging.DEBUG,  # 最低日志级别
                format="%(asctime)s - %(levelname)s - %(message)s",  # 日志格式
                datefmt="%Y-%m-%d %H:%M:%S",  # 时间格式
                encoding='utf-8',  # 指定UTF-8编码
                stream=sys.stdout
            )
            logging.info(f'[系统] 系统配置和日志系统初始化完成')

            logging.info(f'[系统] 正在加载系统软件...')
            # 系统应用在此添加：
            # test_app = TestApp(system=self)
            # self.app_list.append(test_app)
            # test_app = TestApp(system=self)
            # self.app_list.append(test_app)

            # 初始化应用
            for app in self.app_list:
                app: BaseApp
                self.install_app(app)
            logging.info(f'[系统] 系统软件加载完成')
            # raise Exception('test')

            # 执行通过装饰器注册的应用初始化函数
            logging.info(f'[系统] 正在加载用户软件...')
            for init_func in APP_INITIALIZATION_FUNCTIONS:
                # 创建一个新的函数，将system参数绑定到当前实例
                bound_init = types.MethodType(init_func, self)
                bound_init()

            logging.info(f'[系统] 用户软件加载完成')
            logging.info(f'[系统] 系统就绪，等待启动')
        except KeyboardInterrupt as e:
            clear_terminal()
            sys.stderr.write(
                f'''抱歉，您的系统由于初始化出现致命错误而导致崩溃，以下是错误信息：\n{'用户终止系统启动'}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
            sys.exit(1)
        except Exception as e:
            clear_terminal()
            sys.stderr.write(
                f'''抱歉，您的系统由于初始化出现致命错误而导致崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
            sys.exit(1)

    def install_app(self, app, autostartup=False, startup_args=(), startup_kwargs=None):
        """安装应用"""
        if startup_kwargs is None:
            startup_kwargs = {}

        if app.name in self.app_dict:
            logging.warning(f"[系统] 应用 {app.name} 已存在，将被替换")
        self.app_dict[app.name] = app
        if autostartup:
            self.app_autostartup.append((app, startup_args, startup_kwargs))
        logging.info(f"[系统] 应用 {app.name} 已安装")

    def uninstall_app(self, app_name):
        """卸载应用"""
        if app_name in self.app_dict:
            app = self.app_dict[app_name]
            app.stop()
            del self.app_dict[app_name]
            logging.info(f"[系统] 应用 {app_name} 已卸载")

    def get_app(self, app_name):
        """获取应用实例"""
        return self.app_dict.get(app_name, None)

    def run(self):
        try:
            self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
            logging.info(f'[系统] 系统于{self.run_time}启动')
            for app, args, kwargs in self.app_autostartup:
                try:
                    app.run(*args, **kwargs)
                except Exception as e:
                    logging.error(f"[系统] 启动应用 {app.name} 时发生错误: {e}")
                finally:
                    continue
            while self.power:
                time.sleep(0.01)
                pass
        except KeyboardInterrupt:
            logging.warning("[系统] 用户中断程序")
        except Exception as e:
            logging.critical(f'''抱歉，您的系统由于在运行时遇到未处理的错误而导致崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
            sys.stderr.write(
                f'''抱歉，您的系统由于在运行时遇到未处理的错误而导致崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
        finally:
            self.off()

    def off(self):
        """关闭系统"""
        # if self.power:
        self.power = False
        # 停止所有应用
        for app_name, app in self.app_dict.items():
            app.stop()
        logging.info("[系统] 系统已关闭")

    def get_status(self):
        """获取系统状态"""
        apps_status = {name: app.get_status() for name, app in self.app_dict.items()}

        return {
            "device_name": self.device_name,
            "power": self.power,
            "run_time": self.run_time,
            "apps": apps_status
        }

# s = System()
# s.run()
