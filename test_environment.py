import sys
import tkinter
import selenium
import pyautogui

def test_imports():
    modules = {
        'tkinter': tkinter,
        'selenium': selenium,
        'pyautogui': pyautogui
    }
    
    print("Python 版本:", sys.version)
    print("\n已安装模块:")
    for name, module in modules.items():
        print(f"{name}: {module.__version__ if hasattr(module, '__version__') else '已安装'}")

if __name__ == "__main__":
    test_imports()
