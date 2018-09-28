from routes.middleware import path_params, query_validators, body_validators, token_validate
from sanic.views import HTTPMethodView
from . import base_fn
from services import http_request
import ujson
from conf import enum, conf
from sanic.response import json
from handlers.validators import Validators
import time


class TestMobileFlowView(HTTPMethodView):
    async def get(self, req):
        xtoken, xtimestamp = base_fn.prepare_test_param({"method": 'mobie_flow/15910863994/1000'})
        headers = {'xtoken': xtoken, 'xtimestamp': xtimestamp}
        urls = "/v1/bm/mobie_flow/15910863994/1000"
        res = await http_request.test_mobie_flow(req, urls, headers=headers)
        return json(ujson.loads(res))


class TestGasCardAccountInfo(HTTPMethodView):
    async def get(self, req):
        body = req.json
        params = {
            "method": enum.GAS_CARD_ITEM_LIST
        }
        urls = base_fn.gen_urls(params)
        res = await http_request.get_gas_account_info(req, urls)
        res = ujson.loads(res)
        return json(res)


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
