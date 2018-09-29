import asyncio
import ujson
from time import time
from aiohttp import ClientSession, ClientTimeout
from conf import enum
from utils.log import logger, print_excp

session: ClientSession = None
cdn_addr_task = None
HTTP_TIMEOUT = 3
search_headers = {'x-platform': 'main'}


async def init_session():
    global session
    session = ClientSession(timeout=ClientTimeout(total=HTTP_TIMEOUT))
    logger.info('http client init done')


async def close_session():
    global session

    if session is not None:
        try:
            await session.close()
        except Exception as e:
            print_excp(e)


def timing(f):
    async def g(*args, **kwargs):
        start = time()

        try:
            res = await f(*args, **kwargs)
        except Exception:
            stop = time()
            ms = int(1000 * (stop - start))
            logger.error(f'{ms}ms for http error {f.__name__}')
            raise

        stop = time()
        ms = int(1000 * (stop - start))
        logger.debug(f'{ms}ms for http {f.__name__}')

        return res

    return g


# POST REQUEST
async def post_request(url, body=None, data=None, headers=None, need_res=True):
    async with session.post(url, json=body, data=data, headers=headers) as resp:
        if resp.status != 200:
            logger.error(f'http status {resp.status} for {url}')

        if need_res is True:
            return await resp.text()
        else:
            return resp


# GET REQUEST
async def get_request(url, params=None, headers=None):
    async with session.get(url, params=params, headers=headers) as resp:
        if resp.status != 200:
            logger.error(f'http status {resp.status} for {url}')

        return await resp.text()


'''
    All functions which use http request below
'''


@timing
async def test_get_api(req, urls, headers):
    res = await get_request(f'{enum.BM_TEST_SERVER}{enum.BM_URL}{urls}', headers=headers)
    return res


@timing
async def test_post_api(req, urls, body=None, data=None, headers=None):
    res = await post_request(f'{enum.BM_TEST_SERVER}{enum.BM_URL}{urls}', body=body, data=data, headers=headers)
    return res


@timing
async def get_api(req, urls):
    return await get_request(f'{enum.BM_SERVER}?{urls}')


@timing
async def post_api(req, urls):
    return await post_request(f'{enum.BM_SERVER}?{urls}')
