import requests

url = "https://api.enwis.uz/api/v1/auth/register/send-code"

# Server talab qilayotgan barcha maydonlarni kiritamiz
payload = {
    "full_name": "Shohjahon",
    "phone": "+998933288806",
    "phoneNumber": "+998933288806",
    "password": "sizning_parolingiz"
}

headers = {
    "Content-Type": "application/json",
    "Origin": "https://app.enwis.uz",
    "Referer": "https://app.enwis.uz/"
}

response = requests.post(url, json=payload, headers=headers)

print("Status kod:", response.status_code)
print("Server javobi (Response):", response.text)