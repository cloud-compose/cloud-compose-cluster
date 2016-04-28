from pprint import pprint
from os import environ
import logging
from cloudcompose.exceptions import CloudComposeException
import boto3
import botocore
from time import sleep
from retrying import retry

class CloudController:
    def __init__(self):
        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)
        self.ec2 = self._get_ec2_client()

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=self._require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=self._require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def _require_env_var(self, key):
        if key not in environ:
            raise CloudComposeException('Missing %s environment variable' % key)
        return environ[key]

    def up(self, cloud_config):
        #TODO create the cloudwatch log group
        #TODO build cloud_init script
        config_data, _ = cloud_config.config_data('cluster')
        aws = config_data["aws"]
        block_device_map = self._build_block_device_map(aws)
        self._create_instances(config_data['name'], aws, block_device_map)

    def down(self, cloud_config):
        config_data, _ = cloud_config.config_data('cluster')
        aws = config_data["aws"]
        ips = [node['ip'] for node in aws.get('nodes', [])]
        instance_ids = self._instance_ids_from_private_ip(ips)
        if len(instance_ids) > 0:
            self._ec2_terminate_instances(InstanceIds=instance_ids)
            print 'terminated %s' % ','.join(instance_ids)

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

    def _create_instances(self, cluster_name, aws, block_device_map):
        ami = aws['ami']
        keypair = aws['keypair']
        security_groups = aws['security_groups'].split(',')
        instance_type = aws['instance_type']
        terminate_protection = aws.get('terminate_protection', True)
        detailed_monitoring = aws.get('detailed_monitoring', False)
        ebs_optimized = aws.get('ebs_optimized', False)
        instance_ids = {}
        for node in aws.get("nodes", []):
            #TODO need to regenerate the cloud_init script again with NODE_ID set
            max_retries = 6
            retries = 0
            while retries < max_retries:
                retries += 1
                try:
                    response = self._ec2_run_instances(ImageId=ami,
                                    MinCount=1,
                                    MaxCount=1,
                                    KeyName=keypair,
                                    SecurityGroupIds=security_groups,
                                    InstanceType=instance_type,
                                    SubnetId=node["subnet"],
                                    PrivateIpAddress=node["ip"],
                                    BlockDeviceMappings=block_device_map,
                                    DisableApiTermination=terminate_protection,
                                    Monitoring={
                                        "Enabled": detailed_monitoring
                                    },
                                    EbsOptimized=ebs_optimized)
                    instance_id = response['Instances'][0]['InstanceId']
                    instance_ids[node['id']] = instance_id
                    break
                except botocore.exceptions.ClientError as ex:
                    if ex.response["Error"]["Code"] == 'InvalidIPAddress.InUse':
                        print(ex.response["Error"]["Message"])

        for node_id, instance_id in instance_ids.iteritems():
            self._tag_instance(cluster_name, aws.get("tags", {}), node_id, instance_id)

    def _tag_instance(self, cluster_name, tags, node_id, instance_id):
        instance_tags = self._build_instance_tags(cluster_name, node_id, tags)
        self._ec2_create_tags(Resources=[instance_id], Tags=instance_tags)
        print 'created %s-%s (%s)' % (cluster_name, node_id, instance_id)

    def _build_instance_tags(self, cluster_name, node_id, tags):
        instance_tags = [
            {
                'Key': 'ClusterName',
                'Value' : cluster_name
            },
            {
                'Key': 'Name',
                'Value' : ('%s-%s' % (cluster_name, node_id)),
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


    def _build_block_device_map(self, aws):
        block_device_map = []
        for volume in aws.get("volumes", []):
            block_device_map.append(self._create_volume_config(aws['ami'], volume))

        return block_device_map

    def _create_volume_config(self, ami, volume):
        volume_config = {
            "DeviceName": self._find_volume_block(ami, volume),
            "Ebs": {
                "VolumeSize": self._format_size(volume.get("size", "10G")),
                "DeleteOnTermination": volume.get("delete_on_termination", True),
                "VolumeType": volume.get("volume_type", "gp2")
            }
        }
        snapshot = volume.get("snapshot", None)
        if snapshot:
            volume_config["SnapshotId"] = snapshot

        return volume_config

    def _find_volume_block(self, ami, volume):
        if 'block' in volume:
            return volume['block']
        return self._find_block_from_ami(ami)

    def _format_size(self, size):
        size_in_gb = 0
        units = size[-1]
        quantity = int(size[0:len(size)-1])

        if units.lower() == 't':
            return quantity * 1000
        elif units.lower() == 'g':
            return quantity
        elif units.lower() == 'm':
            return quantity / 1000

    def _is_retryable_exception(exception):
        return isinstance(exception, botocore.exceptions.ClientError) and \
           exception.response["Error"]["Code"] == 'InvalidIPAddress.InUse'

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_run_instances(self, **kwargs):
        return self.ec2.run_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_create_tags(self, **kwargs):
        return self.ec2.create_tags(**kwargs)


    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _find_block_from_ami(self, ami):
        block = "/dev/xvda1"
        response = self.ec2.describe_images(ImageIds=[ami])
        if 'Images' in response:
            images = response['Images']
            if len(images) > 0:
                image = images[0]
                if 'RootDeviceName' in image:
                    block = image['RootDeviceName']
        return block

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_terminate_instances(self, **kwargs):
        return self.ec2.terminate_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_instances(self, **kwargs):
        return self.ec2.describe_instances(**kwargs)

