import sys
import types
import uuid
import base64
import os
import logging
import time
import threading
# from utils.helpers import get_mac
from System.utils.helpers import *
from System.core.base_app import BaseApp
import traceback
import code

# 应用代理类
class AppProxy:
    """应用代理类，用于包装应用实例，实现生命周期管理"""
    
    def __init__(self, app, system):
        self._app = app
        self._system = system
        self._active = True
    
    def __getattr__(self, name):
        """拦截属性访问"""
        if self._app is None:
            raise RuntimeError(f"应用已被卸载")
        elif not self._active:
            raise RuntimeError(f"应用 {self._app.name} 已被禁用")
        
        return getattr(self._app, name)
    
    def __setattr__(self, name, value):
        """拦截属性设置"""
        if name.startswith('_'):
            # 允许设置私有属性
            super().__setattr__(name, value)
        else:
            if self._app is None:
                raise RuntimeError(f"应用已被卸载")
            elif not self._active:
                raise RuntimeError(f"应用 {self._app.name} 已被禁用")
            setattr(self._app, name, value)
    
    def deactivate(self):
        """停用代理"""
        self._active = False
    
    def is_active(self):
        """检查代理是否激活"""
        return self._active
    
    def uninstall(self):
        """卸载应用，将对象设置为None"""
        if self._app:
            # 将应用对象设置为None
            self._app = None
        # 停用代理
        self.deactivate()
        logging.info(f"[系统] 应用已被卸载")

# 存储通过装饰器注册的应用初始化函数
APP_INITIALIZATION_FUNCTIONS = []


def app_initializer(func):
    """应用初始化装饰器"""
    APP_INITIALIZATION_FUNCTIONS.append(func)
    return func


