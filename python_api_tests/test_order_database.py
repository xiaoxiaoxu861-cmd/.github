from decimal import Decimal

import pytest
import requests

from config import BASE_URL, PREFERRED_PRODUCT_ID, TIMEOUT


pytestmark = [pytest.mark.api, pytest.mark.db]


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


def _choose_product_to_add(cart_items):
    # 优先选择配置商品；如果不能再添加，则选择其他真实有库存商品
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


def _prepare_one_selected_item(auth_headers, original_cart):
    # 临时只选中一个可下单商品，避免其他购物车项影响订单内容
    for item in original_cart["items"]:
        if item.get("selected"):
            _patch_cart_item(auth_headers, item["id"], {"selected": False})

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


def _query_order_from_db(db_connection, order_id):
    # 只执行参数化 SELECT，不拼接 SQL 字符串
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, status, total_amount AS totalAmount FROM orders WHERE id = %s",
            (order_id,),
        )
        return cursor.fetchone()


def test_created_order_matches_database_record(auth_headers, db_connection):
    original_cart = None
    order_id = None

    try:
        # 通过真实接口准备购物车并创建订单
        original_cart = _get_cart(auth_headers)
        _prepare_one_selected_item(auth_headers, original_cart)
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
        order_id = create_json.get("id")
        assert isinstance(order_id, int) and order_id > 0, f"orderId 不是大于 0 的整数，响应={create_json}"

        # 通过接口查询订单详情
        detail_response = requests.get(
            f"{BASE_URL}/api/orders/{order_id}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert detail_response.status_code == 200, (
            f"查询订单详情失败，状态码={detail_response.status_code}，响应={detail_response.text}"
        )
        detail_json = _parse_json(detail_response)
        api_status = detail_json.get("status")
        api_total_amount = Decimal(str(detail_json.get("totalAmount")))

        # 通过数据库查询同一订单，并比较接口与数据库数据
        db_order = _query_order_from_db(db_connection, order_id)
        assert db_order is not None, f"数据库中未找到订单 orderId={order_id}"
        assert db_order["id"] == order_id, f"数据库订单 ID 不一致，orderId={order_id}，数据库记录={db_order}"
        assert db_order["status"] == api_status, f"数据库 status 与接口不一致，接口={api_status}，数据库记录={db_order}"
        assert Decimal(db_order["totalAmount"]) == api_total_amount, (
            f"数据库 totalAmount 与接口不一致，接口={api_total_amount}，数据库记录={db_order}"
        )
        assert api_status == "PENDING", f"新订单接口状态不是 PENDING，响应={detail_json}"
        assert db_order["status"] == "PENDING", f"新订单数据库状态不是 PENDING，数据库记录={db_order}"
    finally:
        # 清理本次创建的 PENDING 订单；数据库仍然只做 SELECT 校验
        if order_id is not None:
            cancel_response = requests.post(
                f"{BASE_URL}/api/orders/{order_id}/cancel",
                headers=auth_headers,
                timeout=TIMEOUT,
            )
            assert cancel_response.status_code == 200, (
                f"取消测试订单失败，状态码={cancel_response.status_code}，响应={cancel_response.text}"
            )
            cancelled_order = _query_order_from_db(db_connection, order_id)
            assert cancelled_order is not None, f"取消后数据库中未找到订单 orderId={order_id}"
            assert cancelled_order["status"] == "CANCELLED", f"取消后数据库状态不是 CANCELLED，数据库记录={cancelled_order}"

        if original_cart is not None:
            _restore_cart(auth_headers, original_cart)
