
# 更新日记

---

## [2.3.8] - 2026-03-08

### Added
- **系统功能增强**：
  - 新增 `get_app_install_dir` 方法，支持获取应用安装目录的相对路径和绝对路径，便于应用储存预置资源，安装时解压到工作目录。
  - 新增 `get_app_file_path` 方法，支持获取应用文件路径的相对路径和绝对路径。
  - 将 `BaseApp` 中的相关方法改为静态函数，提高代码灵活性。
  - 建立应用资源和数据的分离标准：预置资源位于安装目录，运行时数据存放于工作目录。

- **ClientWebApp 增强**：
  - 添加检查和提取 Web 文件的功能，当工作目录中缺少 Web 文件时自动从安装目录解压。
  - 添加版本检查和更新机制，确保 WebApp 升级时静态文件同步更新。

### Changed
- **系统功能**：
  - 修改 `get_app_data_dir` 方法，使其与其他方法保持一致：应用运行时数据统一存放在其工作目录下（成为新标准）。
  - 将 `get_app_install_dir`、`get_app_file_path` 等方法改为静态函数（原为实例方法）。

- **应用标准化**：
  - 将所有应用移入各自独立的文件夹，便于管理和隔离。

- **ClientWebApp 优化**：
  - 修改静态文件路径，使其优先从工作目录读取。

### Fixed
- **BaseApp**：修复 `BaseApp` 导入路径问题，确保 `isinstance` 检查正常工作。
- **STP 应用**：
  - 修复哈希校验禁用后连接不通过的问题：修改 `connect_net` 方法，在哈希校验禁用时直接进入 stage 1。
  - 修复 `broadcast_msg` 方法中的导入错误，将 `from System.apps.STP import Msg` 改为相对导入 `from .STP import Msg`。

### Documentation
- **FastAPI 日志**：
  - 查看并分析 Uvicorn 日志配置，解释为何 500 错误会以 INFO 级别记录。