class System:
    """系统主类"""
    # 系统版本号
    VERSION = "1.2.1"

    def __init__(self, *args, **kwargs):
        try:
            self.config = kwargs
            self.device_name = get_mac()
            self.power = False
            self.run_time = None
            self.enable_repl = kwargs.get('enable_repl', False)

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
            # 从 app_autostartup 中移除该应用
            self.app_autostartup = [(a, args, kwargs) for a, args, kwargs in self.app_autostartup if a.name != app_name]
            # 从 app_list 中移除该应用
            self.app_list = [a for a in self.app_list if a.name != app_name]
            logging.info(f"[系统] 应用 {app_name} 已卸载")

    def get_app(self, app_name):
        """获取应用实例（返回代理对象）"""
        app = self.app_dict.get(app_name, None)
        if app:
            return AppProxy(app, self)
        return None

    def _main_loop(self):
        """系统主循环，在后台线程中执行"""
        try:
            while self.power:
                time.sleep(0.01)
                pass
        except Exception as e:
            logging.critical(f'''抱歉，您的系统主循环由于遇到未处理的错误而崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
        finally:
            self._off()

    def run(self):
        try:
            self.power = True
            self.run_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
            logging.info(f'[系统] 系统于{self.run_time}启动')
            # 启动所有自动启动的应用
            for app, args, kwargs in self.app_autostartup:
                try:
                    app.run(*args, **kwargs)
                except Exception as e:
                    logging.error(f"[系统] 启动应用 {app.name} 时发生错误: {e}")
                finally:
                    continue
            # 创建并启动后台线程执行主循环
            main_loop_thread = threading.Thread(target=self._main_loop, daemon=True)
            main_loop_thread.start()
            # 启动REPL（如果启用）
            if self.enable_repl:
                code.interact(local={"self": self, "system": self})
            else:
                # 如果未启用REPL，主线程等待后台线程结束
                main_loop_thread.join()
        except KeyboardInterrupt:
            logging.warning("[系统] 用户中断程序")
        except Exception as e:
            logging.critical(f'''抱歉，您的系统由于在运行时遇到未处理的错误而导致崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
            sys.stderr.write(
                f'''抱歉，您的系统由于在运行时遇到未处理的错误而导致崩溃，以下是错误信息：\n{e}\n调用栈：\n{traceback.format_exc()}\n\n\n''')
        finally:
            self._off()
            pass

    def off(self):
        """外部应用触发系统关闭"""
        # if self.power:
        self.power = False
        logging.info(f"[系统] 已由应用设置系统关闭标志。")

    def _off(self):
        """系统内部触发系统关闭"""
        # if self.power:
        self.power = False
        # 卸载所有应用（调用系统内置的 uninstall_app 方法）
        for app_name in list(self.app_dict.keys()):
            self.uninstall_app(app_name)
        logging.info("[系统] 系统已关闭")

    @staticmethod
    def get_app_data_dir(app, absolute=False):
        """获取APP工作目录
        
        Args:
            app (BaseApp or AppProxy): 应用实例或应用代理实例
            absolute (bool): 是否返回绝对路径
            
        Returns:
            str: 应用工作目录路径
        """
        # 检查应用实例是否合法
        if hasattr(app, '_app'):  # 处理 AppProxy 实例
            app = app._app
        if not isinstance(app, BaseApp):
            raise TypeError("参数必须是BaseApp的实例或AppProxy的实例")
        
        # 构建相对路径
        app_data_dir = os.path.join(".", "System", "AppData", app.name)
        
        # 如果需要绝对路径，转换为绝对路径
        if absolute:
            app_data_dir = os.path.abspath(app_data_dir)
        
        # 确保目录存在
        if not os.path.exists(app_data_dir):
            os.makedirs(app_data_dir, exist_ok=True)
        
        return app_data_dir
    
    @staticmethod
    def get_app_install_dir(app, absolute=False):
        """获取APP安装目录
        
        Args:
            app (BaseApp or AppProxy): 应用实例或应用代理实例
            absolute (bool): 是否返回绝对路径
            
        Returns:
            str: 应用安装目录路径
        """
        # 检查应用实例是否合法
        if hasattr(app, '_app'):  # 处理 AppProxy 实例
            app = app._app
        if not isinstance(app, BaseApp):
            raise TypeError("参数必须是BaseApp的实例或AppProxy的实例")
        
        # 获取应用的模块路径
        module_path = app.__module__
        # 转换模块路径为文件系统路径
        # 例如：System.apps.client_MsgHandle.client_MsgHandle -> System/apps/client_MsgHandle
        parts = module_path.split('.')
        if len(parts) >= 3:
            # 构建目录路径（去掉最后一个部分，因为最后一个部分是文件名）
            app_install_dir = os.path.join(".", *parts[:-1])
        else:
            # 如果模块路径不符合预期，使用默认路径
            app_install_dir = os.path.join(".", "System", "apps", app.name)
        
        # 如果需要绝对路径，转换为绝对路径
        if absolute:
            app_install_dir = os.path.abspath(app_install_dir)
        
        return app_install_dir
    
    @staticmethod
    def get_app_file_path(app, absolute=False):
        """获取APP对应的文件路径
        
        Args:
            app (BaseApp or AppProxy): 应用实例或应用代理实例
            absolute (bool): 是否返回绝对路径
            
        Returns:
            str: 应用文件路径
        """
        # 检查应用实例是否合法
        if hasattr(app, '_app'):  # 处理 AppProxy 实例
            app = app._app
        if not isinstance(app, BaseApp):
            raise TypeError("参数必须是BaseApp的实例或AppProxy的实例")
        
        # 获取应用的模块路径
        module_path = app.__module__
        # 转换模块路径为文件系统路径
        # 例如：System.apps.client_MsgHandle.client_MsgHandle -> System/apps/client_MsgHandle/client_MsgHandle.py
        parts = module_path.split('.')
        if len(parts) >= 3:
            # 构建文件路径
            app_file_path = os.path.join(".", *parts) + ".py"
        else:
            # 如果模块路径不符合预期，使用默认路径
            app_file_path = os.path.join(".", "System", "apps", app.name, f"{app.name}.py")
        
        # 如果需要绝对路径，转换为绝对路径
        if absolute:
            app_file_path = os.path.abspath(app_file_path)
        
        return app_file_path

    def get_status(self):
        """获取系统状态"""
        apps_status = {name: app.get_status() for name, app in self.app_dict.items()}

        return {
            "device_name": self.device_name,
            "power": self.power,
            "run_time": self.run_time,
            "version": self.VERSION,
            "apps": apps_status
        }

# s = System()
# s.run()
