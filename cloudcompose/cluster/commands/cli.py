import click
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig
from cloudcompose.exceptions import CloudComposeException

@click.group()
def cli():
    pass

@cli.command()
@click.option('--cloud-init/--no-cloud-init', default=True, help="Initialize the instance with a cloud init script")
@click.option('--use-snapshots/--no-use-snapshots', default=True, help="Use snapshots to initialize volumes with existing data")
@click.option('--upgrade-image/--no-upgrade-image', default=False, help="Upgrade the image to the newest version instead of keeping the cluster consistent")
@click.option('--snapshot-cluster', help="Cluster name to use for snapshot retrieval. It defaults to the current cluster name.")
@click.option('--snapshot-time', help="Use a snapshot on or before this time. It defaults to the current time")
def up(cloud_init, use_snapshots, upgrade_image, snapshot_cluster, snapshot_time):
    """
    creates a new cluster
    """
    try:
        cloud_config = CloudConfig()
        ci = None

        if cloud_init:
            ci = CloudInit()

        cloud_controller = CloudController(cloud_config)
        cloud_controller.up(ci, use_snapshots, upgrade_image, snapshot_cluster, snapshot_time)
    except CloudComposeException as ex:
        print ex.message

@cli.command()
@click.option('--force/--no-force', default=False, help="Force the cluster to go down even if terminate protection is enabled")
def down(force):
    """
    destroys an existing cluster
    """
    try:
        cloud_config = CloudConfig()
        cloud_controller = CloudController(cloud_config)
        cloud_controller.down(force)
    except CloudComposeException as ex:
        print ex.message

@cli.command()
def cleanup():
    """
    deletes launch configs and auto scaling group
    """
    try:
        cloud_config = CloudConfig()
        cloud_controller = CloudController(cloud_config)
        cloud_controller.cleanup()
    except CloudComposeException as ex:
        print ex.message

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    try:
        cloud_config = CloudConfig()
        config_data = cloud_config.config_data('cluster')
        cloud_init = CloudInit()
        print cloud_init.build(config_data)
    except CloudComposeException as ex:
        print ex.message
