from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect

from python_api_tests.config import BASE_URL, VALID_PASSWORD, VALID_PHONE


pytestmark = pytest.mark.ui


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
WRONG_PASSWORD = "Wrong123"


def _reset_login_failures():
    # 通过正确登录接口清理失败次数，避免错误密码用例多次执行导致账号锁定
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"phone": VALID_PHONE, "password": VALID_PASSWORD},
        timeout=5,
    )
    assert response.status_code == 200, f"登录失败次数复位失败，状态码={response.status_code}"


def test_ui_login_success(page: Page):
    # 失败时保存截图，方便定位页面状态
    try:
        page.goto(BASE_URL)
        page.evaluate("localStorage.removeItem('minimall_token')")
        page.reload()

        # 打开登录页并填写正确账号
        expect(page.get_by_role("heading", name="登录商城")).to_be_visible()
        page.get_by_placeholder("11 位手机号").fill(VALID_PHONE)
        page.get_by_placeholder("密码（6-20位）").fill(VALID_PASSWORD)

        # 点击登录，等待登录成功后的商品列表出现
        page.get_by_role("button", name="登录").click()
        expect(page.get_by_role("heading", name="商品列表")).to_be_visible()

        # 登录成功后页面应显示商品区域，且本地登录态应已写入
        expect(page.get_by_role("button", name="购物车", exact=True)).to_be_visible()
        assert page.evaluate("Boolean(localStorage.getItem('minimall_token'))")
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_login_success_failed.png"), full_page=True)
        raise


def test_ui_login_wrong_password_shows_error(page: Page):
    # 失败时保存截图，方便定位页面状态
    try:
        _reset_login_failures()

        page.goto(BASE_URL)
        page.evaluate("localStorage.removeItem('minimall_token')")
        page.reload()

        # 打开登录页并填写正确手机号、错误密码
        login_panel = page.locator("section.login")
        expect(login_panel.get_by_role("heading", name="登录商城", exact=True)).to_be_visible()
        login_panel.get_by_placeholder("11 位手机号").fill(VALID_PHONE)
        login_panel.get_by_placeholder("密码（6-20位）").fill(WRONG_PASSWORD)

        # 点击登录后，精确断言错误提示
        login_panel.get_by_role("button", name="登录", exact=True).click()
        error_message = page.locator("#tip .message")
        expect(error_message).to_have_text("手机号或密码错误")

        # 登录失败后不应进入商品列表，也不应写入登录态
        expect(page.get_by_role("heading", name="商品列表", exact=True)).not_to_be_visible()
        assert page.evaluate("localStorage.getItem('minimall_token')") is None
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_login_wrong_password_failed.png"), full_page=True)
        raise
    finally:
        _reset_login_failures()
