import pytest
import requests

from config import BASE_URL, PREFERRED_PRODUCT_ID, TIMEOUT


pytestmark = pytest.mark.api


def _parse_json(response):
    # 统一解析 JSON，失败时输出状态码和响应内容
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
    # 查询真实商品列表，用来选择有库存商品
    response = requests.get(f"{BASE_URL}/api/products", timeout=TIMEOUT)
    assert response.status_code == 200, f"查询商品失败，状态码={response.status_code}，响应={response.text}"
    products = _parse_json(response)
    assert isinstance(products, list), f"商品列表响应不是列表，响应={products}"
    return products


def _find_cart_item(cart_items, product_id):
    # 按商品 ID 查找购物车行
    return next((item for item in cart_items if item.get("productId") == product_id), None)


def _patch_cart_item(auth_headers, cart_id, body):
    # 通过接口修改购物车数量或选中状态
    response = requests.patch(
        f"{BASE_URL}/api/cart/{cart_id}",
        headers=auth_headers,
        json=body,
        timeout=TIMEOUT,
    )
    assert response.status_code == 200, f"修改购物车失败，状态码={response.status_code}，响应={response.text}"
    return _parse_json(response)


def _choose_product_to_add(cart_items):
    # 优先选择 productId=3；如果不能再添加，则选择其他有库存商品
    products = _get_products()
    cart_quantities = {
        item.get("productId"): item.get("quantity", 0)
        for item in cart_items
    }
    sorted_products = sorted(
        products,
        key=lambda product: 0 if product.get("id") == PREFERRED_PRODUCT_ID else 1,
    )

    for product in sorted_products:
        product_id = product.get("id")
        stock = product.get("stock", 0)
        current_quantity = cart_quantities.get(product_id, 0)
        if stock > 0 and current_quantity < stock:
            return product

    raise AssertionError(f"没有找到可添加的有库存商品，商品列表={products}，购物车={cart_items}")


def _choose_existing_orderable_item(cart_items):
    # 优先使用购物车中已经存在且库存足够的商品
    return next(
        (
            item
            for item in cart_items
            if item.get("quantity", 0) > 0 and item.get("stock", 0) >= item.get("quantity", 0)
        ),
        None,
    )


def _prepare_one_selected_item(auth_headers, original_cart):
    # 临时只选中一个可下单商品，避免其他购物车项影响订单内容
    for item in original_cart["items"]:
        if item.get("selected"):
            _patch_cart_item(auth_headers, item["id"], {"selected": False})

    existing_item = _choose_existing_orderable_item(original_cart["items"])
    if existing_item is not None:
        _patch_cart_item(auth_headers, existing_item["id"], {"selected": True})
        return existing_item["productId"]

    product = _choose_product_to_add(original_cart["items"])
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


def _restore_cart(auth_headers, original_cart):
    # 通过真实购物车接口恢复测试前的购物车状态
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


def test_create_order_and_query_by_dynamic_order_id(auth_headers):
    original_cart = None
    order_id = None

    try:
        # 查询购物车，并准备一个可下单商品
        original_cart = _get_cart(auth_headers)
        _prepare_one_selected_item(auth_headers, original_cart)

        # 调用真实创建订单接口
        create_response = requests.post(
            f"{BASE_URL}/api/orders",
            headers=auth_headers,
            json={},
            timeout=TIMEOUT,
        )
        assert create_response.status_code == 201, (
            f"创建订单失败，状态码={create_response.status_code}，响应={create_response.text}"
        )
        create_json = _parse_json(create_response)

        # 从创建订单响应中提取动态 orderId
        order_id = create_json.get("id")
        assert isinstance(order_id, int) and order_id > 0, f"orderId 不是大于 0 的整数，响应={create_json}"

        # 使用动态 orderId 查询订单详情
        detail_response = requests.get(
            f"{BASE_URL}/api/orders/{order_id}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert detail_response.status_code == 200, (
            f"查询订单详情失败，状态码={detail_response.status_code}，响应={detail_response.text}"
        )
        detail_json = _parse_json(detail_response)

        # 验证查询结果与刚创建的订单一致
        assert detail_json.get("id") == order_id, f"查询到的订单 ID 不一致，orderId={order_id}，响应={detail_json}"
        assert detail_json.get("status") == "PENDING", f"新订单状态不是 PENDING，响应={detail_json}"
        assert isinstance(detail_json.get("items"), list) and len(detail_json["items"]) > 0, (
            f"订单 items 为空或不是列表，响应={detail_json}"
        )
        assert detail_json.get("totalAmount", 0) > 0, f"订单 totalAmount 未大于 0，响应={detail_json}"
    finally:
        # 清理本次创建的 PENDING 订单，并尽量恢复购物车
        if order_id is not None:
            cancel_response = requests.post(
                f"{BASE_URL}/api/orders/{order_id}/cancel",
                headers=auth_headers,
                timeout=TIMEOUT,
            )
            assert cancel_response.status_code == 200, (
                f"取消测试订单失败，状态码={cancel_response.status_code}，响应={cancel_response.text}"
            )
            cancel_json = _parse_json(cancel_response)
            assert isinstance(cancel_json.get("message"), str) and cancel_json["message"].strip() != "", (
                f"取消订单响应缺少非空 message，响应={cancel_json}"
            )

        if original_cart is not None:
            _restore_cart(auth_headers, original_cart)
