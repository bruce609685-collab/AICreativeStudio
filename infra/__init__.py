"""基础设施层（headless，所有 I/O 边界）。

infra（infrastructure，基础设施）层负责一切"程序与外部世界打交道"
的工作：读写磁盘文件、访问数据库、下载网络资源等（统称 I/O）。
把这类操作集中在这一层，好处是：业务逻辑（domain/contract/core）
不必关心数据存在哪里、用什么网络库；将来更换存储方式或网络库，
只需修改本层，其他层不受影响。

子包：persistence（SQLite/JSON 存储）、media（产物下载/缩略图）、net（HTTP 封装）。
存储切换、网络库替换都只动本包，不污染业务层 stack trace。
"""
