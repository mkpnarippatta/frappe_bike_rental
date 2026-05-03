import frappe, requests, json

frappe.init("rental.local")
frappe.connect()
s = frappe.get_single("Rental Notification Settings")
token = s.get_password("whatsapp_access_token")
headers = {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json"}

# Try creating the template via the phone number ID
url = "https://graph.facebook.com/v22.0/998547943351064/message_templates"

payload = {
    "name": "dumzy_bike_otp_authentication",
    "language": "en_US",
    "category": "AUTHENTICATION",
    "components": [
        {
            "type": "BODY",
            "text": "Your Bike Rental OTP is: {{1}}. It expires in 5 minutes.",
            "example": {"body_text": [["295525"]]}
        }
    ]
}

resp = requests.post(url, headers=headers, json=payload, timeout=15)
print("Status:", resp.status_code)
print("Response:", json.dumps(resp.json(), indent=2))

frappe.db.close()
