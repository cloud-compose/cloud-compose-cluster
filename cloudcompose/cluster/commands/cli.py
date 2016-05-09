import click
from cloudcompose.cluster.cloudinit import CloudInit
from cloudcompose.cluster.aws.cloudcontroller import CloudController
from cloudcompose.config import CloudConfig

@click.group()
def cli():
    pass

@cli.command()
@click.option('--cloud-init/--no-cloud-init', default=True)
def up(cloud_init):
    """
    creates a new cluster
    """
    cloud_config = CloudConfig()
    ci = None

    if cloud_init:
        ci = CloudInit()

    cloud_controller = CloudController(cloud_config)
    cloud_controller.up(ci)

@cli.command()
def down():
    """
    destroys an existing cluster
    """
    cloud_config = CloudConfig()
    cloud_controller = CloudController(cloud_config)
    cloud_controller.down()

@cli.command()
def build():
    """
    builds the cloud_init script
    """
    cloud_config = CloudConfig()
    config_data = cloud_config.config_data('cluster')
    cloud_init = CloudInit()
    print cloud_init.build(config_data)
