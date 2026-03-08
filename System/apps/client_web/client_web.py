import threading
import time
import logging
import webbrowser
import os
import zipfile
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from System.core.base_app import BaseApp
from System.system import System


class ClientWebApp(BaseApp):
    def __init__(self, system):
        super().__init__(system, "ClientWebApp", "1.1.0")
        self.app = FastAPI()
        self.server_thread = None
        self.host = "0.0.0.0"
        self.port = 5003
        
        # 获取应用工作目录
        self.app_data_dir = System.get_app_data_dir(self, absolute=True)
        # 构建工作目录下的web/dist路径
        self.web_dist_path = os.path.join(self.app_data_dir, "web", "dist")
        # 获取应用安装目录
        self.app_install_dir = System.get_app_install_dir(self, absolute=True)
        # 构建安装目录下的web压缩包路径
        self.web_zip_path = os.path.join(self.app_install_dir, "web.zip")
        
        # 检查工作目录下是否有web文件，如果没有就从安装目录解压
        self.check_and_extract_web_files()
        
        self.config_cors()
        self.config_static_files()
        self.config_routes()
    
    def check_and_extract_web_files(self):
        """检查工作目录下是否有web文件，如果没有就从安装目录解压，或者版本较旧则更新"""
        # 版本文件路径
        version_file_path = os.path.join(self.app_data_dir, "web_version.txt")
        
        # 检查是否需要更新静态文件
        need_update = False
        
        # 检查工作目录下的web/dist路径是否存在
        if not os.path.exists(self.web_dist_path):
            logging.info(f"[ClientWebApp] 工作目录下的web文件不存在，需要从安装目录解压")
            need_update = True
        else:
            # 检查版本文件是否存在
            if not os.path.exists(version_file_path):
                logging.info(f"[ClientWebApp] 工作目录下的版本文件不存在，需要更新web文件")
                need_update = True
            else:
                # 读取当前版本
                try:
                    with open(version_file_path, 'r', encoding='utf-8') as f:
                        current_version = f.read().strip()
                    # 比较版本
                    if current_version != self.version:
                        logging.info(f"[ClientWebApp] 工作目录下的web文件版本较旧 ({current_version})，需要更新到版本 {self.version}")
                        need_update = True
                    else:
                        logging.info(f"[ClientWebApp] 工作目录下的web文件版本已是最新 ({current_version})")
                except Exception as e:
                    logging.error(f"[ClientWebApp] 读取版本文件失败: {e}")
                    need_update = True
        
        # 如果需要更新静态文件
        if need_update:
            # 检查安装目录下的web压缩包是否存在
            if os.path.exists(self.web_zip_path):
                # 确保工作目录下的web目录存在
                os.makedirs(os.path.dirname(self.web_dist_path), exist_ok=True)
                
                # 删除旧的web文件（如果存在）
                if os.path.exists(self.web_dist_path):
                    import shutil
                    try:
                        shutil.rmtree(self.web_dist_path)
                        logging.info(f"[ClientWebApp] 已删除旧的web文件")
                    except Exception as e:
                        logging.error(f"[ClientWebApp] 删除旧的web文件失败: {e}")
                
                # 解压web压缩包到工作目录
                try:
                    with zipfile.ZipFile(self.web_zip_path, 'r') as zip_ref:
                        zip_ref.extractall(os.path.dirname(self.web_dist_path))
                    logging.info(f"[ClientWebApp] 成功从安装目录解压web文件到工作目录")
                    
                    # 写入版本文件
                    with open(version_file_path, 'w', encoding='utf-8') as f:
                        f.write(self.version)
                    logging.info(f"[ClientWebApp] 已更新版本文件为 {self.version}")
                except Exception as e:
                    logging.error(f"[ClientWebApp] 解压web文件失败: {e}")
            else:
                logging.error(f"[ClientWebApp] 安装目录下的web压缩包不存在: {self.web_zip_path}")
    
    def config_cors(self):
        """配置CORS中间件"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def config_static_files(self):
        """配置静态文件托管"""
        # 不再使用app.mount()，而是通过路由手动处理
        if os.path.exists(self.web_dist_path):
            logging.info(f"[ClientWebApp] 静态文件路径已配置，路径: {self.web_dist_path}")
        else:
            logging.error(f"[ClientWebApp] 静态文件路径不存在: {self.web_dist_path}")
    
    def config_routes(self):
        """配置API路由"""
        # 根路径，返回index.html
        @self.app.get("/")
        async def root():
            """根路径，返回index.html"""
            index_path = os.path.join(self.web_dist_path, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            else:
                return {"error": "index.html not found"}
        
        # 捕获所有其他路由，返回index.html，支持前端SPA路由
        @self.app.get("/{full_path:path}")
        async def catch_all(full_path: str):
            """捕获所有路由，返回index.html，支持前端SPA路由"""
            # 检查请求的路径是否对应一个实际存在的文件
            requested_path = os.path.join(self.web_dist_path, full_path)
            if os.path.exists(requested_path) and os.path.isfile(requested_path):
                # 如果是实际存在的文件，返回该文件
                return FileResponse(requested_path)
            else:
                # 否则返回index.html，让前端路由处理
                index_path = os.path.join(self.web_dist_path, "index.html")
                if os.path.exists(index_path):
                    return FileResponse(index_path)
                else:
                    return {"error": "index.html not found"}
    
    def _main(self, *args, **kwargs):
        """应用主循环"""
        # 检查web/dist路径是否存在
        if not os.path.exists(self.web_dist_path):
            logging.error(f"[ClientWebApp] 静态文件路径不存在: {self.web_dist_path}")
            return
        
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
        
        logging.info(f"[ClientWebApp] 服务器已启动，监听 {self.host}:{self.port}")
        
        # 自动打开浏览器
        time.sleep(1)  # 等待服务器启动
        browser_url = f"http://localhost:{self.port}"
        logging.info(f"[ClientWebApp] 正在打开浏览器: {browser_url}")
        webbrowser.open(browser_url)
        
        # 保持应用运行
        while self.running:
            time.sleep(0.1)
    
    def _reset(self):
        """重置应用"""
        if self.server_thread and self.server_thread.is_alive():
            # 注意：uvicorn的服务器线程可能需要特殊处理来停止
            pass
        logging.info(f"[{self.name}] 应用已重置")
    
    def stop(self):
        """停止应用"""
        super().stop()
