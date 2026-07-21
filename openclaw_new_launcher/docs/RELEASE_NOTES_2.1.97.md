# LOOM 2.1.97 更新说明

## 安装升级热修

- 修复低页面文件环境下直接覆盖安装时，`_up_` 内 Node/Python 仍被占用的问题。
- 安装器不再依赖 WMI/CIM 发现麓鸣进程，避免 `ERROR_COMMITMENT_LIMIT` 导致漏检。
- 优先停止当前安装目录中的 LOOM 父进程树；系统 `taskkill` 失败时自动降级为直接终止。
- 覆盖文件前连续五次确认没有麓鸣进程，并验证 LOOM、Node、Python 文件可独占打开。
- 仅处理当前安装根目录内的进程，不按 `node.exe`、`python.exe` 等全局进程名结束任务。
- 新增 `%TEMP%\LOOM-installer-process-cleanup.log`，安装失败时可直接查看清理证据。

## 现场验证

- 安装路径：`D:\LOOM\Luming AI Matrix Acquisition Workbench`。
- 启动完整 LOOM、Python、Node 后执行覆盖安装。
- 现场 `taskkill` 因“页面文件太小”失败，备用终止链成功停止三个进程并完成安装。
- 全新安装、升级数据保留和保护资源运行时烟测通过。
- 安装/更新专项：42 passed。

安装包：`Luming AI Matrix Acquisition Workbench_2.1.97_x64-setup.exe`

大小：257,713,028 字节（245.77 MiB）

SHA256：`1382E9788173B718AD66B482F94CBE52D1405DF9DA738F78DDABC5C556B6B14F`
