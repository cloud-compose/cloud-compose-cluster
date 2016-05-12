import boto3
import botocore
from cloudcompose.exceptions import CloudComposeException
from cloudcompose.util import require_env_var
from retrying import retry
from os import environ

class InstancePolicyController:
    def __init__(self, cluster_name):
        self.cluster_name = cluster_name
        self.iam = self._get_iam_client()

    def _get_iam_client(self):
        return boto3.client('iam', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def create_instance_policy(self, policy):
        self._iam_create_role(RoleName=self.cluster_name, Path="/", AssumeRolePolicyDocument=self._assume_role)
        self._iam_create_instance_profile(InstanceProfileName=self.cluster_name, Path="/")
        self._iam_add_role_to_instance_profile(InstanceProfileName=self.cluster_name, RoleName=self.cluster_name)
        self._iam_put_role_policy(RoleName=self.cluster_name, PolicyName=self.cluster_name, PolicyDocument=policy)

    def _is_retryable_exception(exception):
        return not isinstance(exception, botocore.exceptions.ClientError) or \
           exception.response["Error"]["Code"] != "EntityAlreadyExists"

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _iam_create_role(self, **kwargs):
        try:
            self.iam.create_role(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] != "EntityAlreadyExists":
                raise ex

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _iam_create_instance_profile(self, **kwargs):
        try:
            self.iam.create_instance_profile(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] != "EntityAlreadyExists":
                raise ex

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _iam_add_role_to_instance_profile(self, **kwargs):
        try:
            self.iam.add_role_to_instance_profile(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] != "LimitExceeded":
                raise ex

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _iam_put_role_policy(self, **kwargs):
        return self.iam.put_role_policy(**kwargs)

    _assume_role = """{
    "Version": "2012-10-17",
    "Statement": [
        {
        "Effect": "Allow",
        "Principal": {
            "Service": [
            "ec2.amazonaws.com"
            ]
        },
        "Action": [
            "sts:AssumeRole"
        ]
        }
    ]
    }
    """
