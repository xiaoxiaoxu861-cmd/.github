import pytest
import requests

from config import BASE_URL, TIMEOUT


pytestmark = pytest.mark.api


def _parse_json(response):
    # 统一解析 JSON，失败时显示状态码和响应内容
    try:
        return response.json()
    except ValueError as exc:
        raise AssertionError(f"响应不是 JSON，状态码={response.status_code}，内容={response.text}") from exc


def _get_cart(auth_headers):
    # 查询当前用户购物车
    response = requests.get(f"{BASE_URL}/api/cart", headers=auth_headers, timeout=TIMEOUT)
    assert response.status_code == 200, f"查询购物车失败，状态码={response.status_code}，响应={response.text}"
    cart_json = _parse_json(response)
    assert isinstance(cart_json.get("items"), list), f"购物车 items 不是列表，响应={cart_json}"
    return cart_json


def _get_products():
    # 查询商品列表，用真实库存选择测试商品
    response = requests.get(f"{BASE_URL}/api/products", timeout=TIMEOUT)
    assert response.status_code == 200, f"查询商品失败，状态码={response.status_code}，响应={response.text}"
    products = _parse_json(response)
    assert isinstance(products, list), f"商品列表响应不是列表，响应={products}"
    return products


def _find_cart_item(cart_items, product_id):
    # 按商品 ID 查找购物车行
    return next((item for item in cart_items if item.get("productId") == product_id), None)


