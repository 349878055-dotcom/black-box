"""
skill（平台逆向 API）包。

每个 skill = 一个 *_api.py：requests 直调 HTTP 接口，返回结构化 dict/list（AI 可直接读）。
registry.py 提供 skill_list / skill_run 给主代理。
"""
