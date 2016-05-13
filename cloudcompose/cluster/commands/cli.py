import click
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig

@click.group()
def cli():
    pass

@cli.command()
@click.option('--cloud-init/--no-cloud-init', default=True, help="Initialize the instance with a cloud init script")
@click.option('--use-snapshots/--no-use-snapshots', default=True, help="Use snapshots to initialize volumes with existing data")
@click.option('--upgrade-image/--no-upgrade-image', default=False, help="Upgrade the image to the newest version instead of keeping the cluster consistent")
def up(cloud_init, use_snapshots, upgrade_image):
    """
    creates a new cluster
    """
    cloud_config = CloudConfig()
    ci = None

    if cloud_init:
        ci = CloudInit()

    cloud_controller = CloudController(cloud_config)
    cloud_controller.up(ci, use_snapshots, upgrade_image)

@cli.command()
def down():
    """
    destroys an existing cluster
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.down()

@cli.command()
def cleanup():
    """
    deletes launch configs and auto scaling group
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.cleanup()

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    cloud_config = CloudConfig()
    config_data = cloud_config.config_data('cluster')
    cloud_init = CloudInit()
    print cloud_init.build(config_data)
