import jwt
import pynamodb.exceptions
import bcrypt
import dateutil.relativedelta
from chalice import Chalice, Response, Cron
import boto3
import json
import datetime
import string
import os
import random
import requests
from chalicelib.dynamo_model import Account, AccountEvent


app = Chalice(app_name='event_bridge_scheduler')

lamb = boto3.client("lambda")
event_bridge = boto3.client("events")

# Edit the target here, I call it functionB in the rest of the code
target_function_arn = os.getenv("TARGET_FUNCTION_ARN")

# function for checking if table already exists
def check_table():
    if not Account.exists():
        if os.getenv('STAGE') == 'dev':
            Account.create_table(read_capacity_units=1, write_capacity_units=1, wait=True)
        else:
            Account.create_table(billing_mode='on_demand', wait=True)
    if not AccountEvent.exists():
        if os.getenv('STAGE') == 'dev':
            AccountEvent.create_table(read_capacity_units=1, write_capacity_units=1, wait=True)
        else:
            AccountEvent.create_table(billing_mode='on_demand', wait=True)


# check if the table for storing events and accounts already exist
check_table()


# Function for generating random Ids to avoid coincidences
def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


# Helper function for deleting rules
def delete_rules(rule_obj):
    for rule in rule_obj["Rules"]:
        rule_name = rule["Name"]
        rule_date = rule_name[:12]

        # make sure it only deletes rules with YYYYMMDD prefix
        if rule_date.isnumeric():
            # get the targets of the rule
            targets = event_bridge.list_targets_by_rule(Rule=rule_name)["Targets"]
            target_ids = []
            function_arns = []
            for target in targets:
                target_ids.append(target["Id"])
                function_arns.append(target["Arn"])

            # needs to remove all the rule_targets first before removing the rule itself
            event_bridge.remove_targets(Ids=target_ids, Rule=rule_name)
            # remove the rule itself
            event_bridge.delete_rule(Name=rule_name)

            # remove the invoke:Lambda permission on functionB, so cloudwatch doesn't show up in functionB's console
            for function_arn in function_arns:
                lamb.remove_permission(FunctionName=function_arn, StatementId=rule_name)


# # The API that will delete all the scheduled rules, use with caution!
# @app.route('/delete_all', methods=['DELETE'])
# def delete_all_scheduled_rule():
#     # get all the rules
#     cur_rules = event_bridge.list_rules()
#     delete_rules(cur_rules)
#
#     # repeat the process if there is a NextToken
#     while "NextToken" in cur_rules:
#         cur_rules = event_bridge.list_rules(NextToken=cur_rules['NextToken'])
#         delete_rules(cur_rules)
#
#     res = json.dumps({
#         "msg": "all rules deleted"
#     })
#     response = Response(status_code=200, body=res)
#
#     return response


# Helper function generating yesterday's YYYYMMDD
def get_yesterday_ymd():
    today = datetime.datetime.utcnow()
    yesterday = today - datetime.timedelta(days=1)
    return yesterday.strftime('%Y%m%d')


# @app.route('/delete_yesterday', methods=['DELETE'])
# Runs at 00:01am (UTC) every day, deleting all expired rules.
@app.schedule(Cron(1, 0, '*', '*', '?', '*'))
def delete_yesterday_rules(event):
    # get yesterday's rules
    cur_rules = event_bridge.list_rules(NamePrefix=get_yesterday_ymd())
    delete_rules(cur_rules)

    # repeat the process if there is a NextToken
    while "NextToken" in cur_rules:
        cur_rules = event_bridge.list_rules(NextToken=cur_rules['NextToken'])
        delete_rules(cur_rules)

    print("yesterday's rule deleted")


# Helper function generating lst month's YYYYMM
def get_last_month_ym():
    today = datetime.datetime.utcnow()
    last_month_day = today.replace(day=1) - datetime.timedelta(days=2)
    return last_month_day.strftime('%Y%m')


# @app.route('/delete_last_month', methods=['DELETE'])
# Runs at 00:01am (UTC) every 1st day of the month, deleting those missed by the everyday check.
@app.schedule(Cron(1, 0, 1, '*', '?', '*'))
def delete_last_month_rules(event):
    # get last month's rules
    cur_rules = event_bridge.list_rules(NamePrefix=get_last_month_ym())
    delete_rules(cur_rules)

    # repeat the process if there is a NextToken
    while "NextToken" in cur_rules:
        cur_rules = event_bridge.list_rules(NextToken=cur_rules['NextToken'])
        delete_rules(cur_rules)

    print("last month's rule deleted")


@app.lambda_function(name='the_target_aka_functionB')
def the_handler(event, context):
    target_info = event["target_info"]
    callback_api = target_info["callback"]
    callback_method = target_info["method"]

    message = json.dumps(event["data"])

    headers = {
        'Content-Type': 'application/json'
    }

    requests.request(method=callback_method, headers=headers, url=callback_api, data=message)