def _patch_cart_item(auth_headers, cart_id, body):
    # 通过真实接口修改购物车数量或选中状态
    response = requests.patch(
        f"{BASE_URL}/api/cart/{cart_id}",
        headers=auth_headers,
        json=body,
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"修改购物车失败，状态码={response.status_code}，响应={response.text}"
    return _parse_json(response)


def _choose_payment_product(original_cart):
    # 优先选择购物车中没有的有库存商品，减少对原购物车的影响
    products = _get_products()
    cart_by_product = {
        item["productId"]: item
        for item in original_cart["items"]
    }

    for product in products:
        if product.get("stock", 0) > 0 and product.get("id") not in cart_by_product:
            return product

    # 如果所有有库存商品都已在购物车中，则选择支付后仍能恢复原数量的商品
    for product in products:
        product_id = product.get("id")
        original_item = cart_by_product.get(product_id)
        original_quantity = original_item.get("quantity", 0) if original_item else 0
        if product.get("stock", 0) >= original_quantity * 2 + 1:
            return product

    raise AssertionError(f"没有找到适合支付流测试的有库存商品，商品列表={products}，购物车={original_cart}")


def _prepare_order_item(auth_headers, original_cart):
    # 只选中本次测试商品，避免把用户原有购物车商品一起下单
    for item in original_cart["items"]:
        if item.get("selected"):
            _patch_cart_item(auth_headers, item["id"], {"selected": False})

    product = _choose_payment_product(original_cart)
    add_response = requests.post(
        f"{BASE_URL}/api/cart",
        headers=auth_headers,
        json={"productId": product["id"], "quantity": 1},
        timeout=TIMEOUT,
    )
    assert add_response.status_code == 201, f"添加购物车失败，状态码={add_response.status_code}，响应={add_response.text}"
    _parse_json(add_response)

    latest_cart = _get_cart(auth_headers)
    latest_item = _find_cart_item(latest_cart["items"], product["id"])
    assert latest_item is not None, f"添加后购物车未找到商品 productId={product['id']}，购物车={latest_cart}"
    _patch_cart_item(auth_headers, latest_item["id"], {"selected": True})
    return product["id"]


def _create_order(auth_headers):
    # 创建订单接口不需要业务请求体，后端会使用已选购物车商品
    response = requests.post(
        f"{BASE_URL}/api/orders",
        headers=auth_headers,
        json={},
        timeout=TIMEOUT,
    )
    assert response.status_code == 201, f"创建订单失败，状态码={response.status_code}，响应={response.text}"
    order_json = _parse_json(response)
    order_id = order_json.get("id")
    assert isinstance(order_id, int) and order_id > 0, f"orderId 不是大于 0 的整数，响应={order_json}"
    return order_id


def _get_order(auth_headers, order_id):
    # 使用动态 orderId 查询订单详情
    response = requests.get(
        f"{BASE_URL}/api/orders/{order_id}",
        headers=auth_headers,
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"查询订单失败，状态码={response.status_code}，响应={response.text}"
    return _parse_json(response)


def _restore_cart(auth_headers, original_cart):
    # 尽量通过真实购物车接口恢复测试前的购物车状态
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


def test_order_payment_status_flow(auth_headers):
    original_cart = None
    order_id = None
    order_was_paid = False

    try:
        # 准备购物车商品并创建新订单
        original_cart = _get_cart(auth_headers)
        _prepare_order_item(auth_headers, original_cart)
        order_id = _create_order(auth_headers)

        # A. 查询新订单，验证初始状态
        pending_order = _get_order(auth_headers, order_id)
        assert pending_order.get("id") == order_id, f"订单 ID 不一致，orderId={order_id}，响应={pending_order}"
        assert pending_order.get("status") == "PENDING", f"新订单状态不是 PENDING，响应={pending_order}"
        assert pending_order.get("paidAt") is None, f"新订单 paidAt 应为空，响应={pending_order}"

        # B. 模拟支付失败
        fail_response = requests.post(
            f"{BASE_URL}/api/orders/{order_id}/pay",
            headers=auth_headers,
            json={"result": "fail"},
            timeout=TIMEOUT,
        )
        assert fail_response.status_code == 200, (
            f"支付失败接口状态码不符合预期，状态码={fail_response.status_code}，响应={fail_response.text}"
        )
        fail_json = _parse_json(fail_response)
        assert fail_json.get("message") == "支付失败", f"支付失败提示不符合预期，响应={fail_json}"
        assert fail_json.get("status") == "PENDING", f"支付失败后接口状态不符合预期，响应={fail_json}"

        # C. 支付失败后再次查询，订单仍应保持待支付
        after_fail_order = _get_order(auth_headers, order_id)
        assert after_fail_order.get("status") == "PENDING", f"支付失败后订单状态被错误改变，响应={after_fail_order}"
        assert after_fail_order.get("paidAt") is None, f"支付失败后 paidAt 不应有值，响应={after_fail_order}"

        # D. 模拟支付成功
        success_response = requests.post(
            f"{BASE_URL}/api/orders/{order_id}/pay",
            headers=auth_headers,
            json={"result": "success"},
            timeout=TIMEOUT,
        )
        assert success_response.status_code == 200, (
            f"支付成功接口状态码不符合预期，状态码={success_response.status_code}，响应={success_response.text}"
        )
        success_json = _parse_json(success_response)
        assert success_json.get("message") == "支付成功", f"支付成功提示不符合预期，响应={success_json}"
        assert success_json.get("status") == "PAID", f"支付成功接口状态不符合预期，响应={success_json}"
        order_was_paid = True

        # E. 查询订单，验证已支付并保存第一次 paidAt
        paid_order = _get_order(auth_headers, order_id)
        assert paid_order.get("status") == "PAID", f"支付成功后订单状态不是 PAID，响应={paid_order}"
        first_paid_at = paid_order.get("paidAt")
        assert isinstance(first_paid_at, str) and first_paid_at.strip() != "", (
            f"支付成功后 paidAt 不是非空值，响应={paid_order}"
        )

        # F. 对同一订单重复支付，应返回已支付错误
        repeat_response = requests.post(
            f"{BASE_URL}/api/orders/{order_id}/pay",
            headers=auth_headers,
            json={"result": "success"},
            timeout=TIMEOUT,
        )
        assert repeat_response.status_code == 400, (
            f"重复支付状态码不符合预期，状态码={repeat_response.status_code}，响应={repeat_response.text}"
        )
        repeat_json = _parse_json(repeat_response)
        assert repeat_json.get("message") == "订单已支付", f"重复支付错误提示不符合预期，响应={repeat_json}"

        # G. 最后查询订单，确认仍为已支付且 paidAt 没有被改写
        final_order = _get_order(auth_headers, order_id)
        assert final_order.get("status") == "PAID", f"重复支付后订单状态不应改变，响应={final_order}"
        assert final_order.get("paidAt") == first_paid_at, (
            f"重复支付后 paidAt 不应改变，首次 paidAt={first_paid_at}，最终响应={final_order}"
        )
    finally:
        # 只有未支付订单才尝试取消；PAID 订单不能通过业务接口清理
        if order_id is not None and not order_was_paid:
            cancel_response = requests.post(
                f"{BASE_URL}/api/orders/{order_id}/cancel",
                headers=auth_headers,
                timeout=TIMEOUT,
            )
            assert cancel_response.status_code == 200, (
                f"取消未支付测试订单失败，状态码={cancel_response.status_code}，响应={cancel_response.text}"
            )

        if original_cart is not None:
            _restore_cart(auth_headers, original_cart)
