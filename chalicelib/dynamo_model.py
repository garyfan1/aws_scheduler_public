from datetime import datetime
# from pynamodb.indexes import LocalSecondaryIndex, GlobalSecondaryIndex, AllProjection, IncludeProjection
from pynamodb.models import Model
from pynamodb.attributes import (
    UnicodeAttribute, NumberAttribute, UnicodeSetAttribute, UTCDateTimeAttribute, JSONAttribute, MapAttribute
)

import os
import json


class Account(Model):
    class Meta:
        region = os.getenv('AWS_REGION_PG')
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID_PG')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY_PG')
        table_name = 'SchedulerAccount' + os.getenv('STAGE')
        # table_name = 'SchedulerAccount'



    account_id = UnicodeAttribute(hash_key=True)  # e.g. AAAABBBB_U123123123
    # read_key = UnicodeAttribute(null=True)  # it's used to list event
    write_key = UnicodeAttribute(null=True)  # it's used to create event, delete event


class AccountEvent(Model):
    class Meta:
        region = os.getenv('AWS_REGION_PG')
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID_PG')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY_PG')
        table_name = 'SchedulerAccountEvent' + os.getenv('STAGE')
        # table_name = 'SchedulerAccountEvent'


    account_id = UnicodeAttribute(hash_key=True)
    event_id = UnicodeAttribute(range_key=True)








