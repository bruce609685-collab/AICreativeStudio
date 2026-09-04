"""测试目录：headless 层全部可自动化测试，不需要 GUI 渲染。

各测试文件按被测模块划分：
  test_smoke.py     冒烟测试（模块导入 + 主窗口装配 + 注册表加载）
  test_registry.py  脚本注册表（ACS_META 解析 / 扫描 / 分类索引）
  test_importer.py  智能导入管线（完备性门闸 / mock 链路 / 流式输出）
  test_keys.py      API KEY 注入与读取
  test_deps.py      依赖检测与安装（pip / FFmpeg）
  test_history_db.py 历史记录数据库
  test_script_grok.py / test_script_av.py  样例脚本 mock 链路验证
  screenshot.py     界面走查截图（offscreen 渲染六页签）

运行方式：QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
"""
