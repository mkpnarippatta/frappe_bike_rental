import frappe, requests, json

frappe.init("rental.local")
frappe.connect()
s = frappe.get_single("Rental Notification Settings")
token = s.get_password("whatsapp_access_token")
headers = {"Authorization": "Bearer {}".format(token)}

# Try to get the WABA from the app
url = "https://graph.facebook.com/v22.0/3450372248446862?fields=name"
resp = requests.get(url, headers=headers, timeout=10)
print("App:", json.dumps(resp.json(), indent=2))

# Try to find the WABA via the phone number
url2 = "https://graph.facebook.com/v22.0/998547943351064?fields=id,display_phone_number,verified_name,code_verification_status,platform_type"
resp2 = requests.get(url2, headers=headers, timeout=10)
print("\nPhone:", json.dumps(resp2.json(), indent=2))

# Try to list templates via the business management API
# The token is a system token - maybe waba is accessible via the app
url3 = "https://graph.facebook.com/v22.0/3450372248446862/whatsapp_business_accounts"
resp3 = requests.get(url3, headers=headers, timeout=10)
print("\nWABA from app:", json.dumps(resp3.json(), indent=2)[:500])

# If found waba_id, list templates
data3 = resp3.json()
if "data" in data3 and len(data3["data"]) > 0:
    waba_id = data3["data"][0]["id"]
    url4 = "https://graph.facebook.com/v22.0/{}/message_templates".format(waba_id)
    resp4 = requests.get(url4, headers=headers, timeout=10)
    print("\nTemplates:", json.dumps(resp4.json(), indent=2)[:2000])

frappe.db.close()
