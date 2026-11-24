"""示例：一个最小的 Axon 控制器，Shell 里的编辑区打开的就是它。"""

from axon import AxonController


@AxonController("ShellDemo", id="Demo")
class DemoController:
    count = 0

    def ping(self, name: str = "world") -> str:
        self.count += 1
        return f"pong {name} #{self.count}"

    async def slow(self, ms: int = 500) -> str:
        import asyncio

        await asyncio.sleep(ms / 1000)
        return f"slept {ms}ms"
