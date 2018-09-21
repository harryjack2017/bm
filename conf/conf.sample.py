import os


class Conf:
    IS_PROD = False
    IS_FAILOVER = False

    PORT = int(os.environ.get('PORT') or 5005)
