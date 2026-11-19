from decimal import Decimal
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect

from python_api_tests.config import BASE_URL, TIMEOUT
from ui_tests.test_ui_product_search import _login_by_page, _product_cards


pytestmark = pytest.mark.ui


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


def _parse_json(response):
    # 统一解析 JSON，失败时给出清楚响应
    try:
        return response.json()
    except ValueError as exc:
        raise AssertionError(f"响应不是 JSON，状态码={response.status_code}，内容={response.text}") from exc


def _auth_headers_from_page(page: Page):
    # 从页面登录态中读取 Token，只用于 API 辅助查询和清理，不打印 Token
    token = page.evaluate("localStorage.getItem('minimall_token')")
    assert isinstance(token, str) and token.strip() != ""
    return {"Authorization": f"Bearer {token}"}


def _get_products():
    # 查询真实商品列表，用库存挑选目标商品
    response = requests.get(f"{BASE_URL}/api/products", timeout=TIMEOUT)
    assert response.status_code == 200, f"查询商品失败，状态码={response.status_code}，响应={response.text}"
    products = _parse_json(response)
    assert isinstance(products, list), f"商品列表响应不是列表，响应={products}"
    return products


def _get_cart(auth_headers):
    # 查询当前用户购物车
    response = requests.get(f"{BASE_URL}/api/cart", headers=auth_headers, timeout=TIMEOUT)
    assert response.status_code == 200, f"查询购物车失败，状态码={response.status_code}，响应={response.text}"
    cart_json = _parse_json(response)
    assert isinstance(cart_json.get("items"), list), f"购物车 items 不是列表，响应={cart_json}"
    return cart_json


def _find_cart_item(cart_items, product_id):
    # 按商品 ID 查找购物车行
    return next((item for item in cart_items if item.get("productId") == product_id), None)


def _choose_addable_product(cart_items):
    # 选择真实存在且当前还能继续加入购物车的有库存商品
    cart_quantities = {
        item.get("productId"): item.get("quantity", 0)
        for item in cart_items
    }
    for product in _get_products():
        product_id = product.get("id")
        stock = product.get("stock", 0)
        current_quantity = cart_quantities.get(product_id, 0)
        if stock > 0 and current_quantity < stock:
            return product

    raise AssertionError(f"没有找到可通过 UI 加入购物车的商品，购物车={cart_items}")


def _parse_money(text):
    # 将“单价 ¥89.90”这类文本转换为 Decimal
    amount_text = text.split("¥")[-1].strip()
    return Decimal(amount_text)


def _restore_cart_item(auth_headers, product_id, original_item):
    # 通过真实接口恢复目标商品在购物车中的原始状态
    latest_cart = _get_cart(auth_headers)
    latest_item = _find_cart_item(latest_cart["items"], product_id)
    if latest_item is None:
        return

    if original_item is None:
        response = requests.delete(
            f"{BASE_URL}/api/cart/{latest_item['id']}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert response.status_code == 200, f"删除测试新增购物车项失败，状态码={response.status_code}，响应={response.text}"
        return

    response = requests.patch(
        f"{BASE_URL}/api/cart/{latest_item['id']}",
        headers=auth_headers,
        json={"quantity": original_item["quantity"], "selected": bool(original_item["selected"])},
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"恢复购物车数量失败，状态码={response.status_code}，响应={response.text}"


def test_ui_add_product_to_cart_full_flow(page: Page):
    auth_headers = None
    target_product = None
    original_item = None

    try:
        # 通过页面正常登录
        _login_by_page(page)
        auth_headers = _auth_headers_from_page(page)

        # 通过 API 辅助记录添加前购物车数量
        original_cart = _get_cart(auth_headers)
        target_product = _choose_addable_product(original_cart["items"])
        original_item = _find_cart_item(original_cart["items"], target_product["id"])
        original_quantity = original_item["quantity"] if original_item else 0
        product_name = target_product["name"]

        # 使用商品 ID 对应的 onclick 精确定位“加入购物车”按钮
        target_product_id = target_product["id"]
        add_button = page.locator(f'button[onclick="add({target_product_id})"]')
        expect(add_button).to_have_count(1)
        expect(add_button).to_be_visible()
        with page.expect_event("dialog") as dialog_info:
            add_button.click()
        dialog = dialog_info.value
        assert dialog.message == "已加入购物车", f"加入购物车弹窗提示不符合预期，实际={dialog.message}"
        dialog.accept()

        # 点击顶部精确匹配的“购物车”按钮
        page.get_by_role("button", name="购物车", exact=True).click()
        cart_panel = page.locator("section.panel").filter(
            has=page.get_by_role("heading", name="购物车", exact=True)
        )
        expect(cart_panel).to_be_visible()

        # 断言购物车中出现刚才选择的商品
        cart_row = cart_panel.locator("article.card").filter(
            has=page.get_by_text(product_name, exact=True)
        )
        expect(cart_row).to_have_count(1)
        expect(cart_row).to_be_visible()

        # 断言数量增加 1
        quantity = int(cart_row.first.locator("input[type='number']").input_value())
        assert quantity == original_quantity + 1, (
            f"购物车数量未增加 1，商品={product_name}，添加前={original_quantity}，添加后={quantity}"
        )

        # 断言小计等于单价乘以数量
        unit_price = _parse_money(cart_row.first.locator("span").filter(has_text="单价").inner_text())
        subtotal = _parse_money(cart_row.first.locator("span").filter(has_text="小计").inner_text())
        assert subtotal == unit_price * quantity, (
            f"购物车小计不正确，商品={product_name}，单价={unit_price}，数量={quantity}，小计={subtotal}"
        )
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_add_product_to_cart_full_flow_failed.png"), full_page=True)
        raise
    finally:
        # 测试结束后恢复目标商品购物车状态，保证用例可重复运行
        if auth_headers is not None and target_product is not None:
            _restore_cart_item(auth_headers, target_product["id"], original_item)
