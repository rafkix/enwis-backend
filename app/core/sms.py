import httpx

from app.core.config import settings


class LocalSMSGateway:
    def __init__(self):
        self.url = settings.SMS_GATEWAY_URL

    async def send(self, phone: str, message: str):
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(self.url, json={"phone": phone, "message": message})
            if res.status_code != 200:
                raise Exception(f"SMS failed: {res.text}")
            return res.json()
