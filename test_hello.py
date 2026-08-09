# -*- coding: utf-8 -*-
"""assistant5 测试脚本"""


def hello(name: str = "World") -> str:
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    print(hello())
    print(f"1 + 2 = {add(1, 2)}")
    print("assistant5 测试通过！")
