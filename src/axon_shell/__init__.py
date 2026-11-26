"""axon-shell —— 给 Axon 应用一层可复用的「桌面应用外观」。

它不是框架核心：`axon-gui` 只管通道与窗口基类，这个包只提供
「VSCode 那种观感」需要的两半——Python 侧的无边框窗口，以及前端皮肤。
"""

from .window import AxonShellWindow, AxonWindow, WindowBridge, assets_dir

__all__ = ["AxonShellWindow", "AxonWindow", "WindowBridge", "assets_dir"]
__version__ = "0.3.0"
