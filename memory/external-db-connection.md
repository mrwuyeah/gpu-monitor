---
name: external-db-connection
description: 公司内网 MySQL 数据库连接信息，用于替代 SQLite 接入生产数据库
metadata:
  type: reference
---

- **Host**: 10.70.19.243
- **Port**: 3306 (MySQL)
- **Identifier**: model-monitor/iVDbNxcRAU1A/CcD（可能是 database/user/password 的编码格式，待确认）
- **用途**: GPU 监控系统从本地 SQLite 迁移至集中式数据库，支持多机数据互通
