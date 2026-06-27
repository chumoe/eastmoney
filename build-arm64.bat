@echo off
REM Build and export ARM64 image for Windows using Podman

REM 设置镜像名称和版本
set IMAGE_NAME=eastmoney
set IMAGE_TAG=arm64
set FULL_IMAGE_NAME=%IMAGE_NAME%:%IMAGE_TAG%

REM 设置导出文件名
set EXPORT_FILE=eastmoney.tar

echo Building ARM64 image: %FULL_IMAGE_NAME%
echo.

REM 使用 podman buildx 构建 amd64 架构镜像
podman buildx build --platform linux/amd64 ^
    -t %FULL_IMAGE_NAME% ^
    -f Dockerfile ^
    --load ^
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
