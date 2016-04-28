from pprint import pprint

class CloudController:
    def up(self, cloud_config):
        #TODO create the cloudwatch log group
        #TODO build cloud_init script
        self._create_instances(cloud_config)

    def _create_instances(self, cloud_config):
        block_device_map = self._build_block_device_map(cloud_config)
        pprint(block_device_map)

    def _build_block_device_map(self, cloud_config):
        config_data, _ = cloud_config.config_data('cluster')
        aws = config_data["aws"]
        block_device_map = []
        for volume in aws.get("volumes", []):
            block_device_map.append(self._create_volume_config(volume))

        return block_device_map

    def _create_volume_config(self, volume):
        volume_config = {
            "DeviceName": volume["block"],
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
