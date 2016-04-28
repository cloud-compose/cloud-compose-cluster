from pprint import pprint
from os import environ
import logging
from cloudcompose.exceptions import CloudComposeException
import boto3
import botocore
from time import sleep

class CloudController:
    def __init__(self):
        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)
        self.ec2 = self._get_ec2_client()
        self.max_retries = 5
        self.retry_sleep_interval = 1

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

    def _create_instances(self, cluster_name, aws, block_device_map):
        ami = aws['ami']
        keypair = aws['keypair']
        security_groups = aws['security_groups'].split(',')
        instance_type = aws['instance_type']
        terminate_protection = aws.get('terminate_protection', True)
        detailed_monitoring = aws.get('detailed_monitoring', False)
        ebs_optimized = aws.get('ebs_optimized', False)
        for node in aws.get("nodes", []):
            #TODO need to regenerate the cloud_init script again with NODE_ID set
            instance_id = None
            retries = self.max_retries
            while retries > 0:
                retries -= 1
                try:
                    response = self.ec2.run_instances(
                            ImageId=ami,
                            MinCount=1,
                            MaxCount=1,
                            KeyName=keypair,
                            SecurityGroupIds=security_groups,
                            InstanceType=instance_type,
                            SubnetId=node["subnet"],
                            PrivateIpAddress=node["ip"],
                            BlockDeviceMappings=block_device_map,
                            #TODO UserData=user_data["cloud_init"],
                            #TODO IamInstanceProfile=_get_iam_instance_profile(user_data),
                            DisableApiTermination=terminate_protection,
                            Monitoring={
                                "Enabled": detailed_monitoring
                            },
                            EbsOptimized=ebs_optimized)
                    instance_id = response['Instances'][0]['InstanceId']
                    break
                except botocore.exceptions.ClientError as ex:
                    self.logger.error(ex)
                    sleep(self.retry_sleep_interval)

            if instance_id:
                self._tag_instance(cluster_name, aws.get("tags", {}), node['id'], instance_id)

    def _tag_instance(self, cluster_name, tags, node_id, instance_id):
        instance_tags = self._build_instance_tags(cluster_name, node_id, tags)
        retries = self.max_retries
        while retries > 0:
            retries -= 1
            try:
                self.ec2.create_tags(Resources=[instance_id], Tags=instance_tags)
                break
            except botocore.exceptions.ClientError as ex:
                self.logger.error(ex)
                sleep(self.retry_sleep_interval)


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

    def _find_block_from_ami(self, ami):
        retries = self.max_retries
        while retries > 0:
            retries -= 1
            try:
                block = "/dev/xvda1"
                response = self.ec2.describe_images(ImageIds=[ami])
                if 'Images' in response:
                    images = response['Images']
                    if len(images) > 0:
                        image = images[0]
                        if 'RootDeviceName' in image:
                            block = image['RootDeviceName']
                return block
            except botocore.exceptions.ClientError as ex:
                self.logger.error(ex)
                sleep(self.retry_sleep_interval)

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
