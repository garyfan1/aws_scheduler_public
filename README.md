# This is a Scheduler!
This scheduler accepts HTTP calls which can help you schedule or delete events on amazon Eventbridge.  
The events will trigger and invoke the target lambda function on the specified time.


## Some Important Notes
- This scheduler will create 4 lambda functions:
	- event_bridge_scheduler-dev
	- event_bridge_scheduler-dev-delete_last_month_rules
	- event_bridge_scheduler-dev-delete_yesterday_rules
	- event_bridge_scheduler-dev-the_target_aka_functionB
- This scheduler only supports **one target for each rule**.
- This scheduler is written with little error handling.
- The scheduling date should follow **YYYYMMDDHHMM** format.
- Time is based on UTC +00:00.
- Before deploying, make sure to modify the target function in your `config.json` file.
- Try to avoid naming any other rules starting with 12 digits, this might make `/delete_all` delete your rule.

## /account
- Description: Create an account and returns its write key.
- Method: **POST**
- Request body:
	```json
	{
	  	"account": "Test123"
	}
	```
- Sample response:
	```json
	{
		"account": "Test123",
		"write_key": "737XC4FU4FBCT3MN"		
	}
	```
 
## /login
- Description: Get a jwt token that will last for 10 minutes.
  - `jwt_token` is required whenever you perform an operation such as create/delete an event.
  - You can modify its duration in `config.json`.
- Method: **POST**
- Request body:
	```json
	{
		"account": "Test123",
		"write_key": "737XC4FU4FBCT3MN"
	}
	```
- Sample response:
	```json
	{
		"jwt_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE2MjUwNTUwOTl9.A4F-jzF9CRKc12cIBhNE6mB8EVXYEcT6ngvIHcqln-Y"
	}
	```

## /events
- Description: Schedule an event on EventBridge.
- Method: **POST**
- Required request header: `jwt_token`
- Request body:
	```json
	{
		"target_info": {
			"date_time": "202107170721",
			"callback": "https://lycheeeeee.tw",
			"method": "GET"        
		},
		"data": {
			"user_id": "user123321",
			"message": "hehexdxdxdxd"
		}
	}
	```
- Sample response:
	```json
	{
		"rule_name": "202107170721JTERLG",
		"sch_exp": "cron(21 07 17 07 ? 2021)",
		"function_para": {
			"target_info": {
				"date_time": "202107170721",
				"callback": "https://lycheeeeee.tw",
				"method": "GET"
			},
			"data": {
				"user_id": "user123321",
				"message": "hehexdxdxdxd"
			}
		}
	}
	```

## /events
- Description: Get all the events associated with the account.
- Method: **GET**
- Required request header: `jwt_token`
- Sample response:
	```json
	{
		"event_list": [
			"202106100726D7JWUC",
			"2021061107268I132Y",
			"202106110726Y5LRXJ",
			"2021061307262ETD3N"
		]
	}
	```

## /events/{event_id}
- Description: Get the specified event details.
- Method: **GET**
- Required request header: `jwt_token`
- Sample response:
	```json
	{
		"target_info": {
			"date_time": "202106100726",
			"callback": "https://lycheeeeee.tw",
			"method": "GET"
		},
		"data": {
			"user_id": "Test123",
			"message": "hehexdxdxdxd"
		}
	}
	```

## /events/{event_id}
- Description: Delete the specified event details.
- Method: **DELETE**
- Required request header: `jwt_token`
- Sample response:
	```json
	{
		"msg": "202106100726D7JWUC deleted"
	}
	```
