import pytest
import requests

from config import BASE_URL, VALID_PASSWORD, VALID_PHONE


pytestmark = pytest.mark.api


@pytest.mark.parametrize(
    "phone,password,expected_status,should_login_success",
    [
        # 正确手机号和正确密码，登录成功
        (VALID_PHONE, VALID_PASSWORD, 200, True),
        # 正确手机号和错误密码，登录失败
        (VALID_PHONE, "Wrong123", 401, False),
        # 正确手机号和空密码，参数校验失败
        (VALID_PHONE, "", 400, False),
        # 格式错误的手机号和正确密码，参数校验失败
        ("12345", VALID_PASSWORD, 400, False),
    ],
    ids=[
        "login_success",
        "wrong_password",
        "empty_password",
        "invalid_phone",
    ],
)
def test_login_returns_expected_response(phone, password, expected_status, should_login_success):
    # 准备登录接口地址和测试账号
    url = f"{BASE_URL}/api/auth/login"
    login_body = {
        "phone": phone,
        "password": password,
    }

    # 发送登录请求
    response = requests.post(url, json=login_body)

    # 断言 HTTP 状态码为 200
    assert response.status_code == expected_status

    # 断言响应内容可以被解析为 JSON
    response_json = response.json()

    if should_login_success:
        # 登录成功时断言 token 存在，且 token 是非空字符串
        assert "token" in response_json
        assert isinstance(response_json["token"], str)
        assert response_json["token"].strip() != ""
    else:
        # 登录失败时断言 message 存在，且 message 是非空字符串
        assert "message" in response_json
        assert isinstance(response_json["message"], str)
        assert response_json["message"].strip() != ""
