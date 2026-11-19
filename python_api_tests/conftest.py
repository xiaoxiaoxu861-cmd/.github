import os

import pymysql
import pytest
import requests
from pymysql.cursors import DictCursor

from config import BASE_URL, VALID_PASSWORD, VALID_PHONE


class SafeAuthHeaders(dict):
    # 避免 pytest 失败输出中展示完整 Token
    def __repr__(self):
        return "{'Authorization': 'Bearer ***'}"


@pytest.fixture(scope="session")
def auth_headers():
    # 会话级 fixture：整次测试会话只登录一次
    login_url = f"{BASE_URL}/api/auth/login"
    login_body = {
        "phone": VALID_PHONE,
        "password": VALID_PASSWORD,
    }

    # 调用真实登录接口获取 token
    response = requests.post(login_url, json=login_body)
    assert response.status_code == 200

    response_json = response.json()
    token = response_json.get("token")

    # 验证 token 存在且不是空字符串
    assert isinstance(token, str)
    assert token.strip() != ""

    # 返回后续接口测试可直接复用的认证请求头
    return SafeAuthHeaders({"Authorization": f"Bearer {token}"})
   # return {"Authorization": "Bearer invalid_token"}


@pytest.fixture
def db_connection():
    # 从项目 .env 或系统环境变量读取数据库连接信息
    required_keys = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing_keys = [key for key in required_keys if key not in os.environ]
    if missing_keys:
        raise AssertionError(
            "数据库测试缺少环境变量，请在 .env 或系统环境变量中配置："
            + ", ".join(missing_keys)
            + "。不会猜测数据库密码。"
        )

    db_host = os.getenv("DB_HOST")
    db_port = int(os.getenv("DB_PORT"))
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD", "")

    try:
        connection = pymysql.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name,
            cursorclass=DictCursor,
            autocommit=True,
        )
    except pymysql.MySQLError as exc:
        raise AssertionError(
            f"MySQL 连接失败，host={db_host}，port={db_port}，database={db_name}，user={db_user}，错误={exc.__class__.__name__}"
        ) from exc

    try:
        yield connection
    finally:
        connection.close()
