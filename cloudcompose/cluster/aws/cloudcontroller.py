from os import environ
from os.path import abspath, dirname, join, isfile
import logging
from cloudcompose.exceptions import CloudComposeException
from iam import InstancePolicyController
from ebs import EBSController
from cloudwatch import LogsController
from cloudcompose.util import require_env_var
import boto3
import botocore
from time import sleep
import time, datetime
from retrying import retry
from pprint import pprint

class CloudController:
    def __init__(self, cloud_config, ec2_client=None, asg_client=None):
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
        self.ec2 = ec2_client or self._get_ec2_client()
        self.asg = asg_client or self._get_asg_client()

    def _get_ec2_client(self):
        return boto3.client('ec2', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def _get_asg_client(self):
        return boto3.client('autoscaling', aws_access_key_id=require_env_var('AWS_ACCESS_KEY_ID'),
                            aws_secret_access_key=require_env_var('AWS_SECRET_ACCESS_KEY'),
                            region_name=environ.get('AWS_REGION', 'us-east-1'))

    def up(self, cloud_init=None, use_snapshots=True, upgrade_image=False):
        self.aws['ami'] = self._resolve_ami_name(upgrade_image)
        block_device_map = self._block_device_map(use_snapshots)
        if self.log_driver == 'awslogs':
            self._create_log_group(self.log_group, self.log_retention)
        if self.aws.get('asg'):
            self._create_asg(block_device_map, cloud_init)
        else:
            self._create_instances(block_device_map, cloud_init)

    def down(self):
        if self.aws.get('asg'):
            asg_name = self.cluster_name
            try:
                self._asg_update_auto_scaling_group(
                                        AutoScalingGroupName=asg_name,
                                        MinSize=0,
                                        MaxSize=0,
                                        DesiredCapacity=0)
                print 'auto scaling group %s size is now 0' % asg_name
            except botocore.exceptions.ClientError as ex:
                if ex.response["Error"]["Code"] == 'ValidationError':
                    print 'auto scaling group %s does not exist' % asg_name
                else:
                    raise ex

        else:
            ips = [node['ip'] for node in self.aws.get('nodes', [])]
            instance_ids = self._instance_ids_from_private_ip(ips)
            if len(instance_ids) > 0:
                self._ec2_terminate_instances(InstanceIds=instance_ids)
                print 'terminated %s' % ','.join(instance_ids)

    def cleanup(self):
        if self.aws.get('asg'):
            asg_name = self.cluster_name
            asg_details = self._describe_asg(asg_name)

            asg_lc = asg_details["AutoScalingGroups"][0]["LaunchConfigurationName"]
            asg_instances = len(asg_details["AutoScalingGroups"][0]["Instances"])

            if asg_instances != 0:
                print 'unable to delete autoscaling group %s because of %s active instances' % (asg_name, asg_instances)
                print 'run cloud-compose cluster down first or wait for instances to terminate'
            else:
                self._delete_asg(asg_name)
                print 'deleted autoscaling group %s' % asg_name

                self._delete_launch_config(asg_lc)
                print 'deleted launch configuration %s' % asg_lc
        else:
            print 'cleanup has no effect for non-ASG clusters'
            print 'use cloud-compose cluster down to remove instances'

    def _resolve_ami_name(self, upgrade_image):
        if self.aws['ami'].startswith('ami-'):
            return self.aws['ami']

        ami = None
        message = None

        if not upgrade_image and not self.aws.get('asg'):
            ami = self._find_ami_on_cluster()
            if ami:
                message = 'as used on other cluster nodes'

        if not ami:
            ami, creation_date = self._find_ami_by_name_tag()
            if ami:
                message = 'created on %s' % creation_date

        if ami:
            print 'ami %s resolves to %s %s' % (self.aws['ami'], ami, message)
        else:
            raise CloudComposeException('Unable to resolve AMI %s' % self.aws['ami'])

        return ami

    def _find_ami_by_name_tag(self):
        ami = self.aws['ami']
        images = self._ec2_describe_images(Filters=[{'Name': 'tag:Name', 'Values': [ami]}])

        for image in sorted(images, reverse=True, key=lambda image: image['CreationDate']):
            if 'ImageId' in image:
                # get the newest image with the name tag that matches
                return (image['ImageId'], image['CreationDate'])

    def _find_ami_on_cluster(self):
        filters = [
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
            {"Name": "tag:ClusterName", "Values": [self.cluster_name]}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                if 'ImageId' in instance:
                    return instance['ImageId']

    def _block_device_map(self, use_snapshots):
        controller = EBSController(self.ec2, self.cluster_name)
        default_device = self._find_device_from_ami(self.aws['ami'])
        return controller.block_device_map(self.aws['volumes'], default_device, use_snapshots)

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

    def security_groups(self):
        security_groups = self.aws['security_groups']
        if isinstance(security_groups, basestring):
            security_groups = security_groups.split(',')
        return security_groups

    def _create_instance_args(self, block_device_map):
        ami = self.aws['ami']
        keypair = self.aws['keypair']
        security_groups = self.security_groups()
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

    def _create_asg_args(self, block_device_map, cloud_init):
        asg_name      = self.cluster_name
        subnet_list   = self.aws['asg']['subnets']
        vpc_zones     = ', '.join(subnet_list)
        cluster_size  = len(subnet_list)
        redundancy    = self.aws['asg'].get('redundancy', 1)
        lc_name       = self._build_launch_config(block_device_map, cloud_init)
        term_policies = ["OldestLaunchConfiguration", "OldestInstance", "Default"]
        tags = self.aws.get("tags", {})
        tags['Name'] = self.cluster_name
        instance_tags = self._build_instance_tags(tags)

        return {
            'AutoScalingGroupName': asg_name,
            'LaunchConfigurationName': lc_name,
            'MinSize': cluster_size * redundancy,
            'MaxSize': cluster_size * redundancy,
            'DesiredCapacity': cluster_size * redundancy,
            'LoadBalancerNames': [],
            'VPCZoneIdentifier': vpc_zones,
            'TerminationPolicies': term_policies,
            'Tags': instance_tags
        }

    def _create_asg(self, block_device_map, cloud_init):
        kwargs = self._create_asg_args(block_device_map, cloud_init)
        try:
            self._asg_create(**kwargs)
        except botocore.exceptions.ClientError as ex:
            raise ex

    def _create_instances(self, block_device_map, cloud_init):
        instances = {}
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
                        instance = response['Instances'][0]
                        instances[node['id']] = instance
                    break
                except botocore.exceptions.ClientError as ex:
                    print(ex.response["Error"]["Message"])

        for node_id, instance in instances.iteritems():
            self._tag_instance(self.aws.get("tags", {}), node_id, instance)

    def _create_instance_policy(self, instance_policy):
        controller = InstancePolicyController(self.cluster_name)
        controller.create_instance_policy(instance_policy)

    def _create_log_group(self, log_group, log_retention):
        controller = LogsController()
        controller.create_log_group(log_group, log_retention)

    def _tag_instance(self, tags, node_id, instance):
        tags['NodeId'] = str(node_id)
        tags['Name'] = '%s-%s' % (self.cluster_name, node_id)
        instance_tags = self._build_instance_tags(tags)
        self._ec2_create_tags(Resources=[instance['InstanceId']], Tags=instance_tags)
        print 'created instance %s %s-%s (%s)' % (instance['InstanceId'], self.cluster_name, node_id, instance['PrivateIpAddress'])

    def _build_instance_tags(self, tags):
        instance_tags = [
            {
                'Key': 'ClusterName',
                'Value': self.cluster_name
            }
        ]

        for key, value in tags.items():
            instance_tags.append({
                "Key": key,
                "Value" : str(value),
            })

        return instance_tags

    def _launch_config_args(self, block_device_map, cloud_init):
        cluster_name = self.cluster_name
        timestamp    = time.time()
        string_time  = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d-%H-%M-%S")
        lc_name      = "%s-%s" % (cluster_name, string_time)

        if cloud_init:
            cloud_init_script = cloud_init.build(self.config_data, node_id=cluster_name)


        launch_config_args = {
            "LaunchConfigurationName": lc_name,
            "ImageId": self.aws['ami'],
            "SecurityGroups": self.security_groups(),
            "InstanceType": self.aws['instance_type'],
            "UserData": cloud_init_script,
            "KeyName": self.aws['keypair'],
            "EbsOptimized": self.aws.get("ebs_optimized", False),
            "BlockDeviceMappings": block_device_map,
            "InstanceMonitoring": {
                "Enabled": self.aws.get("monitoring", False)
            }
        }

        if self.instance_policy:
            self._create_instance_policy(self.instance_policy)
            launch_config_args['IamInstanceProfile'] = self.cluster_name

        return launch_config_args

    def _build_launch_config(self, block_device_map, cloud_init):
        kwargs = self._launch_config_args(block_device_map, cloud_init)
        self._create_launch_configs(**kwargs)

        return kwargs['LaunchConfigurationName']

    def _is_retryable_exception(exception):
        return not isinstance(exception, botocore.exceptions.ClientError) or \
            ((exception.response["Error"]["Code"] in ['InvalidIPAddress.InUse', 'InvalidInstanceID.NotFound'] or
            'Invalid IAM Instance Profile name' in exception.response["Error"]["Message"] or
            'Invalid IamInstanceProfile' in exception.response["Error"]["Message"]))

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _find_existing_instance(self, private_ip):
        filters = [
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
            {"Name": "private-ip-address", "Values": [private_ip]},
            {"Name": "tag:ClusterName", "Values": [self.cluster_name]}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                return instance

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_run_instances(self, private_ip, **kwargs):
        try:
            response = self.ec2.run_instances(**kwargs)
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "InvalidIPAddress.InUse":
                instance = self._find_existing_instance(private_ip)
                if instance:
                    instance_name = self._find_instance_name(instance)
                    instance_id = instance['InstanceId']
                    print "skipping %s %s (%s)" % (instance_id, instance_name, private_ip)
                    return None
            raise ex

        return response

    def _find_instance_name(self, instance):
        instance_name = ''
        for tag in instance.get('Tags', []):
            if 'Key' in tag:
                if tag['Key'].lower() == 'name':
                    return tag['Value']
        return instance_name

    def _asg_create(self, **kwargs):
        try:
            self._asg_create_auto_scaling_group(**kwargs)
            print 'created auto scaling group %s with size %s' % (self.cluster_name, kwargs['DesiredCapacity'])
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "AlreadyExists":
                print 'updated auto scaling group %s launch config %s' % (self.cluster_name, kwargs['LaunchConfigurationName'])
                self._asg_update(**kwargs)
            else:
                raise ex

    def _asg_update(self, **kwargs):
        self._asg_update_auto_scaling_group(
            AutoScalingGroupName=kwargs['AutoScalingGroupName'],
            LaunchConfigurationName=kwargs['LaunchConfigurationName'],
            VPCZoneIdentifier=kwargs['VPCZoneIdentifier'])

        tags = []
        for tag in kwargs.get('Tags', []):
            if 'Key' in tag and 'Value' in tag:
                tags.append({'ResourceId': kwargs['AutoScalingGroupName'],
                             'ResourceType': 'auto-scaling-group',
                             'Key': tag['Key'],
                             'Value': tag['Value'],
                             'PropagateAtLaunch': True})

        if len(tags) > 0:
            self._asg_create_or_update_tags(Tags=tags)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _asg_update_auto_scaling_group(self, **kwargs):
        return self.asg.update_auto_scaling_group(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _asg_create_auto_scaling_group(self, **kwargs):
        return self.asg.create_auto_scaling_group(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_create_tags(self, **kwargs):
        return self.ec2.create_tags(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _asg_create_or_update_tags(self, **kwargs):
        return self.asg.create_or_update_tags(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _create_launch_configs(self, **kwargs):
        return self.asg.create_launch_configuration(**kwargs)

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

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_images(self, **kwargs):
        return self.ec2.describe_images(**kwargs)['Images']

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _describe_asg(self, name):
        return self.asg.describe_auto_scaling_groups(
                    AutoScalingGroupNames=[name]
                )

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _delete_asg(self, name):
        self.asg.delete_auto_scaling_group(
                    AutoScalingGroupName=name
                )

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _delete_launch_config(self, name):
        self.asg.delete_launch_configuration(
                    LaunchConfigurationName=name
                )
