import hashlib
import time
from conf import conf


def gen_sign(params):
    ps = [conf.APP_SECRET]
    ps.extend([f'{i}{params[i]}' for i in sorted(params)])
    ps.append(conf.APP_SECRET)
    return hashlib.sha1(''.join(ps).encode()).hexdigest()


def gen_urls(params):
    params['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    params['access_token'] = conf.ACCESS_TOKEN
    params['v'] = '1.1'
    sign = gen_sign(params).upper()
    urls = []
    urls.extend([f'{i}={params[i]}' for i in sorted(params)])
    urls.append(f'sign={sign}')
    return '&'.join(urls)
