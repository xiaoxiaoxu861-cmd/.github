from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from python_api_tests.config import BASE_URL, VALID_PASSWORD, VALID_PHONE


pytestmark = pytest.mark.ui


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
NOT_EXIST_KEYWORD = "ui_test_not_exist_987654"


def _login_by_page(page: Page):
    # 通过页面完成登录，不直接写入 Token
    page.goto(BASE_URL)
    page.evaluate("localStorage.removeItem('minimall_token')")
    page.reload()

    login_panel = page.locator("section.login")
    expect(login_panel.get_by_role("heading", name="登录商城", exact=True)).to_be_visible()
    login_panel.get_by_placeholder("11 位手机号").fill(VALID_PHONE)
    login_panel.get_by_placeholder("密码（6-20位）").fill(VALID_PASSWORD)
    login_panel.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_role("heading", name="商品列表", exact=True)).to_be_visible()


def _product_panel(page: Page):
    # 锁定商品列表面板，避免定位到其他页面元素
    return page.locator("section.panel").filter(
        has=page.get_by_role("heading", name="商品列表", exact=True)
    )


def _product_cards(page: Page):
    return _product_panel(page).locator(".products article.card")


def test_ui_search_existing_product_shows_matching_results(page: Page):
    # 失败时保存截图，方便定位页面状态
    try:
        _login_by_page(page)

        # 从页面真实商品卡片中读取第一个商品名称作为搜索关键词
        cards = _product_cards(page)
        expect(cards.first).to_be_visible()
        keyword = cards.first.get_by_role("heading").inner_text()
        assert keyword.strip() != ""

        # 输入关键词并点击搜索
        panel = _product_panel(page)
        panel.get_by_placeholder("搜索商品名称").fill(keyword)
        panel.get_by_role("button", name="搜索", exact=True).click()

        # 断言至少显示一个商品，且每个结果名称都包含关键词
        result_cards = _product_cards(page)
        expect(result_cards.first).to_be_visible()
        result_headings = result_cards.get_by_role("heading")
        result_names = result_headings.all_inner_texts()
        assert len(result_names) >= 1, f"搜索后没有返回商品结果，关键词={keyword}"
        for product_name in result_names:
            assert keyword in product_name, f"搜索结果商品名称不包含关键词，关键词={keyword}，商品名={product_name}"
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_search_existing_product_failed.png"), full_page=True)
        raise


def test_ui_search_not_existing_product_shows_empty_message(page: Page):
    # 失败时保存截图，方便定位页面状态
    try:
        _login_by_page(page)

        # 搜索一个确定不存在的关键词
        panel = _product_panel(page)
        panel.get_by_placeholder("搜索商品名称").fill(NOT_EXIST_KEYWORD)
        panel.get_by_role("button", name="搜索", exact=True).click()

        # 断言出现无结果提示，且没有商品卡片
        products_area = panel.locator(".products")
        expect(products_area.get_by_text("未找到商品", exact=True)).to_be_visible()
        expect(products_area.locator("article.card")).to_have_count(0)
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_search_not_existing_product_failed.png"), full_page=True)
        raise
