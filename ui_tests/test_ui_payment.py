from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect

from python_api_tests.config import BASE_URL, TIMEOUT
from ui_tests.test_ui_cart import (
    _auth_headers_from_page,
    _find_cart_item,
    _get_cart,
    _get_products,
    _parse_json,
)
from ui_tests.test_ui_order import (
    _cancel_order_by_api,
    _click_and_accept_dialog,
    _order_card_by_order_no,
    _patch_cart_item,
    _restore_cart,
)
from ui_tests.test_ui_product_search import _login_by_page


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
pytestmark = pytest.mark.ui


def _choose_payment_product(original_cart):
    # 优先选择原购物车中不存在的有库存商品，避免测试后恢复用户原购物车时受已支付订单扣库存影响
    cart_quantities = {
        item["productId"]: item.get("quantity", 0)
        for item in original_cart["items"]
    }
    products = _get_products()

    for product in products:
        if product.get("stock", 0) > 0 and product.get("id") not in cart_quantities:
            return product

    # 如果所有有库存商品都已在购物车中，则选择库存足够恢复原数量的商品
    for product in products:
        product_id = product.get("id")
        original_quantity = cart_quantities.get(product_id, 0)
        if product.get("stock", 0) >= original_quantity * 2 + 1:
            return product

    raise AssertionError(f"没有找到适合创建已支付订单且可恢复购物车的商品，购物车={original_cart['items']}")


