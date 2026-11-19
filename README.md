# .github
**CI状态：**
<img width="375" height="32" alt="image" src="https://github.com/user-attachments/assets/106ffef2-2e62-4619-a4a0-df0e851250e0" />
<img width="700" height="206" alt="image" src="https://github.com/user-attachments/assets/836e6473-467c-487d-8449-49fafd48235f" />


**项目说明：**
本项目采用 GitHub Actions 进行持续集成。每次代码提交将自动拉起环境，执行核心接口自动化用例（8条），确保主干代码质量。由于 UI 自动化耗时较长且有环境依赖，本地维护，不纳入高频 CI 触发流程。

**特殊说明：**
test_order_database.py
**→**
数据库校验用例因为依赖真实 MySQL 环境，故在本地手动执行，结果为 16 passed。
