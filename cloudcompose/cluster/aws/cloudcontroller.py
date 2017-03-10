from os import environ
import sys
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
from gzip import GzipFile
from base64 import b64encode
from StringIO import StringIO
from dateutil.parser import parse
import pytz
from dateutil.tz import tzlocal

MAX_CLOUD_INIT_LENGTH = 16000

class CloudController:
    def __init__(self, cloud_config, ec2_client=None, asg_client=None, silent=False):
        logging.basicConfig(level=logging.ERROR)
        self.logger = logging.getLogger(__name__)
        self.cloud_config = cloud_config
        self.silent = silent
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

    def up(self, cloud_init=None, use_snapshots=True, upgrade_image=False, snapshot_cluster=None, snapshot_time=None):
        if snapshot_time and use_snapshots:
            snapshot_time = self._parse_localized_time(snapshot_time)
            if not self.silent:
                print 'restoring from snapshot created on or before %s' % snapshot_time.strftime('%Y-%m-%d %H:%M:%S %Z')

        self.aws['ami'] = self._resolve_ami_name(upgrade_image)
        block_device_map = self._block_device_map(use_snapshots, snapshot_cluster, snapshot_time)
        if self.log_driver == 'awslogs':
            self._create_log_group(self.log_group, self.log_retention)
        if self.aws.get('asg'):
            self._create_asg(block_device_map, cloud_init)
        else:
            self._create_instances(block_device_map, cloud_init)

    def _parse_localized_time(self, snapshot_time):
        snapshot_time = parse(snapshot_time)
        if snapshot_time.tzinfo is None or snapshot_time.tzinfo.utcoffset(snapshot_time) is None:
            snapshot_time = snapshot_time.replace(tzinfo=tzlocal())

        snapshot_time = snapshot_time.astimezone(pytz.UTC)
        return snapshot_time

    def down(self, force=False):
        if self.aws.get('asg'):
            asg_name = self.cluster_name
            try:
                self._asg_update_auto_scaling_group(
                                        AutoScalingGroupName=asg_name,
                                        MinSize=0,
                                        MaxSize=0,
                                        DesiredCapacity=0)
                if not self.silent:
                    print 'auto scaling group %s size is now 0' % asg_name
            except botocore.exceptions.ClientError as ex:
                if ex.response["Error"]["Code"] == 'ValidationError':
                    if not self.silent:
                        print 'auto scaling group %s does not exist' % asg_name
                else:
                    raise ex

        else:
            ips = [node['ip'] for node in self.aws.get('nodes', [])]
            instance_ids = self._instance_ids_from_private_ip(ips)
            if len(instance_ids) > 0:
                if force:
                    self._disable_terminate_protection(instance_ids)
                self._ec2_terminate_instances(InstanceIds=instance_ids)
                if not self.silent:
                    print 'terminated %s' % ','.join(instance_ids)

    def _disable_terminate_protection(self, instance_ids):
        for instance_id in instance_ids:
            self._ec2_modify_instance_attribute(InstanceId=instance_id, DisableApiTermination={"Value": False})


    def cleanup(self):
        if self.aws.get('asg'):
            asg_name = self.cluster_name
            asg_details = self._describe_asg(asg_name)

            asg_lc = asg_details["AutoScalingGroups"][0]["LaunchConfigurationName"]
            asg_instances = len(asg_details["AutoScalingGroups"][0]["Instances"])

            if asg_instances != 0:
                if not self.silent:
                    print 'unable to delete autoscaling group %s because of %s active instances' % (asg_name, asg_instances)
                    print 'run cloud-compose cluster down first or wait for instances to terminate'
            else:
                self._delete_asg(asg_name)
                if not self.silent:
                    print 'deleted autoscaling group %s' % asg_name

                self._delete_launch_config(asg_lc)
                if not self.silent:
                    print 'deleted launch configuration %s' % asg_lc
        else:
            if not self.silent:
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
            if not self.silent:
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

    def _block_device_map(self, use_snapshots, snapshot_cluster, snapshot_time):
        controller = EBSController(self.ec2, self.cluster_name, silent=self.silent)
        default_device = self._find_device_from_ami(self.aws['ami'])
        return controller.block_device_map(self.aws['volumes'], default_device, use_snapshots, snapshot_cluster, snapshot_time)

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
        instance_type = self.aws.get('instance_type', 't2.medium')
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
        elb_list   = self.aws['asg'].get('elbs', [])
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
            'LoadBalancerNames': elb_list,
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
                kwargs['UserData'] = self._cloud_init_build(cloud_init, node_id=node['id'])

            max_retries = 6
            retries = 0
            while retries < max_retries:
                retries += 1
                try:
                    instance_id, created = self._ec2_run_instances(private_ip, **kwargs)
                    if instance_id:
                        instances[node['id']] = (instance_id, private_ip, created, node.get("eip"), self.aws.get("source_dest_check", True))
                    break
                except botocore.exceptions.ClientError as ex:
                    if not self.silent:
                        print(ex.response["Error"]["Message"])

        for node_id, instance_data in instances.iteritems():
            instance_id = instance_data[0]
            private_ip = instance_data[1]
            created = instance_data[2]
            elastic_ip = instance_data[3]
            source_dest_check = instance_data[4]

            instance_name = "%s-%s" % (self.cluster_name, node_id)
            self._tag_instance(self.aws.get("tags", {}), node_id, instance_id)
            if elastic_ip:
                self._associate_eip(instance_id, elastic_ip)
            if not source_dest_check:
                self._disable_source_dest_check(instance_id)
            prefix = 'skipping'
            if created:
                prefix = 'created'
            if not self.silent:
                print "%s %s %s (%s)" % (prefix, instance_id, instance_name, private_ip)

    def _disable_source_dest_check(self, instance_id):
        self._wait_for_running(instance_id)
        self._ec2_modify_instance_attribute(InstanceId=instance_id, SourceDestCheck={'Value': False})

    def _associate_eip(self, instance_id, allocation_id):
        self._wait_for_running(instance_id)
        self._ec2_associate_address(InstanceId=instance_id, AllocationId=allocation_id, AllowReassociation=False)

    def _wait_for_running(self, instance_id):
        status = 'pending'
        if not self.silent:
            sys.stdout.write("%s is pending start" % instance_id)
            sys.stdout.flush()

        while status == 'pending':
            status = self._instance_status(instance_id)
            time.sleep(1)
            if not self.silent:
                sys.stdout.write('.')
                sys.stdout.flush()

        if not self.silent:
            print ""

    def _instance_status(self, instance_id):
        filters = [
            {
                "Name": "instance-id",
                "Values": [instance_id]
            }
        ]
        instances = self._ec2_describe_instances(Filters=filters)["Reservations"]
        if len(instances) != 1:
            raise Exception("Expected one instance for %s and got %s" % (instance_id, len(instances)))
        return instances[0]["Instances"][0]["State"]["Name"]

    def _cloud_init_build(self, cloud_init, **kwargs):
        cloud_init_script = cloud_init.build(self.config_data, **kwargs)
        if len(cloud_init_script) > MAX_CLOUD_INIT_LENGTH:
            output = StringIO()
            with GzipFile(mode='wb', fileobj=output) as gzfile:
                gzfile.write(cloud_init_script)
            cloud_init_script = "#!/bin/bash\necho '%s' | base64 -d | gunzip | /bin/bash" % b64encode(output.getvalue())

        return cloud_init_script

    def _create_instance_policy(self, instance_policy):
        controller = InstancePolicyController(self.cluster_name)
        controller.create_instance_policy(instance_policy)

    def _create_log_group(self, log_group, log_retention):
        controller = LogsController()
        controller.create_log_group(log_group, log_retention)

    def _tag_instance(self, tags, node_id, instance_id):
        tags['Name'] = '%s-%s' % (self.cluster_name, node_id)
        instance_tags = self._build_instance_tags(tags)
        self._ec2_create_tags(Resources=[instance_id], Tags=instance_tags)

        #NodeId tag is no longer set, this will remove it for existing clusters
        #This code can be removed in the next release
        remove_tags = [{'Key': 'NodeId'}]
        self._ec2_delete_tags(Resources=[instance_id], Tags=remove_tags)

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
            cloud_init_script = self._cloud_init_build(cloud_init, node_id=cluster_name)

        instance_type = self.aws.get('instance_type', None)

        if not instance_type:
            existing_instance_type = self._existing_instance_type_from_asg(self.cluster_name)
            if existing_instance_type:
                instance_type = existing_instance_type
            else:
                instance_type = 't2.medium'

        launch_config_args = {
            "LaunchConfigurationName": lc_name,
            "ImageId": self.aws['ami'],
            "SecurityGroups": self.security_groups(),
            "InstanceType": instance_type,
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

    def _existing_instance_type_from_asg(self, cluster_name):
        for asg in self._asg_describe_auto_scaling_groups(AutoScalingGroupNames=[cluster_name]).get('AutoScalingGroups', []):
            lc_name = asg.get('LaunchConfigurationName', None)
            if lc_name:
                for launch_config in self._asg_describe_launch_configurations(LaunchConfigurationNames=[lc_name]).get('LaunchConfigurations', []):
                    instance_type = launch_config.get('InstanceType', None)
                    if instance_type:
                        return instance_type
        return None

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
            return response['Instances'][0]['InstanceId'], True
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "InvalidIPAddress.InUse":
                instance = self._find_existing_instance(private_ip)
                if instance:
                    instance_name = self._find_instance_name(instance)
                    instance_id = instance['InstanceId']
                    return instance_id, False
                else:
                    if not self.silent:
                        print('%s in use but not by an instance' % private_ip)
            raise ex
        return None, False

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
            if not self.silent:
                print 'created auto scaling group %s with size %s' % (self.cluster_name, kwargs['DesiredCapacity'])
        except botocore.exceptions.ClientError as ex:
            if ex.response["Error"]["Code"] == "AlreadyExists":
                if not self.silent:
                    print 'updated auto scaling group %s launch config %s' % (self.cluster_name, kwargs['LaunchConfigurationName'])
                self._asg_update(**kwargs)
            else:
                raise ex

    def _asg_update(self, **kwargs):
        tags = kwargs.get('Tags', [])
        self._asg_update_auto_scaling_group(
            AutoScalingGroupName=kwargs['AutoScalingGroupName'],
            LaunchConfigurationName=kwargs['LaunchConfigurationName'],
            VPCZoneIdentifier=kwargs['VPCZoneIdentifier'])

        asg_tags = []
        for tag in tags:
            if 'Key' in tag and 'Value' in tag:
                asg_tags.append({'ResourceId': kwargs['AutoScalingGroupName'],
                             'ResourceType': 'auto-scaling-group',
                             'Key': tag['Key'],
                             'Value': tag['Value'],
                             'PropagateAtLaunch': True})

        if len(asg_tags) > 0:
            self._asg_create_or_update_tags(Tags=asg_tags)
            self._tag_existing_asg_instances(tags)

    def _tag_existing_asg_instances(self, tags):
        instance_ids = []
        filters = [
            {"Name": "instance-state-name", "Values": ["running", "pending"]},
            {"Name": "tag:aws:autoscaling:groupName", "Values": [self.cluster_name]}
        ]

        instances = self._ec2_describe_instances(Filters=filters)
        for reservation in instances.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                instance_ids.append(instance['InstanceId'])

        if len(instance_ids) > 0:
            self._ec2_create_tags(Resources=instance_ids, Tags=tags)

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
    def _ec2_delete_tags(self, **kwargs):
        return self.ec2.delete_tags(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _asg_describe_auto_scaling_groups(self, **kwargs):
        return self.asg.describe_auto_scaling_groups(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _asg_describe_launch_configurations(self, **kwargs):
        return self.asg.describe_launch_configurations(**kwargs)

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
    def _ec2_modify_instance_attribute(self, **kwargs):
        return self.ec2.modify_instance_attribute(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_instances(self, **kwargs):
        return self.ec2.describe_instances(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_describe_images(self, **kwargs):
        return self.ec2.describe_images(**kwargs)['Images']

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_modify_instance_attribute(self, **kwargs):
        return self.ec2.modify_instance_attribute(**kwargs)

    @retry(retry_on_exception=_is_retryable_exception, stop_max_delay=10000, wait_exponential_multiplier=500, wait_exponential_max=2000)
    def _ec2_associate_address(self, **kwargs):
        return self.ec2.associate_address(**kwargs)

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
