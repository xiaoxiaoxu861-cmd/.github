import pytest
import requests

from config import BASE_URL


pytestmark = pytest.mark.api


def test_auth_headers_can_access_cart(auth_headers):
    # 使用 fixture 提供的 Authorization 请求头访问登录后接口
    response = requests.get(f"{BASE_URL}/api/cart", headers=auth_headers)

    # 断言接口访问成功
    assert response.status_code == 200

    # 断言响应内容可以被解析为 JSON
    response_json = response.json()

    # 断言没有返回未登录或 Token 无效类错误
    message = response_json.get("message", "")
    assert "未登录" not in message
    assert "Token无效" not in message
