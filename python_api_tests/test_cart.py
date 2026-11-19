import pytest
import requests

from config import BASE_URL, PREFERRED_PRODUCT_ID, TIMEOUT


pytestmark = pytest.mark.api


def _parse_json(response):
    # 统一解析 JSON，失败时给出清楚的响应内容
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


def _find_cart_item(cart_items, product_id):
    # 按商品 ID 查找购物车行
    return next((item for item in cart_items if item.get("productId") == product_id), None)


def _choose_target_product(cart_items):
    # 优先选择 productId=3；如果不能继续加 1，则选择其他真实有库存商品
    products_response = requests.get(f"{BASE_URL}/api/products", timeout=TIMEOUT)
    assert products_response.status_code == 200, (
        f"查询商品列表失败，状态码={products_response.status_code}，响应={products_response.text}"
    )
    products = _parse_json(products_response)
    assert isinstance(products, list), f"商品列表响应不是列表，响应={products}"

    product_quantities = {
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
        current_quantity = product_quantities.get(product_id, 0)
        if stock > 0 and current_quantity < stock:
            return product

    raise AssertionError(f"没有找到可添加 1 件的有库存商品，商品列表={products}，购物车={cart_items}")


def test_add_product_to_cart_increases_quantity_by_one(auth_headers):
    original_cart = None
    target_product = None
    original_item = None

    try:
        # 添加前查询购物车，记录原始数量
        original_cart = _get_cart(auth_headers)
        target_product = _choose_target_product(original_cart["items"])
        target_product_id = target_product["id"]
        original_item = _find_cart_item(original_cart["items"], target_product_id)
        original_quantity = original_item["quantity"] if original_item else 0

        # 调用真实添加购物车接口，添加数量 1
        add_response = requests.post(
            f"{BASE_URL}/api/cart",
            headers=auth_headers,
            json={"productId": target_product_id, "quantity": 1},
            timeout=TIMEOUT,
        )
        assert add_response.status_code == 201, (
            f"添加购物车失败，状态码={add_response.status_code}，响应={add_response.text}"
        )
        add_json = _parse_json(add_response)
        assert isinstance(add_json.get("message"), str) and add_json["message"].strip() != "", (
            f"添加购物车响应缺少非空 message，响应={add_json}"
        )

        # 添加后再次查询购物车
        updated_cart = _get_cart(auth_headers)
        updated_item = _find_cart_item(updated_cart["items"], target_product_id)

        # 验证目标商品存在，且数量增加 1
        assert updated_item is not None, f"添加后购物车中未找到商品 productId={target_product_id}，响应={updated_cart}"
        assert updated_item["quantity"] == original_quantity + 1, (
            f"商品数量未加 1，productId={target_product_id}，"
            f"添加前={original_quantity}，添加后={updated_item['quantity']}，购物车={updated_cart}"
        )
    finally:
        # 测试结束后通过接口恢复购物车原始状态，保证用例可重复运行
        if target_product is not None:
            latest_cart = _get_cart(auth_headers)
            latest_item = _find_cart_item(latest_cart["items"], target_product["id"])
            if latest_item is not None:
                if original_item is None:
                    requests.delete(
                        f"{BASE_URL}/api/cart/{latest_item['id']}",
                        headers=auth_headers,
                        timeout=TIMEOUT,
                    )
                else:
                    requests.patch(
                        f"{BASE_URL}/api/cart/{latest_item['id']}",
                        headers=auth_headers,
                        json={"quantity": original_item["quantity"]},
                        timeout=TIMEOUT,
                    )
