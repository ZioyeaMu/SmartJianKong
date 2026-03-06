import threading
import time
import logging
import webbrowser
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from System.core.base_app import BaseApp


class ClientWebApp(BaseApp):
    def __init__(self, system):
        super().__init__(system, "ClientWebApp", "1.0.0")
        self.app = FastAPI()
        self.server_thread = None
        self.host = "0.0.0.0"
        self.port = 5003
        # 构建web/dist路径
        self.web_dist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "dist")
        self.config_cors()
        self.config_static_files()
        self.config_routes()
    
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
                log_level="info"
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
