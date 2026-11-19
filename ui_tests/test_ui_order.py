import re
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, expect

from python_api_tests.config import BASE_URL, TIMEOUT
from ui_tests.test_ui_cart import (
    _auth_headers_from_page,
    _choose_addable_product,
    _find_cart_item,
    _get_cart,
    _parse_json,
)
from ui_tests.test_ui_product_search import _login_by_page


SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
pytestmark = pytest.mark.ui


def _patch_cart_item(auth_headers, cart_id, body):
    # 通过 API 辅助设置购物车状态，避免用户原有选中商品影响本次订单
    response = requests.patch(
        f"{BASE_URL}/api/cart/{cart_id}",
        headers=auth_headers,
        json=body,
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"修改购物车失败，状态码={response.status_code}，响应={response.text}"
    return _parse_json(response)


def _restore_cart(auth_headers, original_cart):
    # 测试结束后恢复购物车快照，不删除用户原有商品
    latest_cart = _get_cart(auth_headers)
    original_by_product = {
        item["productId"]: item
        for item in original_cart["items"]
    }

    for latest_item in latest_cart["items"]:
        if latest_item["productId"] not in original_by_product:
            delete_response = requests.delete(
                f"{BASE_URL}/api/cart/{latest_item['id']}",
                headers=auth_headers,
                timeout=TIMEOUT,
            )
            assert delete_response.status_code == 200, (
                f"删除测试新增购物车项失败，状态码={delete_response.status_code}，响应={delete_response.text}"
            )

    latest_cart = _get_cart(auth_headers)
    latest_by_product = {
        item["productId"]: item
        for item in latest_cart["items"]
    }

    for product_id, original_item in original_by_product.items():
        latest_item = latest_by_product.get(product_id)
        if latest_item is None:
            add_response = requests.post(
                f"{BASE_URL}/api/cart",
                headers=auth_headers,
                json={"productId": product_id, "quantity": original_item["quantity"]},
                timeout=TIMEOUT,
            )
            assert add_response.status_code == 201, (
                f"恢复原购物车商品失败，状态码={add_response.status_code}，响应={add_response.text}"
            )
            latest_cart = _get_cart(auth_headers)
            latest_item = _find_cart_item(latest_cart["items"], product_id)
            assert latest_item is not None, f"恢复后仍未找到原商品 productId={product_id}，购物车={latest_cart}"

        _patch_cart_item(
            auth_headers,
            latest_item["id"],
            {"quantity": original_item["quantity"], "selected": bool(original_item["selected"])},
        )


def _cancel_order_by_api(auth_headers, order_id):
    # UI 流程中途失败时，使用 API 尽量取消本次创建的 PENDING 订单
    response = requests.post(
        f"{BASE_URL}/api/orders/{order_id}/cancel",
        headers=auth_headers,
        timeout=TIMEOUT,
    )
    if response.status_code not in (200, 409):
        raise AssertionError(f"API 清理订单失败，状态码={response.status_code}，响应={response.text}")


def _extract_order_no(message):
    # 前端创建订单弹窗格式：订单创建成功：订单号
    prefix = "订单创建成功："
    assert message.startswith(prefix), f"创建订单弹窗提示不符合预期，实际={message}"
    order_no = message.removeprefix(prefix).strip()
    assert order_no != ""
    return order_no


def _click_and_accept_dialog(page: Page, locator):
    # 同步捕获本次点击产生的弹窗，只接受一次并返回消息
    with page.expect_event("dialog") as dialog_info:
        locator.click()
    dialog = dialog_info.value
    message = dialog.message
    dialog.accept()
    return message


def _extract_order_id(order_card):
    # 从取消按钮 onclick 中提取动态 orderId，例如 cancelOrder(123)
    cancel_button = order_card.get_by_role("button", name="取消订单", exact=True)
    expect(cancel_button).to_have_count(1)
    onclick = cancel_button.get_attribute("onclick")
    assert onclick is not None, "取消订单按钮缺少 onclick 属性"
    match = re.fullmatch(r"cancelOrder\((\d+)\)", onclick)
    assert match is not None, f"无法从取消按钮 onclick 提取 orderId，onclick={onclick}"
    return int(match.group(1))


def _find_order_in_response(orders, order_id, order_no):
    # 优先用 orderId 匹配；如果页面/接口字段变化，再用 orderNo 辅助匹配
    for order in orders:
        if order.get("id") == order_id:
            return order
    for order in orders:
        if order.get("orderNo") == order_no:
            return order
    return None


def _order_card_by_order_id(page: Page, order_id):
    # PENDING 订单卡片内有唯一 cancelOrder(orderId) 按钮，可用动态 orderId 精确定位
    cancel_button = page.locator(f'button[onclick="cancelOrder({order_id})"]')
    expect(cancel_button).to_have_count(1)
    return cancel_button.locator("xpath=ancestor::article[1]")


def _order_card_by_order_no(page: Page, order_no):
    # 使用动态订单号定位刚创建的订单卡片，不依赖“订单号”和冒号的空格格式
    return page.locator("article.card.order").filter(has_text=order_no)


def test_ui_create_order_and_cancel_order_flow(page: Page):
    auth_headers = None
    original_cart = None
    created_order_id = None
    order_cancelled = False

    try:
        # 正常登录，并记录原始购物车快照
        _login_by_page(page)
        auth_headers = _auth_headers_from_page(page)
        original_cart = _get_cart(auth_headers)

        # 通过 API 辅助取消原有选中项，避免本次订单混入用户原有商品
        for item in original_cart["items"]:
            if item.get("selected"):
                _patch_cart_item(auth_headers, item["id"], {"selected": False})

        # 选择一个真实有库存商品，并通过唯一 productId 按钮加入购物车
        target_product = _choose_addable_product(original_cart["items"])
        target_product_id = target_product["id"]
        add_button = page.locator(f'button[onclick="add({target_product_id})"]')
        expect(add_button).to_have_count(1)
        expect(add_button).to_be_visible()
        add_message = _click_and_accept_dialog(page, add_button)
        assert "已加入购物车" in add_message, f"加入购物车弹窗提示不符合预期，实际={add_message}"

        # 打开购物车，并确保该商品被选中
        page.get_by_role("button", name="购物车", exact=True).click()
        cart_panel = page.locator("section.panel").filter(
            has=page.get_by_role("heading", name="购物车", exact=True)
        )
        expect(cart_panel).to_be_visible()
        target_cart_row = cart_panel.locator("article.card").filter(
            has=page.get_by_text(target_product["name"], exact=True)
        )
        expect(target_cart_row).to_have_count(1)
        checkbox = target_cart_row.locator("input[type='checkbox']")
        expect(checkbox).to_be_visible()
        if not checkbox.is_checked():
            checkbox.check()

        # 通过页面点击提交订单，同时捕获真实 POST /api/orders 响应
        with page.expect_response(
            lambda response: response.url.endswith("/api/orders") and response.request.method == "GET"
        ) as orders_response_info:
            with page.expect_response(
                lambda response: response.url.endswith("/api/orders") and response.request.method == "POST"
            ) as create_response_info:
                with page.expect_event("dialog") as create_dialog_info:
                    page.get_by_role("button", name="提交订单", exact=True).click()
                create_dialog = create_dialog_info.value
                create_message = create_dialog.message
                create_dialog.accept()
        create_response = create_response_info.value
        assert create_response.status == 201, f"创建订单接口状态码不符合预期，实际={create_response.status}"
        create_json = create_response.json()
        created_order_id = create_json.get("id")
        created_order_no = create_json.get("orderNo")
        assert isinstance(created_order_id, int) and created_order_id > 0, f"创建订单响应缺少有效 orderId，响应={create_json}"
        assert isinstance(created_order_no, str) and created_order_no.strip() != "", f"创建订单响应缺少有效 orderNo，响应={create_json}"

        popup_order_no = _extract_order_no(create_message)
        assert popup_order_no == created_order_no, (
            f"弹窗订单号与 POST /api/orders 响应不一致，弹窗={popup_order_no}，接口={created_order_no}，"
            f"接口状态码={create_response.status}"
        )

        # 创建订单弹窗已由一次性处理器接受，前端随即进入“我的订单”
        orders_response = orders_response_info.value
        assert orders_response.status == 200, f"查询订单列表接口状态码不符合预期，实际={orders_response.status}"
        orders_json = orders_response.json()
        matched_order = _find_order_in_response(orders_json, created_order_id, created_order_no)
        assert matched_order is not None, (
            f"GET /api/orders 未包含刚创建的订单，orderId={created_order_id}，orderNo={created_order_no}，"
            f"接口状态码={orders_response.status}，列表orderIds={[order.get('id') for order in orders_json]}，"
            f"列表orderNos={[order.get('orderNo') for order in orders_json]}"
        )
        rendered_order_no = matched_order.get("orderNo")

        # 进入我的订单，并用动态 orderId 精确找到刚创建的 PENDING 订单
        expect(page.get_by_role("heading", name="我的订单", exact=True)).to_be_visible()
        orders_panel = page.locator("section.panel").filter(
            has=page.get_by_role("heading", name="我的订单", exact=True)
        )
        expect(orders_panel).to_be_visible()
        order_card = _order_card_by_order_id(page, created_order_id)
        visible_order_text = orders_panel.inner_text()
        assert order_card.count() == 1, (
            f"未能通过动态 orderId 定位本次订单，orderId={created_order_id}，orderNo={created_order_no}，"
            f"我的订单页面可见文字={visible_order_text}"
        )
        expect(order_card).to_be_visible()

        # 再从页面取消按钮反查 orderId，确认页面卡片确实属于刚创建的订单
        page_order_id = _extract_order_id(order_card)
        assert page_order_id == created_order_id, (
            f"页面订单 ID 与创建接口响应不一致，页面={page_order_id}，接口={created_order_id}"
        )

        # 断言订单状态为 PENDING，页面展示为“待支付”
        expect(order_card.locator(".status")).to_have_text("待支付")

        # 断言订单金额大于 0
        total_text = order_card.get_by_text(re.compile(r"^总金额：¥")).inner_text()
        total_amount = total_text.split("¥")[-1].strip()
        assert float(total_amount) > 0, f"订单金额未大于 0，实际={total_text}"

        # 点击该订单取消按钮，并正确处理浏览器弹窗
        with page.expect_response(
            lambda response: response.url.endswith("/api/orders") and response.request.method == "GET"
        ):
            with page.expect_response(
                lambda response: response.url.endswith(f"/api/orders/{created_order_id}/cancel")
                and response.request.method == "POST"
            ) as cancel_response_info:
                with page.expect_event("dialog") as cancel_dialog_info:
                    order_card.get_by_role("button", name="取消订单", exact=True).click()
                cancel_dialog = cancel_dialog_info.value
                cancel_message = cancel_dialog.message
                cancel_dialog.accept()
        cancel_response = cancel_response_info.value
        assert cancel_response.status == 200, f"取消订单接口状态码不符合预期，实际={cancel_response.status}"
        assert "订单已取消" in cancel_message, f"取消订单弹窗提示不符合预期，实际={cancel_message}"
        order_cancelled = True

        # 断言订单状态变成 CANCELLED，页面展示为“已取消”
        cancelled_order_card = _order_card_by_order_no(page, rendered_order_no)
        expect(cancelled_order_card).to_have_count(1)
        expect(cancelled_order_card.locator(".status")).to_have_text("已取消")
    except Exception:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT_DIR / "test_ui_create_order_and_cancel_order_flow_failed.png"), full_page=True)
        raise
    finally:
        # 如果 UI 中途失败但订单已创建，尽量用 API 取消，避免留下 PENDING 订单
        if auth_headers is not None and created_order_id is not None and not order_cancelled:
            _cancel_order_by_api(auth_headers, created_order_id)

        # 恢复用户原始购物车状态
        if auth_headers is not None and original_cart is not None:
            _restore_cart(auth_headers, original_cart)
