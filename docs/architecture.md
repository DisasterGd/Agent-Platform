# 架构说明

```text
React + TypeScript
       | HTTP / SSE
       v
FastAPI routes
       v
Services (业务用例)
       +---- Agent Core / Model Adapters / Tools（后续加入）
       v
Repositories
       v
SQLAlchemy Session -> MySQL
```

约束：前端不访问数据库；路由层不堆复杂业务；Agent Core 不依赖 FastAPI Request/Response；
Repository 封装数据读写；Session 按请求创建和关闭；用户归属必须由服务端认证身份决定。
