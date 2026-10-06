@echo off
echo 运行此脚本之前，先安装python 3.10.10(建议版本)
echo 初次使用该软件，只需运行一次脚本，虚拟环境创建成功后都不在需要运行此脚本
echo 虚拟环境创建成功后，会在脚本目录下生成.venv文件夹
echo 创建虚拟环境时请勿关闭窗口，耐心稍等片刻...
echo.

:: 等待用户按任意键后再开始执行
echo 请按任意键开始创建虚拟环境...
pause >nul  :: 静默等待，不显示默认提示文字

:: 步骤1 ：获取当前脚本所在目录（即存放脚本的路径）
set "script_dir=%~dp0"

::: 步骤2：创建虚拟环境
call python -m venv .venv || (
    echo 错误：虚拟环境激活失败
    pause
    exit /b 1
)
echo 虚拟环境激活成功

:: 步骤3：激活虚拟环境
if not exist ".venv\Scripts\activate.bat" (
    echo 错误：未找到虚拟环境激活文件，请确认.venv目录存在
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat || (
    echo 错误：虚拟环境激活失败
    pause
    exit /b 1
)
echo 虚拟环境创建成功且已激活
echo 准备安装项目所需依赖...



:: 步骤4：切换回脚本所在目录（程序运行目录）
cd /d "%script_dir%" || (
    echo 错误：无法切换回程序运行目录，请检查路径是否正确
    pause
    exit /b 1
)
echo 已切换到脚本所在目录：%cd%

::: 步骤5：更新最新版本pip
call python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple || (
    echo 错误：安装失败
    pause
    exit /b 1
)

::: 步骤6：依赖安装
call pip install -i https://pypi.tuna.tsinghua.edu.cn/simple openai || (
    echo 错误：安装失败
    pause
    exit /b 1
)

::: 步骤7：依赖安装
call pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller || (
    echo 错误：安装失败
    pause
    exit /b 1
)
::: 步骤：全部依赖清单
call pip list || (
    echo 错误：安装失败
    pause
    exit /b 1
)

:: 提示用户可以进行手动操作
echo.
echo =====================================================================================
echo 软件所需依赖已全部安装完毕 ，上面是该虚拟环境的全部库列表清单
echo 虚拟环境创建成功且已激活，可以准备使用注音标注软件了
echo 输入 exit 按Enter或鼠标点击“X”退出当前环境
echo 进到“Local_Ruby”文件，点击"自动开始X语标注.bat",按提示一步步操作即可
echo =====================================================================================
echo.

:: 启动命令行
cmd /k    


