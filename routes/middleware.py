import gzip
import time
from random import random
from functools import wraps
from urllib.parse import unquote
from shortuuid import uuid

from sanic.response import text

from conf import conf
from utils import logger
from utils.jsonv import validate
from .req_context import ReqContext
from handlers import base_fn
from conf import enum

MIME_TYPES_TO_GZIP = frozenset([
    'text/html', 'text/css', 'text/xml',
    'application/json',
    'application/javascript'])
GZIP_MIN_SIZE = 500
GZIP_LEVEL = 5
PROTECT_HEADERS = ['xtimestamp', 'xtoken']


# if conf.IS_PROD \
# else []


class Helper:
    @staticmethod
    def req_log(req, res, time_ms_spent):
        q = req.query_string

        if q:
            q = '?' + q

        return f"{req['logid']} {req.method} {req.path}{q} {req.headers} {res.status} {len(res.body)} {time_ms_spent}ms"


def append_logid(req):
    req['logid'] = uuid()


def header_protect(req):
    if req.path == '/health' or req.path == '/' or req.path.find('/v1/bm_test') >= 0:
        return

    for h in PROTECT_HEADERS:
        if req.headers.get(h) is None:
            return text('', 404)


def gzip_res(req, res):
    accept_encoding = req.headers.get('Accept-Encoding', '')
    content_length = len(res.body)
    content_type = res.content_type

    if ';' in res.content_type:
        content_type = content_type.split(';')[0]

    if (content_type not in MIME_TYPES_TO_GZIP or
            'gzip' not in accept_encoding.lower() or
            not 200 <= res.status < 300 or
            (content_length is not None and
             content_length < GZIP_MIN_SIZE) or
            'Content-Encoding' in res.headers):
        return

    res.body = gzip.compress(res.body, compresslevel=GZIP_LEVEL)
    res.headers['Content-Encoding'] = 'gzip'
    res.headers['Content-Length'] = len(res.body)

    vary = res.headers.get('Vary')
    if vary:
        if 'accept-encoding' not in vary.lower():
            res.headers['Vary'] = '{}, Accept-Encoding'.format(vary)
    else:
        res.headers['Vary'] = 'Accept-Encoding'


def mark_req_start_time(req):
    req['_start_time'] = time.time()


def mark_req_end_time(req, res):
    time_ms_spent = int((time.time() - req['_start_time']) * 1000)

    if conf.IS_PROD:
        if (not req.path.startswith('/v3')) and (not req.path.startswith('/v1/configure')) and (random() * 300 < 1):
            logger.info(f"[sample] {Helper.req_log(req, res, time_ms_spent)}")
        elif time_ms_spent >= 1000:
            logger.info(f"[longtime] {Helper.req_log(req, res, time_ms_spent)}")
    else:
        logger.info(Helper.req_log(req, res, time_ms_spent))

    if 'path_content' in req:
        record_path = req['path_content']
    else:
        record_path = req.path


def append_req_context(req):
    req['context'] = ReqContext()


def append_user(req):
    # address = conf.USER_ACTION_SERVER_URL
    # req['user'] = User(req, address)
    pass


def append_headers(req):
    pass
    # prefer_lang = req.headers.get('x-prefer-lang').split(';') if req.headers.get('x-prefer-lang') else []
    # # prefer_lang = [enum.LANGUAGE_MAPPING.get(lang) for lang in prefer_lang if lang in enum.LANGUAGE_MAPPING]
    # # prefer_lang.sort()
    #
    # app_code = req.headers.get('x-app-version', '9999999999')
    # req['xheaders'] = {
    #     'lang': req.headers.get('x-lang', 'en'),
    #     'country': req.headers.get('x-country', 'us'),
    #     'density': req.headers.get('x-density', '1'),
    #     'prefer-lang': prefer_lang,
    #     'app-version': app_code[3:],
    #     'app-code': app_code,
    #     'av-code': req.headers.get('x-av-code')
    # }


def cdn_cache(req, res):
    pass


def path_params(f):
    @wraps(f)
    async def g(view, req, **kwargs):
        for k in kwargs.keys():
            kwargs[k] = unquote(kwargs[k])

        req['context'].path_params = kwargs
        return await f(view, req)

    return g


def body_validators(*schemas):
    def f(g):
        async def h(view, req):
            for schema in schemas:
                if validate(req.json, schema):
                    return await g(view, req)
            return text('param is not right', 400)

        return h

    return f


def query_validators(*schemas):
    def f(g):
        async def h(view, req):
            args = {key: req['context'].path_params.get(key) for key in req['context'].path_params}
            for schema in schemas:
                if validate(args, schema):
                    return await g(view, req)

            return text('', 400)

        return h

    return f


def path_content(path):
    def f(g):
        async def h(view, req):
            req['path_content'] = path
            return await g(view, req)

        return h

    return f


def token_validate(f):
    @wraps(f)
    async def g(view, req, **kwargs):
        req.session['islogin'] = True

        params = req.json or {}
        params['method'] = req.path.replace('/v1/bm/', '')
        params['v'] = enum.BM_VERSION
        params['secret'] = enum.BM_SECRET_TEST
        params['xtimestamp'] = req.headers.get('xtimestamp')
        xtoken = base_fn.get_token(params)
        if xtoken != req.headers.get('xtoken'):
            return text('token invalid', 401)
        return await f(view, req)

    return g
