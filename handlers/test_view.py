from routes.middleware import path_params, query_validators, body_validators, token_validate
from sanic.views import HTTPMethodView
from . import base_fn
from services import http_request
import ujson
from conf import enum, conf
from sanic.response import json, text
from handlers.validators import Validators
import copy


async def fetch_res(req, body, method):
    try:
        params = copy.copy(body)
        params['method'] = method
        xtoken, xtimestamp = base_fn.prepare_test_param(params)
        headers = {'xtoken': xtoken, 'xtimestamp': xtimestamp}
        urls = f"/{method}"
        res = await http_request.test_post_api(req, urls, headers=headers, body=body)
        return json(ujson.loads(res))
    except Exception as e:
        return text('failed', 500)


class TestMobileFlowView(HTTPMethodView):
    async def get(self, req):
        body = {
            "mobile_no": "15910863994",
            "recharge_amount": "300"
        }
        from conf import route_map
        return await fetch_res(req, body, route_map.MOBILE_FLOW)


class TestGasCardAccountInfo(HTTPMethodView):
    async def get(self, req):
        body = {
            "province": "天津",
            "operator": "sinopec",
            "card_no": "1000111200008936352"
        }
        from conf import route_map
        return await fetch_res(req, body, route_map.GAS_CARD_ACCOUNT_INFO)


class TestGasCardPayBill(HTTPMethodView):
    async def get(self, req):
        body = {
            "item_id": "64357114",
            "gas_card_tel": "18033616617",
            "gas_card_name": "董明瑞",
            "card_no": "1000111100017573362"
        }
        from conf import route_map
        return await fetch_res(req, body, route_map.GAS_CARD_PAYBILL)


class TestFinanceAccInfo(HTTPMethodView):
    async def get(self, req):
        params = {
            'method': 'finance_accinfo'
        }
        xtoken, xtimestamp = base_fn.prepare_test_param(params)
        headers = {'xtoken': xtoken, 'xtimestamp': xtimestamp}
        urls = "/finance_accinfo"
        res = await http_request.test_get_api(req, urls, headers=headers)
        return json(ujson.loads(res))


class TestCardPassItemList(HTTPMethodView):
    async def get(self, req):
        params = {
            'method': 'cardpasslist'
        }
        xtoken, xtimestamp = base_fn.prepare_test_param(params)
        headers = {'xtoken': xtoken, 'xtimestamp': xtimestamp}
        urls = "/cardpasslist"
        res = await http_request.test_get_api(req, urls, headers=headers)
        try:
            return json(ujson.loads(res))
        except Exception as e:
            return text(res, 401)


class GasCardPayBill(HTTPMethodView):
    @path_params
    @body_validators(Validators.schema_gas_card_pay_bill)
    @token_validate
    async def post(self, req):
        body = req.json
        params = {
            "method": enum.GAS_CARD_PAYBILL,
            'itemId': body['item_id'],
            'gasCardTel': body['gas_card_tel'],
            'gasCardName': body['gas_card_name'],
            'gasCardNo': body['card_no'],
            'callback': 'http://127.0.0.1:5005/v1/bm/message'
        }
        urls = base_fn.gen_urls(params)
        res = await http_request.get_gas_card_pay_bill(req, urls)
        res = ujson.loads(res)
        return json(res)


class GasCallbackMsg(HTTPMethodView):
    async def get(self, req):
        print(req.json)
