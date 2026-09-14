import requests

from wallets.infrastructure.third_party import ThirdPartyTransferClient


def request_third_party_deposit():
    response = requests.post("http://localhost:8010/")
    return response.json()


def request_third_party_transfer(**kwargs):
    return ThirdPartyTransferClient().transfer(**kwargs)