@app.route('/account', methods=['POST'])
def create_account():
    account_id = app.current_request.json_body["account"]

    write_key = id_generator(size=16)

    write_hashed = bcrypt.hashpw(write_key.encode(), bcrypt.gensalt(8)).decode()

    try:
        Account.get(account_id)
        res = json.dumps({
            "msg": "account id taken"
        })
        return Response(status_code=403, body=res)
    except pynamodb.exceptions.DoesNotExist:
        Account(account_id=account_id, write_key=write_hashed).save()
        response = {
            "account": account_id,
            "write_key": write_key
        }
        return Response(status_code=200, body=json.dumps(response))
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something went wrong when creating account"
        })
        return Response(status_code=500, body=res)


@app.route('/events', methods=['POST'])
def create_event():
    print("start to schedule the event")

    # account_id = account
    user_input = app.current_request.json_body

    # use jwt to verify
    app.log.debug("start jwt token checking")
    try:
        info = jwt.decode(app.current_request.headers["jwt_token"], key=os.getenv("JWT_SECRET_KEY"), algorithms="HS256")
        account_id = info["account"]
    except KeyError:
        res = json.dumps({
            "msg": "jwt token not provided"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.ExpiredSignatureError:
        res = json.dumps({
            "msg": "jwt token expired"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.InvalidSignatureError:
        res = json.dumps({
            "msg": "invalid jwt token"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something wrong when verifying jwt token"
        })
        return Response(status_code=500, body=res)
    app.log.debug("end jwt token checking")

    if "target_info" not in user_input:
        res = json.dumps({
            "msg": "target_info not provided"
        })
        return Response(status_code=400, body=res)
    else:
        target_info = user_input["target_info"]
        if "date_time" not in target_info:
            res = json.dumps({
                "msg": "date_time not provided"
            })
            return Response(status_code=400, body=res)
        if "callback" not in target_info:
            res = json.dumps({
                "msg": "callback api not provided"
            })
            return Response(status_code=400, body=res)
        if "method" not in target_info:
            res = json.dumps({
                "msg": "callback method not provided"
            })
            return Response(status_code=400, body=res)
    if "data" not in user_input:
        res = json.dumps({
            "msg": "data passing to target not provided"
        })
        return Response(status_code=400, body=res)

    # ==== below is the same as create_schedule ====
    # parse the datetime
    date_time = user_input["target_info"]["date_time"]
    if len(date_time) != 12:
        res = json.dumps({
            "msg": "incorrect date time format"
        })
        return Response(status_code=400, body=res)
    year = date_time[0:4]
    month = date_time[4:6]
    day = date_time[6:8]
    hour = date_time[8:10]
    minute = date_time[10:12]

    try:
        user_dt = datetime.datetime(year=int(year), month=int(month), day=int(day), hour=int(hour), minute=int(minute))
        if user_dt < datetime.datetime.utcnow():
            res = json.dumps({
                "msg": "scheduling a pass event"
            })
            return Response(status_code=400, body=res)
    except:
        res = json.dumps({
            "msg": "incorrect date time format"
        })
        return Response(status_code=400, body=res)

    # generate the name by its datetime follow by a random id
    rule_name = year + month + day + hour + minute + id_generator()
    sch_exp = "cron({min} {hr} {d} {m} ? {y})".format(min=minute, hr=hour, d=day, m=month, y=year)
    function_para = json.dumps(user_input)

    # create a rule on eventbridge
    rule = event_bridge.put_rule(
        Name=rule_name,
        ScheduleExpression=sch_exp
    )
    app.log.debug("after executing put_rule, printing rule")
    app.log.debug(rule)

    # grant functionB permission to be executed by the rule
    statement = lamb.add_permission(
        Action="lambda:InvokeFunction",
        FunctionName=target_function_arn,
        Principal="events.amazonaws.com",
        StatementId=rule_name,
        SourceArn=rule["RuleArn"],
    )
    app.log.debug("after adding add_permission, printing statement")
    app.log.debug(statement)

    # put functionB as a target of the rule
    result = event_bridge.put_targets(
        Rule=rule_name,
        Targets=[
            {
                "Id": rule_name + "-target",
                "Arn": target_function_arn,
                "Input": function_para
            }
        ]
    )
    app.log.debug("after executing put_target, printing result")
    app.log.debug(result)
    # ==== end of create_schedule ====

    # add the event to AccountEvent in dynamodb
    AccountEvent(account_id=account_id, event_id=rule_name).save()

    res = json.dumps(
        {
            "rule_name": rule_name,
            "sch_exp": sch_exp,
            "function_para": user_input
        }
    )

    response = Response(status_code=200, body=res)

    app.log.debug("finish scheduling event")

    return response


@app.route('/events/{rule_name}', methods=['DELETE'])
def delete_event(rule_name):

    # account_id = account
    # use jwt to verify
    app.log.debug("start jwt token checking")
    try:
        info = jwt.decode(app.current_request.headers["jwt_token"], key=os.getenv("JWT_SECRET_KEY"), algorithms="HS256")
        account_id = info["account"]
    except KeyError:
        res = json.dumps({
            "msg": "jwt token not provided"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.InvalidSignatureError:
        res = json.dumps({
            "msg": "invalid jwt token"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.ExpiredSignatureError:
        res = json.dumps({
            "msg": "jwt token expired"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something wrong when verifying jwt token"
        })
        return Response(status_code=500, body=res)
    app.log.debug("end jwt token checking")

    # checks if the user owns the event, if not, reject the request
    try:
        AccountEvent.get(account_id, rule_name)
    except pynamodb.exceptions.DoesNotExist:
        res = json.dumps({
            "msg": "Either you don't have the permission to delete, or the rule does not exist"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        res = json.dumps({
            "msg": "something went wrong when fetching the event"
        })
        app.log.error(e)
        return Response(status_code=500, body=res)

    # refactor the input so the helper function (delete_rules) can accept it
    rule_names = [rule_name]
    temp = {"Rules": []}
    for name in rule_names:
        temp["Rules"].append({"Name": name})
    delete_rules(temp)

    # remove the event from AccountEvent
    AccountEvent.get(account_id, rule_name).delete()

    res = json.dumps({
        "msg": rule_name + " deleted"
    })
    response = Response(status_code=200, body=res)
    return response


@app.route('/events', methods=['GET'])
def get_events():

    # account_id = account

    # use jwt to verify
    app.log.debug("start jwt token checking")
    try:
        info = jwt.decode(app.current_request.headers["jwt_token"], key=os.getenv("JWT_SECRET_KEY"), algorithms="HS256")
        account_id = info["account"]
    except KeyError:
        res = json.dumps({
            "msg": "jwt token not provided"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.InvalidSignatureError:
        res = json.dumps({
            "msg": "invalid jwt token"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.ExpiredSignatureError:
        res = json.dumps({
            "msg": "jwt token expired"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something wrong when verifying jwt token"
        })
        return Response(status_code=500, body=res)
    app.log.debug("end jwt token checking")

    # fetch events from AccountEvent by account_id in dynamodb
    event_list = []
    for event in AccountEvent.query(hash_key=account_id):
        event_list.append(event.event_id)

    if not event_list:
        res = json.dumps({
            "msg": "no event yet"
        })
        return Response(status_code=200, body=res)

    response = {
        "event_list": event_list
    }

    return Response(status_code=200, body=json.dumps(response))


@app.route('/events/{rule_name}', methods=['GET'])
def get_event_details(rule_name):

    # account_id = account

    # use jwt to verify instead
    app.log.debug("start jwt token checking")
    try:
        info = jwt.decode(app.current_request.headers["jwt_token"], key=os.getenv("JWT_SECRET_KEY"), algorithms="HS256")
        account_id = info["account"]
    except KeyError:
        res = json.dumps({
            "msg": "jwt token not provided"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.InvalidSignatureError:
        res = json.dumps({
            "msg": "invalid jwt token"
        })
        return Response(status_code=403, body=res)
    except jwt.exceptions.ExpiredSignatureError:
        res = json.dumps({
            "msg": "jwt token expired"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something wrong when verifying jwt token"
        })
        return Response(status_code=500, body=res)
    app.log.debug("end jwt token checking")

    # checks if the user owns the event, if not, reject the request
    try:
        AccountEvent.get(account_id, rule_name)
    except pynamodb.exceptions.DoesNotExist:
        res = json.dumps({
            "msg": "Either you don't have the permission to delete, or the rule does not exist"
        })
        return Response(status_code=403, body=res)
    except Exception as e:
        app.log.error(e)
        res = json.dumps({
            "msg": "something went wrong when fetching event from dynamo"
        })
        return Response(status_code=403, body=res)

    # get the input data back using list_target_by_rule
    input_data = event_bridge.list_targets_by_rule(Rule=rule_name)["Targets"][0]["Input"]

    return Response(status_code=200, body=input_data)


@app.route('/login', methods=['POST'])
def get_jwt():

    input_body = app.current_request.json_body
    # verifying write key
    try:
        account_id = input_body["account"]
        write_key = input_body["write_key"]
        account_info = Account.get(account_id)
        account_key = account_info.write_key
        if not bcrypt.checkpw(write_key.encode(), account_key.encode()):
            res = json.dumps({
                "msg": "permission denied"
            })
            return Response(status_code=403, body=res)
    except pynamodb.exceptions.DoesNotExist:
        res = json.dumps({
            "msg": "account name does not exist"
        })
        return Response(status_code=403, body=res)
    except KeyError:
        res = json.dumps({
            "msg": "account name or write_key not provided"
        })
        return Response(status_code=403, body=res)
    except:
        res = json.dumps({
            "msg": "something wrong when verifying write key"
        })
        return Response(status_code=500, body=res)

    duration = int(os.getenv("JWT_DURATION_MINUTES"))
    token_dic = {
        "exp": datetime.datetime.utcnow() + dateutil.relativedelta.relativedelta(minutes=duration),
        "account": account_id
    }
    jwt_token = jwt.encode(token_dic, key=os.getenv("JWT_SECRET_KEY"), algorithm="HS256")

    res = json.dumps({"jwt_token": jwt_token})
    return Response(status_code=200, body=res)

