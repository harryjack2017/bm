import os


class Conf:
    IS_PROD = False
    IS_FAILOVER = False

    PORT = int(os.environ.get('PORT') or 5005)
    REDIS = {
        'addresses': [
            ('127.0.0.1', 6379),
            ('127.0.0.1', 6379),
            ('127.0.0.1', 6379)
        ],
        'password': ''
    }
