import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferResult:
    status: str
    http_status: int | None = None
    response_payload: dict = field(default_factory=dict)
    error_message: str = ""


class TransferStatus:
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ThirdPartyTransferClient:
    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or settings.THIRD_PARTY_TRANSFER_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.THIRD_PARTY_TRANSFER_TIMEOUT

    def transfer(self, *, wallet_uuid, amount, withdrawal_id):
        payload = {
            "wallet_uuid": str(wallet_uuid),
            "amount": amount,
            "withdrawal_id": withdrawal_id,
        }

        try:
            response = requests.post(self.base_url + "/", json=payload, timeout=self.timeout)

        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.warning(
                "Third-party transfer request failed ambiguously.",
                extra={"withdrawal_id": withdrawal_id, "wallet_uuid": str(wallet_uuid), "error": str(exc)},
            )
            return TransferResult(status=TransferStatus.UNKNOWN, error_message=str(exc))

        except requests.RequestException as exc:
            logger.exception(
                "Third-party transfer request raised an unexpected requests error.",
                extra={"withdrawal_id": withdrawal_id, "wallet_uuid": str(wallet_uuid)},
            )
            return TransferResult(status=TransferStatus.UNKNOWN, error_message=str(exc))

        try:
            body = response.json()

        except ValueError:
            body = {"raw": response.text}

        service_status = body.get("status")
        service_data = body.get("data")
        if response.ok and (service_status == 200 or service_data == "success"):
            logger.info(
                "Third-party transfer succeeded.",
                extra={
                    "withdrawal_id": withdrawal_id,
                    "wallet_uuid": str(wallet_uuid),
                    "http_status": response.status_code,
                    "response_payload": body,
                },
            )
            return TransferResult(
                status=TransferStatus.SUCCESS, http_status=response.status_code, response_payload=body
            )

        if service_status and int(service_status) >= 400:
            logger.warning(
                "Third-party transfer failed explicitly.",
                extra={
                    "withdrawal_id": withdrawal_id,
                    "wallet_uuid": str(wallet_uuid),
                    "http_status": response.status_code,
                    "response_payload": body,
                },
            )
            return TransferResult(
                status=TransferStatus.FAILED,
                http_status=response.status_code,
                response_payload=body,
                error_message=str(service_data or service_status),
            )

        if response.status_code >= 500:
            logger.warning(
                "Third-party transfer returned an ambiguous server error.",
                extra={
                    "withdrawal_id": withdrawal_id,
                    "wallet_uuid": str(wallet_uuid),
                    "http_status": response.status_code,
                    "response_payload": body,
                },
            )
            return TransferResult(
                status=TransferStatus.UNKNOWN,
                http_status=response.status_code,
                response_payload=body,
                error_message="Third-party service error.",
            )

        logger.warning(
            "Third-party transfer failed.",
            extra={
                "withdrawal_id": withdrawal_id,
                "wallet_uuid": str(wallet_uuid),
                "http_status": response.status_code,
                "response_payload": body,
            },
        )
        return TransferResult(
            status=TransferStatus.FAILED,
            http_status=response.status_code,
            response_payload=body,
            error_message=str(service_data or "Transfer failed."),
        )
