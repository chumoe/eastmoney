@echo off
REM 切换到 UTF-8 编码，解决中文乱码问题
chcp 65001 >nul
REM Build and export ARM64 image for Windows using Podman
REM 优化：使用分层缓存加速第二次构建

REM 设置镜像名称和版本
set IMAGE_NAME=eastmoney
set IMAGE_TAG=arm64
set FULL_IMAGE_NAME=%IMAGE_NAME%:%IMAGE_TAG%

REM 设置导出文件名
set EXPORT_FILE=eastmoney.tar

echo Building ARM64 image: %FULL_IMAGE_NAME%
echo.
echo 提示：第二次构建将自动使用缓存层加速
echo.

REM 使用 podman build 构建 arm64 架构镜像
REM --layers=true 启用分层缓存（默认已启用，显式指定确保生效）
REM 注：podman 默认自动使用本地镜像缓存，无需额外 --cache-from 参数
podman build --platform linux/arm64 ^
    --layers=true ^
    -t %FULL_IMAGE_NAME% ^
    .

if %errorlevel% neq 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo Build completed successfully!
echo.

REM 导出镜像为 tar 文件
echo Exporting image to %EXPORT_FILE%...
podman save -o %EXPORT_FILE% %FULL_IMAGE_NAME%

if %errorlevel% neq 0 (
    echo Export failed!
    pause
    exit /b 1
)

echo.
echo Export completed: %EXPORT_FILE%
echo.
echo Image size:
dir %EXPORT_FILE%
echo.
echo Done! You can load this image on ARM64 device with:
echo   podman load -i %EXPORT_FILE%
echo.
pause
