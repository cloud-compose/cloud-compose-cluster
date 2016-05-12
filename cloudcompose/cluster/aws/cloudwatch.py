import botocore
import boto3
from cloudcompose.util import require_env_var
from retrying import retry
from os import environ

class LogsController:
    def __init__(self):
        self.logs = self._get_logs_client()

    def _get_logs_client(self):
        return boto3.client('logs', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def create_log_group(self, log_group, log_retention):
        if not log_retention:
            #default to 30 days if not set
            log_retention = 30

        self._logs_create_log_group(logGroupName=log_group)
        self._logs_put_retention_policy(logGroupName=log_group, retentionInDays=int(log_retention))

    def _is_retryable_exception(exception):
        return not isinstance(exception, botocore.exceptions.ClientError) or \
           exception.response["Error"]["Code"] != "ResourceAlreadyExistsException"

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _logs_create_log_group(self, **kwargs):
        try:
            self.logs.create_log_group(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                raise ex

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _logs_put_retention_policy(self, **kwargs):
        self.logs.put_retention_policy(**kwargs)
