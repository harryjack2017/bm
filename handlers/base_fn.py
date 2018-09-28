import hashlib
import time
from conf import enum

ENCODING = 'utf-8'


def gen_sign(params):
    ps = [enum.APP_SECRET]
    ps.extend([f'{i}{params[i]}' for i in sorted(params)])
    ps.append(enum.APP_SECRET)
    return hashlib.sha1(''.join(ps).encode()).hexdigest()


def gen_urls(params):
    params['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    params['access_token'] = enum.BM_ACCESS_TOKEN
    params['v'] = '1.1'
    sign = gen_sign(params).upper()
    urls = []
    urls.extend([f'{i}={params[i]}' for i in sorted(params)])
    urls.append(f'sign={sign}')
    return '&'.join(urls)


def md5_str(str):
    hl = hashlib.md5()
    hl.update(str.encode(encoding=ENCODING))
    return hl.hexdigest()


def get_token(params):
    ps = [enum.BM_KEY_TEST]
    ps.extend([f'{i}{params[i]}' for i in sorted(params)])
    ps.append(enum.BM_KEY_TEST)
    return md5_str(''.join(ps))


def prepare_test_param(params):
    xtimestamp = time.strftime("%Y%m%d%H%M%S", time.localtime(time.time()))
    config = {
        "secret": enum.BM_SECRET_TEST,
        "v": "v1",
        "xtimestamp": xtimestamp
    }
    for p in params:
        config[p] = params[p]

    return get_token(config), xtimestamp