def _get_order_detail(auth_headers, order_id):
    # 通过接口查询订单详情，用于和页面状态互相校验
    response = requests.get(
        f"{BASE_URL}/api/orders/{order_id}",
        headers=auth_headers,
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"查询订单详情失败，状态码={response.status_code}，响应={response.text}"
    return _parse_json(response)


def _prepare_pending_order(auth_headers):
    # 通过真实接口准备一个本测试专用的 PENDING 订单
    original_cart = _get_cart(auth_headers)

    # 取消用户原有已选商品，确保本次订单只包含测试商品
    for item in original_cart["items"]:
        if item.get("selected"):
            _patch_cart_item(auth_headers, item["id"], {"selected": False})

    target_product = _choose_payment_product(original_cart)
    add_response = requests.post(
        f"{BASE_URL}/api/cart",
        headers=auth_headers,
        json={"productId": target_product["id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert add_response.status_code == 201, (
        f"准备购物车商品失败，状态码={add_response.status_code}，响应={add_response.text}"
    )

    latest_cart = _get_cart(auth_headers)
    target_item = _find_cart_item(latest_cart["items"], target_product["id"])
    assert target_item is not None, f"添加商品后购物车中未找到目标商品，productId={target_product['id']}，购物车={latest_cart}"

    # 如果商品原本就在购物车且未选中，重复添加只会增加数量，因此这里显式选中目标行
    _patch_cart_item(auth_headers, target_item["id"], {"selected": True})

    create_response = requests.post(
        f"{BASE_URL}/api/orders",
        headers=auth_headers,
        json={},
        timeout=TIMEOUT,
    )
    assert create_response.status_code == 201, (
        f"创建测试订单失败，状态码={create_response.status_code}，响应={create_response.text}"
    )
    create_json = _parse_json(create_response)
    order_id = create_json.get("id")
    assert isinstance(order_id, int) and order_id > 0, f"创建订单响应缺少有效 orderId，响应={create_json}"

    # 以后端订单详情为准获取真实持久化 orderNo，避免依赖创建响应中的展示值
    order_detail = _get_order_detail(auth_headers, order_id)
    order_no = order_detail.get("orderNo")
    assert isinstance(order_no, str) and order_no.strip() != "", f"订单详情缺少有效 orderNo，响应={order_detail}"
    assert order_detail.get("status") == "PENDING", f"新建订单状态不是 PENDING，响应={order_detail}"

    return original_cart, order_id, order_no


def _open_orders_page(page: Page):
    # 点击顶部“我的订单”，并等待真实订单列表接口返回
    with page.expect_response(
        lambda response: response.url.endswith("/api/orders") and response.request.method == "GET"
    ):
        page.get_by_role("button", name="我的订单", exact=True).click()
    expect(page.get_by_role("heading", name="我的订单", exact=True)).to_be_visible()


def _pay_from_ui(page: Page, order_id, order_card, button_name):
    # 点击当前订单卡片内的支付按钮，同时捕获真实支付接口响应和一次弹窗
    pay_button = order_card.get_by_role("button", name=button_name, exact=True)
    expect(pay_button).to_have_count(1)
    expect(pay_button).to_be_visible()

    with page.expect_response(
        lambda response: response.url.endswith("/api/orders") and response.request.method == "GET"
    ):
        with page.expect_response(
            lambda response: response.url.endswith(f"/api/orders/{order_id}/pay")
            and response.request.method == "POST"
        ) as pay_response_info:
            message = _click_and_accept_dialog(page, pay_button)

    return pay_response_info.value, message


def test_ui_order_payment_status_flow(page: Page):
    auth_headers = None
    original_cart = None
    order_id = None
    order_no = None
    order_was_paid = False

    try:
        # 通过页面登录，后续 API 辅助操作复用页面中的 Token，不打印 Token
        _login_by_page(page)
        auth_headers = _auth_headers_from_page(page)

        # 使用真实接口准备本次测试专用 PENDING 订单
        original_cart, order_id, order_no = _prepare_pending_order(auth_headers)

        # 进入我的订单，并用动态真实 orderNo 精确定位本次订单
        _open_orders_page(page)
        order_card = _order_card_by_order_no(page, order_no)
        expect(order_card).to_have_count(1)
        expect(order_card).to_be_visible()

        # A. 新订单应为待支付，接口 paidAt 应为空
        expect(order_card.locator(".status")).to_have_text("待支付")
        detail_before_pay = _get_order_detail(auth_headers, order_id)
        assert detail_before_pay.get("status") == "PENDING", f"支付前接口状态不符合预期，响应={detail_before_pay}"
        assert detail_before_pay.get("paidAt") is None, f"支付前 paidAt 应为空，响应={detail_before_pay}"

        # B/C. 通过 UI 模拟支付失败，并确认页面和接口状态仍为 PENDING
        fail_response, fail_message = _pay_from_ui(page, order_id, order_card, "模拟支付失败")
        assert fail_response.status == 200, f"支付失败接口状态码不符合预期，实际={fail_response.status}"
        assert "支付失败" in fail_message, f"支付失败弹窗提示不符合预期，实际={fail_message}"

        order_card = _order_card_by_order_no(page, order_no)
        expect(order_card).to_have_count(1)
        expect(order_card.locator(".status")).to_have_text("待支付")
        detail_after_fail = _get_order_detail(auth_headers, order_id)
        assert detail_after_fail.get("status") == "PENDING", f"支付失败后状态不应改变，响应={detail_after_fail}"
        assert detail_after_fail.get("paidAt") is None, f"支付失败后 paidAt 应仍为空，响应={detail_after_fail}"

        # D/E. 通过 UI 模拟支付成功，并保存第一次 paidAt
        success_response, success_message = _pay_from_ui(page, order_id, order_card, "模拟支付成功")
        assert success_response.status == 200, f"支付成功接口状态码不符合预期，实际={success_response.status}"
        assert "支付成功" in success_message, f"支付成功弹窗提示不符合预期，实际={success_message}"
        order_was_paid = True

        paid_order_card = _order_card_by_order_no(page, order_no)
        expect(paid_order_card).to_have_count(1)
        expect(paid_order_card.locator(".status")).to_have_text("已支付")
        detail_after_success = _get_order_detail(auth_headers, order_id)
        assert detail_after_success.get("status") == "PAID", f"支付成功后接口状态不是 PAID，响应={detail_after_success}"
        first_paid_at = detail_after_success.get("paidAt")
        assert first_paid_at is not None and str(first_paid_at).strip() != "", (
            f"支付成功后 paidAt 应为非空，响应={detail_after_success}"
        )

        # F/G. 已支付订单正常应隐藏支付按钮；若页面仍暴露按钮，则验证重复支付被后端拒绝
        repeat_success_button = paid_order_card.get_by_role("button", name="模拟支付成功", exact=True)
        repeat_fail_button = paid_order_card.get_by_role("button", name="模拟支付失败", exact=True)
        if repeat_success_button.count() == 0 and repeat_fail_button.count() == 0:
            expect(repeat_success_button).to_have_count(0)
            expect(repeat_fail_button).to_have_count(0)
        elif repeat_success_button.count() > 0 and not repeat_success_button.is_enabled():
            expect(repeat_success_button).to_be_disabled()
        else:
            expect(repeat_success_button).to_be_visible()
            with page.expect_response(
                lambda response: response.url.endswith(f"/api/orders/{order_id}/pay")
                and response.request.method == "POST"
            ) as repeat_response_info:
                repeat_message = _click_and_accept_dialog(page, repeat_success_button)
            repeat_response = repeat_response_info.value
            assert repeat_response.status == 400, f"重复支付应被拒绝，实际状态码={repeat_response.status}"
            assert "订单已支付" in repeat_message, f"重复支付弹窗提示不符合预期，实际={repeat_message}"

        final_detail = _get_order_detail(auth_headers, order_id)
        assert final_detail.get("status") == "PAID", f"重复支付检查后订单应保持 PAID，响应={final_detail}"
        assert final_detail.get("paidAt") == first_paid_at, (
            f"重复支付检查后 paidAt 不应变化，首次={first_paid_at}，最终响应={final_detail}"
        )
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_order_payment_status_flow_failed.png"), full_page=True)
        raise
    finally:
        # PENDING 订单可以取消；PAID 订单不能取消，本测试成功支付后会保留一条已支付测试订单
        if auth_headers is not None and order_id is not None and not order_was_paid:
            _cancel_order_by_api(auth_headers, order_id)

        if auth_headers is not None and original_cart is not None:
            _restore_cart(auth_headers, original_cart)
