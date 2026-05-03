import frappe, requests, json

frappe.init("rental.local")
frappe.connect()
s = frappe.get_single("Rental Notification Settings")
token = s.get_password("whatsapp_access_token")
headers = {"Authorization": "Bearer {}".format(token)}

# The user_id from the token debug was 122100221780598233
user_id = "122100221780598233"

# Try to get the businesses the user has access to
url = "https://graph.facebook.com/v22.0/{}/?fields=id,name,businesses".format(user_id)
resp = requests.get(url, headers=headers, timeout=10)
print("User:", json.dumps(resp.json(), indent=2)[:1000])

# Try the phone number with more detailed fields
url2 = "https://graph.facebook.com/v22.0/998547943351064/?fields=id,display_phone_number,verified_name,code_verification_status,platform_type,on_behalf_of_business_info,whatsapp_business_api_data"
resp2 = requests.get(url2, headers=headers, timeout=10)
print("\nPhone details:", json.dumps(resp2.json(), indent=2)[:1000])

# Try to get subscriber applications
url3 = "https://graph.facebook.com/v22.0/998547943351064/subscriber_applications"
resp3 = requests.get(url3, headers=headers, timeout=10)
print("\nSubscriber apps:", json.dumps(resp3.json(), indent=2)[:500])

# The webhook config has an applications field
url4 = "https://graph.facebook.com/v22.0/998547943351064/?fields=webhook_configuration"
resp4 = requests.get(url4, headers=headers, timeout=10)
print("\nWebhook:", json.dumps(resp4.json(), indent=2)[:500])

frappe.db.close()
