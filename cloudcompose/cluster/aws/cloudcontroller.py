from os import environ
import logging
from cloudcompose.exceptions import CloudComposeException
from iam import InstancePolicyController
from ebs import EBSController
from cloudwatch import LogsController
from util import require_env_var
import boto3
import botocore
from time import sleep
from retrying import retry
from pprint import pprint

class CloudController:
    def __init__(self, cloud_config):
        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)
        self.cloud_config = cloud_config
        self.config_data = cloud_config.config_data('cluster')
        self.aws = self.config_data['aws']
        self.log_driver = self.config_data.get('logging', {}).get('driver')
        self.log_group = self.config_data.get('logging', {}).get('meta', {}).get('group')
        self.log_retention = self.config_data.get('logging', {}).get('meta', {}).get('retention')
        self.instance_policy = self.aws.get('instance_policy')
        self.cluster_name = self.config_data['name']
        self.ec2 = self._get_ec2_client()

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def up(self, cloud_init=None, no_snapshots=False):
        block_device_map = self._block_device_map(no_snapshots)
        if self.log_driver == 'awslogs':
            self._create_log_group(self.log_group, self.log_retention)
        self._create_instances(block_device_map, cloud_init)

    def down(self):
        ips = [node['ip'] for node in self.aws.get('nodes', [])]
        instance_ids = self._instance_ids_from_private_ip(ips)
        if len(instance_ids) > 0:
            self._ec2_terminate_instances(InstanceIds=instance_ids)
            print 'terminated %s' % ','.join(instance_ids)

    def _block_device_map(self, no_snapshots):
        controller = EBSController(self.ec2, self.cluster_name)
        default_device = self._find_device_from_ami(self.aws['ami'])
        return controller.block_device_map(self.aws['volumes'], default_device, no_snapshots)

    def _instance_ids_from_private_ip(self, ips):
        instance_ids = []
        filters = [
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "private-ip-address", "Values": ips}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                if 'InstanceId' in instance:
                    instance_ids.append(instance['InstanceId'])

        return instance_ids

    def _create_instance_args(self, block_device_map):
        ami = self.aws['ami']
        keypair = self.aws['keypair']
        security_groups = self.aws['security_groups'].split(',')
        instance_type = self.aws['instance_type']
        terminate_protection = self.aws.get('terminate_protection', True)
        detailed_monitoring = self.aws.get('detailed_monitoring', False)
        ebs_optimized = self.aws.get('ebs_optimized', False)
        return {
            'ImageId': ami,
            'MinCount': 1,
            'MaxCount': 1,
            'KeyName': keypair,
            'SecurityGroupIds': security_groups,
            'InstanceType': instance_type,
            'BlockDeviceMappings': block_device_map,
            'DisableApiTermination': terminate_protection,
            'Monitoring': { 'Enabled': detailed_monitoring },
            'EbsOptimized': ebs_optimized
        }

    def _create_instances(self, block_device_map, cloud_init):
        instance_ids = {}
        kwargs = self._create_instance_args(block_device_map)
        if self.instance_policy:
            self._create_instance_policy(self.instance_policy)
            kwargs['IamInstanceProfile'] = {'Name': self.cluster_name}

        for node in self.aws.get("nodes", []):
            private_ip = node["ip"]
            kwargs['SubnetId'] = node["subnet"]
            kwargs['PrivateIpAddress'] = private_ip

            if cloud_init:
                cloud_init_script = cloud_init.build(self.config_data, node_id=node['id'])
                kwargs['UserData'] = cloud_init_script

            max_retries = 6
            retries = 0
            while retries < max_retries:
                retries += 1
                try:
                    response = self._ec2_run_instances(private_ip, **kwargs)
                    if response:
                        instance_id = response['Instances'][0]['InstanceId']
                        instance_ids[node['id']] = instance_id
                    break
                except botocore.exceptions.ClientError as ex:
                    if ex.response["Error"]["Code"] == 'InvalidIPAddress.InUse':
                        print(ex.response["Error"]["Message"])
                    else:
                        print(ex.response["Error"]["Message"])

        for node_id, instance_id in instance_ids.iteritems():
            self._tag_instance(self.aws.get("tags", {}), node_id, instance_id)

    def _create_instance_policy(self, instance_policy):
        controller = InstancePolicyController(self.cluster_name)
        controller.create_instance_policy(instance_policy)

    def _create_log_group(self, log_group, log_retention):
        controller = LogsController()
        controller.create_log_group(log_group, log_retention)

    def _tag_instance(self, tags, node_id, instance_id):
        instance_tags = self._build_instance_tags(node_id, tags)
        self._ec2_create_tags(Resources=[instance_id], Tags=instance_tags)
        print 'created %s-%s (%s)' % (self.cluster_name, node_id, instance_id)

    def _build_instance_tags(self, node_id, tags):
        instance_tags = [
            {
                'Key': 'ClusterName',
                'Value': self.cluster_name
            },
            {
                'Key': 'Name',
                'Value' : ('%s-%s' % (self.cluster_name, node_id)),
            },
            {
                'Key': 'NodeId',
                'Value' : str(node_id),
            }
        ]

        for key, value in tags.items():
            instance_tags.append({
                "Key": key,
                "Value" : str(value),
            })

        return instance_tags


    def _is_retryable_exception(exception):
        return isinstance(exception, botocore.exceptions.ClientError) and \
           exception.response["Error"]["Code"] == 'InvalidIPAddress.InUse'

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _find_existing_instance_id(self, private_ip):
        filters = [
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
            {"Name": "private-ip-address", "Values": [private_ip]},
            {"Name": "tag:ClusterName", "Values": [self.cluster_name]}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                if 'InstanceId' in instance:
                    return instance['InstanceId']

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_run_instances(self, private_ip, **kwargs):
        try:
            response = self.ec2.run_instances(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "InvalidIPAddress.InUse":
                instance_id = self._find_existing_instance_id(private_ip)
                if instance_id:
                    print "skipping %s (%s)" % (private_ip, instance_id)
                    return None
            raise ex

        return response

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_create_tags(self, **kwargs):
        return self.ec2.create_tags(**kwargs)


    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _find_device_from_ami(self, ami):
        device = "/dev/xvda1"
        response = self.ec2.describe_images(ImageIds=[ami])
        if 'Images' in response:
            images = response['Images']
            if len(images) > 0:
                image = images[0]
                if 'RootDeviceName' in image:
                    device = image['RootDeviceName']
        return device

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_terminate_instances(self, **kwargs):
        return self.ec2.terminate_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_instances(self, **kwargs):
        return self.ec2.describe_instances(**kwargs)

